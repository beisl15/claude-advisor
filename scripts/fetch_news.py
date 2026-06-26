#!/usr/bin/env python3
"""
Generates data/news.json: headlines from many sources via RSS/Atom, grouped by
REGION (Brazil / US / World) and ranked by relevance to the portfolio.

Sources (two layers):
  1) General feeds per region — publisher RSS + Google News topic searches.
  2) Portfolio-targeted Google News searches — one query per holding so every
     name in the book gets dedicated coverage (tagged with the ticker).

Ranking:
  - No key: heuristic (portfolio keyword priority + recency).
  - With ANTHROPIC_API_KEY (repo secret): the model curates each region —
    picks the most relevant, writes a 1-line summary + a 1-line "provocation"
    (implication for the book), in English. Heuristic is the fallback.

Robustness: each feed has retries; a health summary (per-source counts) is
printed at the end so silent failures are visible in the Actions log.

Manual reading shortcuts (paywall/login) are added under "manual": Bloomberg,
WSJ, Financial Times, Seeking Alpha. We do not scrape those.
"""
import json, re, os, datetime, sys, time, urllib.request, urllib.parse
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

OUT = os.path.join(os.path.dirname(__file__), "..", "data", "news.json")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
PER_REGION = 8                  # headlines kept per region
POOL_PER_REGION = 28           # candidates considered per region before ranking
PORTFOLIO = ("GOOGL MSFT META AMZN NVDA MU ASML JPM BLK AAPL AMD AVGO TSM MELI RACE "
             "Nubank PRIO Sabesp Copasa Smartfit Vale Itau Petrobras Ambev TOTVS Vivo TIM BTG")


def gnews(query, lang="en"):
    """Build a Google News RSS search URL (very reliable, many publishers)."""
    loc = {"en": ("en-US", "US", "US:en"), "pt": ("pt-BR", "BR", "BR:pt")}[lang]
    q = urllib.parse.quote(query)
    return f"https://news.google.com/rss/search?q={q}&hl={loc[0]}&gl={loc[1]}&ceid={loc[2]}"


# General feeds: (region, source_name, url)
FEEDS = [
    # ── Brazil ──────────────────────────────────────────────────────────────
    ("BR", "Brazil Journal", "https://braziljournal.com/feed/"),
    ("BR", "InfoMoney",      "https://www.infomoney.com.br/feed/"),
    ("BR", "Money Times",    "https://www.moneytimes.com.br/feed/"),
    ("BR", "Valor",          gnews("site:valor.globo.com when:2d", "pt")),
    ("BR", "Google News BR", gnews("(bolsa OR ibovespa OR mercado financeiro OR juros OR Selic) when:1d", "pt")),
    # ── United States ───────────────────────────────────────────────────────
    ("US", "CNBC",           "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20910258"),
    ("US", "CNBC",           "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114"),
    ("US", "MarketWatch",    "https://feeds.marketwatch.com/marketwatch/topstories/"),
    ("US", "MarketWatch",    "https://feeds.marketwatch.com/marketwatch/marketpulse/"),
    ("US", "Yahoo Finance",  "https://finance.yahoo.com/news/rssindex"),
    ("US", "Google News US", gnews("(stock market OR S&P 500 OR Nasdaq OR Federal Reserve OR earnings) when:1d", "en")),
    # ── World ───────────────────────────────────────────────────────────────
    ("WORLD", "Reuters",     gnews("site:reuters.com (markets OR economy OR business) when:1d", "en")),
    ("WORLD", "Bloomberg",   gnews("site:bloomberg.com (markets OR stocks OR economy) when:1d", "en")),
    ("WORLD", "Financial Times", gnews("site:ft.com (markets OR companies) when:2d", "en")),
    ("WORLD", "Investing.com", "https://www.investing.com/rss/news.rss"),
    ("WORLD", "Google News World", gnews("(global markets OR semiconductors OR AI chips OR oil prices) when:1d", "en")),
]

# Portfolio-targeted searches: (region, tag, query, lang). One per holding.
COMPANY_FEEDS = [
    ("US", "NVDA",          "Nvidia stock when:2d", "en"),
    ("US", "MSFT",          "Microsoft stock when:2d", "en"),
    ("US", "META",          "Meta Platforms stock when:2d", "en"),
    ("US", "GOOGL",         "Alphabet Google stock when:2d", "en"),
    ("US", "AMZN",          "Amazon stock when:2d", "en"),
    ("US", "AAPL",          "Apple stock when:2d", "en"),
    ("US", "AMD",           "AMD stock when:2d", "en"),
    ("US", "AVGO",          "Broadcom stock when:2d", "en"),
    ("US", "MU",            "Micron HBM memory when:2d", "en"),
    ("US", "JPM · BLK",     "(JPMorgan OR BlackRock) when:2d", "en"),
    ("US", "VZ · Telecom",  "(Verizon OR T-Mobile OR AT&T) when:2d", "en"),
    ("WORLD", "ASML · TSM", "(ASML OR TSMC) semiconductors when:2d", "en"),
    ("WORLD", "MELI",       "MercadoLibre when:2d", "en"),
    ("WORLD", "RACE",       "Ferrari stock when:3d", "en"),
    ("WORLD", "ABI · ABEV", "(AB InBev OR Ambev) when:3d", "en"),
    ("BR", "PETR · PRIO",   "(Petrobras OR PRIO petróleo) when:2d", "pt"),
    ("BR", "VALE",          "Vale minério when:2d", "pt"),
    ("BR", "ITUB · BTG",    "(Itaú OR BTG Pactual) when:2d", "pt"),
    ("BR", "NU · Fintech",  "(Nubank OR Nu Holdings) when:2d", "pt"),
    ("BR", "SBSP · CSMG",   "(Sabesp OR Copasa saneamento) when:3d", "pt"),
    ("BR", "SMFT",          "Smartfit when:4d", "pt"),
    ("BR", "TOTS · VIVT",   "(TOTVS OR Vivo Telefônica) when:3d", "pt"),
]

# Manual reading shortcuts (paywall/login — not scraped)
MANUAL = [
    ("Bloomberg",       "https://www.bloomberg.com/markets"),
    ("WSJ Markets",     "https://www.wsj.com/news/markets"),
    ("Financial Times", "https://www.ft.com/markets"),
    ("Seeking Alpha",   "https://seekingalpha.com/market-news"),
]

RULES = [  # (regex, priority, tag) — used for scoring when no AI key
    (r"sabesp|saneamento|copasa", 5, "SBSP3 · CSMG3"),
    (r"smart\s?fit|smartfit", 5, "SMFT3"),
    (r"\bprio\b|petrorio|petrobras|petr[oó]leo|brent|\boil\b|crude", 5, "PRIO3 · O&G"),
    (r"\bvale\b|min[eé]rio|iron ore", 4, "VALE3"),
    (r"micron|\bmu\b|mem[oó]ria|memory|\bhbm\b|semicondutor|semiconductor|chips?|asml", 4, "MU · ASML"),
    (r"nvidia|\bnvda\b", 5, "NVDA"),
    (r"verizon|t-mobile|tmus|at&t|\bat t\b", 4, "VZ · Telecom"),
    (r"\bmeta\b|google|alphabet|googl|microsoft|\bmsft\b|amazon|\bamzn\b|\baapl\b|apple", 4, "US Big Tech"),
    (r"\bamd\b|broadcom|avgo|marvell|mrvl|intel|\bintc\b|\btsmc\b|\btsm\b", 4, "Semis US"),
    (r"ita[uú]|nubank|nu holdings|bradesco|\bbtg\b|banco|fintech|jpmorgan|\bjpm\b|blackrock|\bblk\b", 3, "Banks/Asset"),
    (r"ambev|cerveja|beer|\babi\b|ab inbev", 3, "ABEV3 · ABI"),
    (r"totvs", 3, "TOTS3"),
    (r"mercado ?libre|meli", 4, "MELI"), (r"ferrari|\brace\b", 3, "RACE"),
    (r"\bai\b|intelig[eê]ncia artificial|artificial intelligence|datacenter|data center", 3, "AI"),
    (r"selic|copom|\bfed\b|\becb\b|rate cut|rate hike|juros|infla[cç][aã]o|inflation|c[aâ]mbio|d[oó]lar|fiscal|lula|tariff|tarifa", 2, "Macro"),
    (r"ibovespa|\bbolsa\b|s&p ?500|nasdaq|dow|stoxx|ipo|follow-on|earnings|resultado", 2, "Market"),
]

ATOM = "{http://www.w3.org/2005/Atom}"


def get(url, tries=3):
    last = None
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA,
                "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read()
        except Exception as e:
            last = e
            time.sleep(1.5 * (k + 1))
    raise last


def parse_date(s):
    if not s:
        return None
    s = s.strip()
    try:
        return parsedate_to_datetime(s)
    except Exception:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.datetime.strptime(s, fmt)
        except Exception:
            continue
    return None


def strip_tags(t):
    t = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", t or "", flags=re.S)
    t = re.sub(r"<[^>]+>", "", t)
    return re.sub(r"\s+", " ", t).strip()


def norm_title(t):
    """Normalized title for de-duplication (drop ' - Publisher' suffix + punctuation)."""
    t = re.sub(r"\s+-\s+[^-]{2,40}$", "", t)          # google news " - Reuters"
    t = re.sub(r"[^a-z0-9 ]", "", t.lower())
    return re.sub(r"\s+", " ", t).strip()[:90]


def split_src(title, fallback):
    """Google News titles end with ' - Publisher' — use it as the source name."""
    m = re.search(r"\s-\s([^-]{2,40})$", title)
    if m:
        return title[:m.start()].strip(), m.group(1).strip()
    return title, fallback


def entries(root):
    """Yield (title, link, date) for both RSS <item> and Atom <entry>."""
    found = list(root.iter("item"))
    if found:
        for it in found:
            yield (strip_tags(it.findtext("title") or ""),
                   (it.findtext("link") or "").strip(),
                   parse_date(it.findtext("pubDate")))
        return
    for it in root.iter(ATOM + "entry"):                # Atom feeds
        link = ""
        for lk in it.findall(ATOM + "link"):
            if lk.get("rel", "alternate") == "alternate" or not link:
                link = lk.get("href", "") or link
        date = parse_date(it.findtext(ATOM + "published") or it.findtext(ATOM + "updated"))
        yield (strip_tags(it.findtext(ATOM + "title") or ""), link.strip(), date)


def harvest():
    items, seen_url, seen_title, health = [], set(), set(), []
    sources = ([(r, n, u, None, "g") for r, n, u in FEEDS] +
               [(r, t, gnews(q, lang), t, "c") for r, t, q, lang in COMPANY_FEEDS])
    for region, name, url, forced_tag, kind in sources:
        try:
            root = ET.fromstring(get(url))
        except Exception as e:
            health.append(f"  x {name} [{region}]: {type(e).__name__}")
            continue
        added = 0
        for title, link, date in entries(root):
            if kind == "c":
                title, src = split_src(title, name)        # company query → real publisher
            else:
                title, src = (split_src(title, name) if "news.google.com" in url else (title, name))
            if len(title) < 20 or not link:
                continue
            nt = norm_title(title)
            if link in seen_url or (nt and nt in seen_title):
                continue
            seen_url.add(link); seen_title.add(nt)
            items.append({"region": region, "src": src, "title": title,
                          "url": link, "dt": date, "ftag": forced_tag})
            added += 1
        health.append(f"  ok {name} [{region}]: +{added}")
    return items, health


def score(it):
    t = it["title"].lower()
    base = 0
    for rx, pri, tag in RULES:
        if re.search(rx, t):
            base, btag = pri, tag
            break
    else:
        btag = "Market"
    if it.get("ftag"):                                     # company-targeted → at least P3
        return max(base, 3), it["ftag"]
    return base, btag


def rank_region(items, region):
    pool = [it for it in items if it["region"] == region]

    def key(it):
        pri, _ = score(it)
        ts = it["dt"].timestamp() if it["dt"] else 0
        return (-pri, -ts)
    pool.sort(key=key)
    out = []
    for it in pool[:POOL_PER_REGION]:
        pri, tag = score(it)
        d = it["dt"]
        out.append(dict(region=region, p=pri or 2, tag=tag, src=it["src"], title=it["title"],
                        resumo="", prov=(f"Relevant to {tag}." if pri else ""),
                        url=it["url"], date=d.strftime("%d/%m") if d else ""))
    return out


def llm_curate(pool_by_region, key):
    """Model picks the most relevant per region and writes summary + provocation (English)."""
    model = os.environ.get("NEWS_MODEL", "claude-haiku-4-5-20251001")
    flat, idx = [], 0
    listing = []
    for region in ("BR", "US", "WORLD"):
        for it in pool_by_region[region]:
            flat.append(it)
            listing.append(f"{idx}. [{region}] {it['title']} ({it['src']})")
            idx += 1
    prompt = (
        f"You are a buy-side analyst. Portfolio: {PORTFOLIO}.\n"
        f"Candidate headlines (index, region, title, source):\n" + "\n".join(listing) + "\n\n"
        f"Select the {PER_REGION} most relevant headlines FOR EACH region (BR, US, WORLD). "
        "Prefer items that move a portfolio name or its sector. For each selected item write, IN ENGLISH, "
        "a one-sentence summary and a one-sentence 'provocation' (the implication for the book), plus a short tag "
        "(ticker or theme) and a priority 1-5 (5=critical, 1=awareness).\n"
        'Return ONLY a JSON array: '
        '[{"i":index,"p":1-5,"tag":"...","resumo":"...","prov":"..."}]')
    body = json.dumps({"model": model, "max_tokens": 4000,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body,
                                 headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                                          "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        d = json.load(r)
    txt = "".join(c.get("text", "") for c in d.get("content", []))
    arr = json.loads(re.search(r"\[.*\]", txt, re.S).group(0))
    picked = []
    for o in arr:
        i = o.get("i")
        if not isinstance(i, int) or not (0 <= i < len(flat)):
            continue
        it = flat[i]
        d2 = it["dt"]
        picked.append(dict(region=it["region"], p=int(o.get("p", 3)),
                           tag=o.get("tag") or "Market", src=it["src"], title=it["title"],
                           resumo=o.get("resumo", ""), prov=o.get("prov", ""),
                           url=it["url"], date=d2.strftime("%d/%m") if d2 else ""))
    # keep region balance / cap
    out = []
    for region in ("BR", "US", "WORLD"):
        out += [x for x in picked if x["region"] == region][:PER_REGION]
    return out


def main():
    items, health = harvest()
    print(f"harvested {len(items)} unique headlines from {len(FEEDS)+len(COMPANY_FEEDS)} sources")
    print("\n".join(health))

    pool_by_region = {r: [x for x in rank_region(items, r)] for r in ("BR", "US", "WORLD")}
    # convert ranked dicts back to raw-ish for llm pool (need url/dt/src/title)
    raw_by_region = {r: [it for it in items if it["region"] == r] for r in ("BR", "US", "WORLD")}
    for r in raw_by_region:
        raw_by_region[r].sort(key=lambda it: (-score(it)[0], -(it["dt"].timestamp() if it["dt"] else 0)))
        raw_by_region[r] = raw_by_region[r][:POOL_PER_REGION]

    selected = []
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        try:
            selected = llm_curate(raw_by_region, key)
            print(f"AI-curated: {len(selected)} items")
        except Exception as e:
            print(f"  ! AI curation failed ({e}); using heuristic", file=sys.stderr)
    if not selected:
        for r in ("BR", "US", "WORLD"):
            selected += pool_by_region[r][:PER_REGION]

    data = {
        "asof": datetime.date.today().strftime("%d/%m/%Y"),
        "items": selected,
        "manual": [{"name": n, "url": u} for n, u in MANUAL],
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    by = {r: sum(1 for x in selected if x["region"] == r) for r in ("BR", "US", "WORLD")}
    srcs = sorted({x["src"] for x in selected})
    print(f"-> {OUT} ({len(selected)} items; {by})")
    print(f"   sources in output: {', '.join(srcs)}")


if __name__ == "__main__":
    main()

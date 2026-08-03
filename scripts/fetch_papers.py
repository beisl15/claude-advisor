#!/usr/bin/env python3
"""
Generates data/papers.json: recent research/working papers from free RSS feeds
(NBER, BIS, IMF, Fed, arXiv q-fin / cs.AI), scored by relevance to the
portfolio's themes (AI/semis, monetary policy, Brazil/EM, banking, energy...).

No API keys required. Same robustness pattern as fetch_news.py:
retries per feed + health summary printed for the Actions log.
"""
import json, re, os, datetime, time, urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

OUT = os.path.join(os.path.dirname(__file__), "..", "data", "papers.json")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
MAX_ITEMS = 30          # total kept in the output
MAX_AGE_DAYS = 45       # papers older than this are dropped (arXiv floods otherwise)
ATOM = "{http://www.w3.org/2005/Atom}"

# (source_name, url)
FEEDS = [
    ("NBER",        "https://www.nber.org/rss/new.xml"),
    ("BIS",         "https://www.bis.org/doclist/wppubls.rss"),
    ("IMF",         "https://www.imf.org/en/Publications/RSS?language=eng&series=IMF%20Working%20Papers"),
    ("Fed (FEDS)",  "https://www.federalreserve.gov/feeds/feds.xml"),
    ("arXiv q-fin", "https://rss.arxiv.org/rss/q-fin"),
    ("arXiv cs.AI", "https://rss.arxiv.org/rss/cs.AI"),
]

# (regex, priority 1-5, tag) — theme relevance to the book
RULES = [
    (r"artificial intelligence|large language|\bllm\b|generative ai|machine learning|deep learning|\bai\b", 5, "AI"),
    (r"semiconductor|chip|compute|gpu|data.?cent", 5, "Semis"),
    (r"monetary policy|interest rate|inflation|central bank|federal reserve|\bfomc\b", 4, "Macro/Rates"),
    (r"brazil|latin america|emerging market", 5, "BR/EM"),
    (r"equity|stock market|asset pricing|portfolio|factor|valuation", 4, "Equities"),
    (r"bank|credit|fintech|financial stability|lending", 3, "Banks/Fintech"),
    (r"oil|energy|commodit", 3, "Energy/Commod"),
    (r"productivity|labor market|automation", 3, "Productivity"),
    (r"trade|tariff|supply chain|geopolit", 3, "Trade/Geo"),
    (r"housing|real estate|fiscal|debt|exchange rate|currency", 2, "Macro"),
]

# arXiv cs.AI is huge and mostly engineering — require an econ/market angle too
CSAI_EXTRA = re.compile(r"econom|financ|market|trading|invest|forecast|labor|productivity|macro", re.I)


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
    try:
        return parsedate_to_datetime(s.strip())
    except Exception:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(s.strip(), fmt)
        except Exception:
            continue
    return None


def strip_tags(t):
    t = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", t or "", flags=re.S)
    t = re.sub(r"<[^>]+>", "", t)
    return re.sub(r"\s+", " ", t).strip()


def entries(root):
    found = list(root.iter("item"))
    if found:
        for it in found:
            yield (strip_tags(it.findtext("title") or ""),
                   (it.findtext("link") or "").strip(),
                   parse_date(it.findtext("pubDate")),
                   strip_tags(it.findtext("description") or ""))
        return
    for it in root.iter(ATOM + "entry"):
        link = ""
        for lk in it.findall(ATOM + "link"):
            if lk.get("rel", "alternate") == "alternate" or not link:
                link = lk.get("href", "") or link
        date = parse_date(it.findtext(ATOM + "published") or it.findtext(ATOM + "updated"))
        yield (strip_tags(it.findtext(ATOM + "title") or ""), link.strip(), date,
               strip_tags(it.findtext(ATOM + "summary") or ""))


def score(title, desc):
    text = (title + " " + desc[:400]).lower()
    for rx, pri, tag in RULES:
        if re.search(rx, text):
            return pri, tag
    return 0, ""


def main():
    now = datetime.datetime.now(datetime.timezone.utc)
    items, seen, health = [], set(), []
    for name, url in FEEDS:
        try:
            root = ET.fromstring(get(url))
        except Exception as e:
            health.append(f"  x {name}: {type(e).__name__}")
            continue
        added = 0
        for title, link, date, desc in entries(root):
            if len(title) < 15 or not link or link in seen:
                continue
            if date:
                d = date if date.tzinfo else date.replace(tzinfo=datetime.timezone.utc)
                if (now - d).days > MAX_AGE_DAYS:
                    continue
            pri, tag = score(title, desc)
            if pri == 0:
                continue
            if name == "arXiv cs.AI" and not CSAI_EXTRA.search(title + " " + desc[:400]):
                continue
            seen.add(link)
            items.append({"p": pri, "tag": tag, "src": name, "title": title, "url": link,
                          "date": date.strftime("%d/%m") if date else "",
                          "_ts": date.timestamp() if date else 0})
            added += 1
        health.append(f"  ok {name}: +{added}")

    items.sort(key=lambda x: (-x["p"], -x["_ts"]))
    # source diversity: cap arXiv so institutional papers aren't drowned out
    out, per_src = [], {}
    for it in items:
        cap = 8 if it["src"].startswith("arXiv") else 12
        if per_src.get(it["src"], 0) >= cap:
            continue
        per_src[it["src"]] = per_src.get(it["src"], 0) + 1
        it.pop("_ts", None)
        out.append(it)
        if len(out) >= MAX_ITEMS:
            break

    data = {"asof": datetime.date.today().strftime("%d/%m/%Y"), "items": out}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    print("\n".join(health))
    print(f"-> {OUT} ({len(out)} papers)")


if __name__ == "__main__":
    main()

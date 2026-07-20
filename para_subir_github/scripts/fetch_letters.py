#!/usr/bin/env python3
"""
Generates data/letters.json: investor letters & memos.

Two source types:
  - "rss":  blogs/memos with a real feed (Damodaran, Collab Fund, ...).
  - "page": gestora letter pages with no RSS (Dynamo, IP, Verde, Oaktree...).
            We scrape the page for links that look like letters (carta/letter/
            memo/.pdf), and diff against what we've seen before — so an item
            only surfaces as "new" once, with the date we first saw it.

State: the output file itself is the state. Previously seen URLs are kept
(with their first-seen date) so GitHub Actions runs are incremental.
No API keys required.
"""
import json, re, os, datetime, time, urllib.request, urllib.parse
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser

OUT = os.path.join(os.path.dirname(__file__), "..", "data", "letters.json")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
MAX_ITEMS = 60          # history kept in the output
PER_PAGE = 5            # newest links considered per gestora page
RSS_MAX_AGE_DAYS = 60
ATOM = "{http://www.w3.org/2005/Atom}"

# ("rss"|"page", source_name, url)
SOURCES = [
    # ── RSS (blogs / memos) ─────────────────────────────────────────────────
    ("rss",  "Damodaran (Musings)", "https://aswathdamodaran.blogspot.com/feeds/posts/default?alt=rss"),
    ("rss",  "Collab Fund",         "https://collabfund.com/feed/"),
    ("rss",  "Klement on Investing","https://klementoninvesting.substack.com/feed"),
    # ── Gestora / manager letter pages (scraped for new links) ─────────────
    ("page", "Dynamo",              "https://www.dynamo.com.br/pt/cartas"),
    ("page", "IP Capital Partners", "https://ip-capitalpartners.com/relatorios/"),
    ("page", "Verde Asset",         "https://verdeasset.com.br/cartas/"),
    ("page", "Squadra",             "https://www.squadrainvest.com.br/cartas/"),
    ("page", "Oaktree (H. Marks)",  "https://www.oaktreecapital.com/insights/memos"),
    ("page", "Berkshire Hathaway",  "https://www.berkshirehathaway.com/letters/letters.html"),
]

LINK_RX = re.compile(r"carta|letter|memo|relat[oó]rio|report|\.pdf", re.I)
SKIP_RX = re.compile(r"facebook|twitter|linkedin|instagram|whatsapp|mailto:|javascript:|#$|/cookie|/privac|/termo", re.I)


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self._href, self._buf = [], None, []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._buf = []

    def handle_data(self, d):
        if self._href is not None:
            self._buf.append(d)

    def handle_endtag(self, tag):
        if tag == "a" and self._href:
            self.links.append((self._href, re.sub(r"\s+", " ", "".join(self._buf)).strip()))
            self._href = None


def get(url, tries=3):
    last = None
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
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
        return None


def strip_tags(t):
    t = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", t or "", flags=re.S)
    t = re.sub(r"<[^>]+>", "", t)
    return re.sub(r"\s+", " ", t).strip()


def rss_entries(root):
    found = list(root.iter("item"))
    if found:
        for it in found:
            yield (strip_tags(it.findtext("title") or ""),
                   (it.findtext("link") or "").strip(),
                   parse_date(it.findtext("pubDate")))
        return
    for it in root.iter(ATOM + "entry"):
        link = ""
        for lk in it.findall(ATOM + "link"):
            if lk.get("rel", "alternate") == "alternate" or not link:
                link = lk.get("href", "") or link
        yield (strip_tags(it.findtext(ATOM + "title") or ""), link.strip(),
               parse_date(it.findtext(ATOM + "published") or it.findtext(ATOM + "updated")))


def page_links(base_url, html):
    p = LinkParser()
    try:
        p.feed(html)
    except Exception:
        pass
    out, seen = [], set()
    for href, text in p.links:
        if not href or SKIP_RX.search(href):
            continue
        blob = href + " " + text
        if not LINK_RX.search(blob):
            continue
        url = urllib.parse.urljoin(base_url, href)
        if url in seen or url.rstrip("/") == base_url.rstrip("/"):
            continue
        seen.add(url)
        title = text if len(text) >= 6 else os.path.basename(urllib.parse.urlparse(url).path)
        out.append((title[:140], url))
        if len(out) >= PER_PAGE:
            break
    return out


def main():
    today = datetime.date.today()
    now = datetime.datetime.now(datetime.timezone.utc)

    # previous state (the output file itself)
    prev = {}
    try:
        with open(OUT) as f:
            for it in json.load(f).get("items", []):
                prev[it["url"]] = it
    except Exception:
        pass

    items, health = dict(prev), []
    for kind, name, url in SOURCES:
        try:
            raw = get(url)
        except Exception as e:
            health.append(f"  x {name}: {type(e).__name__}")
            continue
        added = 0
        if kind == "rss":
            try:
                root = ET.fromstring(raw)
            except Exception as e:
                health.append(f"  x {name}: parse {type(e).__name__}")
                continue
            for title, link, date in rss_entries(root):
                if not link or len(title) < 6 or link in items:
                    continue
                if date:
                    d = date if date.tzinfo else date.replace(tzinfo=datetime.timezone.utc)
                    if (now - d).days > RSS_MAX_AGE_DAYS:
                        continue
                items[link] = {"src": name, "title": title, "url": link,
                               "date": (date.strftime("%d/%m/%Y") if date else today.strftime("%d/%m/%Y")),
                               "seen": (date.strftime("%Y-%m-%d") if date else today.isoformat())}
                added += 1
        else:
            for title, link in page_links(url, raw.decode("utf-8", "ignore")):
                if link in items:
                    continue
                items[link] = {"src": name, "title": title, "url": link,
                               "date": today.strftime("%d/%m/%Y"), "seen": today.isoformat()}
                added += 1
        health.append(f"  ok {name}: +{added} new")

    ordered = sorted(items.values(), key=lambda x: x.get("seen", ""), reverse=True)[:MAX_ITEMS]
    data = {"asof": today.strftime("%d/%m/%Y"), "items": ordered}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    print("\n".join(health))
    print(f"-> {OUT} ({len(ordered)} letters, {len(ordered) - len(prev) if len(ordered) >= len(prev) else 0} new)")


if __name__ == "__main__":
    main()

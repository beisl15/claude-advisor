#!/usr/bin/env python3
"""
Gera data/transcripts.json: link do RELEASE OFICIAL de resultados direto da fonte.
- US: ultimo 8-K com item 2.02 (Results of Operations) na SEC EDGAR.
- BR: pagina de RI (release/webcast) e a busca CVM.
Transcricao falada completa nao existe de graca na fonte (fica em provedores pagos);
aqui entregamos o documento oficial + o RI, que e o mais perto da fonte.
"""
import json, os, sys, urllib.request

OUT = os.path.join(os.path.dirname(__file__), "..", "data", "transcripts.json")
SEC_UA = os.environ.get("SEC_UA", "claude-advisor-dashboard pedro.beisl@gmail.com")

CIK = {"MSFT": "0000789019", "GOGL": "0001652044", "META": "0001326801",
       "AMZN": "0001018724", "JPM": "0000019617", "BLK": "0002012383", "MU": "0000723125",
       "AAPL": "0000320193", "NVDA": "0001045810", "AMD": "0000002488", "INTC": "0000050863",
       "MRVL": "0001835632", "AVGO": "0001730168", "TSM": "0001046179"}
IR = {
    "MSFT": "https://www.microsoft.com/en-us/investor",
    "GOGL": "https://abc.xyz/investor/", "META": "https://investor.atmeta.com/",
    "AMZN": "https://ir.aboutamazon.com/", "JPM": "https://www.jpmorganchase.com/ir",
    "BLK": "https://ir.blackrock.com/", "MU": "https://investors.micron.com/",
    "SMFT3": "https://ri.smartfit.com.br/", "PRIO3": "https://ri.prio3.com.br/",
    "SBSP3": "https://ri.sabesp.com.br/",
}


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": SEC_UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def latest_earnings_8k(cik):
    """URL do indice do ultimo 8-K com item 2.02 (resultado)."""
    try:
        d = get(f"https://data.sec.gov/submissions/CIK{cik}.json")
    except Exception as e:
        print(f". {cik}: {e}", file=sys.stderr); return None, None
    rec = d.get("filings", {}).get("recent", {})
    forms = rec.get("form", []); accs = rec.get("accessionNumber", [])
    items = rec.get("items", []); dates = rec.get("filingDate", [])
    cikint = str(int(cik))
    for i, f in enumerate(forms):
        if f == "8-K" and "2.02" in (items[i] if i < len(items) else ""):
            acc = accs[i].replace("-", "")
            url = f"https://www.sec.gov/Archives/edgar/data/{cikint}/{acc}/"
            return url, dates[i]
    return None, None


def main():
    out = {}
    for tk in set(list(CIK) + list(IR)):
        entry = {}
        if tk in CIK:
            url, dt = latest_earnings_8k(CIK[tk])
            if url:
                entry["release_url"] = url
                entry["release_date"] = dt
        if tk in IR:
            entry["ir_url"] = IR[tk]
        if entry:
            out[tk] = entry
            print(f"ok {tk}: {entry.get('release_date','')} {entry.get('release_url') or entry.get('ir_url')}")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    print(f"-> {OUT} ({len(out)} tickers)")


if __name__ == "__main__":
    main()

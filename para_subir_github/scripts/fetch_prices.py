#!/usr/bin/env python3
"""
Gera data/prices.json: cotacao ao vivo (Yahoo Finance v8/chart) e P/E calculado
(= preco / LPA 12m). O LPA 12m vem do fin.json (SEC) para as americanas.
Roda no GitHub Actions (o Yahoo costuma responder de IP de servidor; daqui no
ambiente do Claude ele bloqueia, por isso roda so na nuvem).
"""
import json, os, sys, urllib.request

HERE = os.path.dirname(__file__)
DATA = os.path.join(HERE, "..", "data")
OUT = os.path.join(DATA, "prices.json")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"

# ticker do dashboard -> simbolo no Yahoo
SYMBOLS = {
    "MSFT": "MSFT", "GOGL": "GOOGL", "META": "META", "AMZN": "AMZN", "JPM": "JPM",
    "BLK": "BLK", "MU": "MU", "AAPL": "AAPL", "NVDA": "NVDA", "AMD": "AMD",
    "INTC": "INTC", "MRVL": "MRVL", "AVGO": "AVGO", "TSM": "TSM", "MELI": "MELI",
    "ASML": "ASML", "RACE": "RACE", "ABI": "BUD", "ROXO": "NU",
    "VZ": "VZ", "TMUS": "TMUS", "T": "T",
    "SMFT3": "SMFT3.SA", "PRIO3": "PRIO3.SA", "SBSP3": "SBSP3.SA",
    "PETR4": "PETR4.SA", "PETR3": "PETR3.SA", "VALE3": "VALE3.SA", "ITUB4": "ITUB4.SA",
    "BPAC11": "BPAC11.SA", "VIVT3": "VIVT3.SA", "TIMS3": "TIMS3.SA", "TOTS3": "TOTS3.SA",
    "ABEV3": "ABEV3.SA", "CSMG3": "CSMG3.SA",
}


def yquote(sym):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=1d"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.load(r)
    res = d.get("chart", {}).get("result")
    if not res:
        return None
    return res[0].get("meta", {}).get("regularMarketPrice")


def load(path):
    try:
        with open(os.path.join(DATA, path)) as f:
            return json.load(f)
    except Exception:
        return {}


def eps_ttm(fin_entry):
    eps = fin_entry.get("eps") if fin_entry else None
    if not eps or len(eps) < 4 or any(e is None for e in eps[-4:]):
        return None
    return sum(eps[-4:])


def main():
    fin = load("fin.json")
    out = {}
    for tk, sym in SYMBOLS.items():
        try:
            px = yquote(sym)
        except Exception as e:
            print(f". {tk}: {e}", file=sys.stderr)
            continue
        if px is None:
            continue
        rec = {"price": round(px, 2)}
        et = eps_ttm(fin.get(tk))
        if et and et > 0:
            rec["pe"] = round(px / et, 1)   # P/E ao vivo = preco / LPA 12m (SEC)
        out[tk] = rec
        print(f"ok {tk}: {sym} = {rec.get('price')} P/E={rec.get('pe')}")

    import datetime
    out["_asof"] = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    os.makedirs(DATA, exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    print(f"-> {OUT} ({len(out)-1} tickers)")


if __name__ == "__main__":
    main()

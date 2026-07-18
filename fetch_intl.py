#!/usr/bin/env python3
"""
Fundamentos TRIMESTRAIS das estrangeiras (foreign private issuers que so arquivam
20-F anual na SEC, sem 10-Q). Fonte: Yahoo Finance fundamentals-timeseries
(melhor fonte trimestral livre p/ esses nomes; IR/bolsa do pais como referencia).

Faz MERGE em data/fin.json (nao sobrescreve as US da SEC nem as BR).
Roda no GitHub Actions. Cobertura trimestral pode ser irregular -> best-effort,
continue-on-error: se um nome falhar, mantem o que ja havia.

Moeda: valor nativo do reporte (ASML/RACE em EUR; ABI/NU em USD; TSM em TWD).
Os graficos sao por-empresa, entao a consistencia interna e o que importa.
Referencia oficial por nome (verificacao manual):
  ASML  -> ir.asml.com (Euronext Amsterdam)
  TSM   -> investor.tsmc.com / TWSE MOPS (TWD)
  RACE  -> corporate.ferrari.com/en/investors (Borsa Italiana)
  ABI   -> ab-inbev.com/investors (Euronext Brussels)
  ROXO  -> investors.nu (Nu Holdings, NYSE; reporta trimestral em 6-K)
"""
import json, os, sys, time, datetime, urllib.request

HERE = os.path.dirname(__file__)
OUT = os.path.join(HERE, "..", "data", "fin.json")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
NQ = 17

# ticker no dashboard -> simbolo Yahoo
SYMBOLS = {"ASML": "ASML", "TSM": "TSM", "RACE": "RACE", "ABI": "BUD", "ROXO": "NU"}

# tipo Yahoo -> chave no nosso FIN (e se e fluxo de caixa = sai negativo, abs)
TYPES = {
    "quarterlyTotalRevenue": ("rev", False),
    "quarterlyGrossProfit": ("gp", False),
    "quarterlyOperatingIncome": ("ebitda", False),
    "quarterlyNetIncome": ("ni", False),
    "quarterlyDilutedEPS": ("eps", False),
    "quarterlyCapitalExpenditure": ("capex", True),
    "quarterlyCashDividendsPaid": ("div", True),
    "quarterlyRepurchaseOfCapitalStock": ("buyback", True),
}


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def qlabel(d):  # 'YYYY-MM-DD' -> "Q3'25"
    y, m = int(d[:4]), int(d[5:7])
    return f"Q{(m - 1) // 3 + 1}'{str(y)[2:]}"


def fetch_symbol(sym):
    p2 = int(time.time())
    p1 = p2 - 6 * 365 * 86400  # ~6 anos
    types = ",".join(TYPES.keys())
    url = (f"https://query2.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/{sym}"
           f"?symbol={sym}&type={types}&period1={p1}&period2={p2}&merge=false")
    d = get(url)
    time.sleep(0.3)
    res = (d.get("timeseries", {}) or {}).get("result", [])
    # por tipo: {asOfDate: valor}
    bydate = {key: {} for key, _ in TYPES.values()}
    for blk in res:
        t = (blk.get("meta", {}).get("type") or [None])[0]
        if t not in TYPES:
            continue
        key, is_flow = TYPES[t]
        for row in blk.get(t, []) or []:
            if not row:
                continue
            dt = row.get("asOfDate")
            rv = (row.get("reportedValue") or {}).get("raw")
            if dt is None or rv is None:
                continue
            bydate[key][dt] = abs(rv) if is_flow else rv
    # datas-base = uniao das datas de receita (fallback: lucro liquido)
    dates = sorted(bydate["rev"] or bydate["ni"])
    dates = dates[-NQ:]
    if not dates:
        return None

    def col(key, scale):
        return [round(bydate[key][dt] / scale, 3) if dt in bydate[key] else None for dt in dates]

    entry = dict(
        src="Yahoo Finance (intl)", asof=qlabel(dates[-1]),
        q=[qlabel(dt) for dt in dates],
        rev=col("rev", 1e9), gp=col("gp", 1e9), ebitda=col("ebitda", 1e9),
        ni=col("ni", 1e9), eps=col("eps", 1), capex=col("capex", 1e9),
        div=col("div", 1e9), buyback=col("buyback", 1e9),
        netdebt=[None] * len(dates),
    )
    # se receita veio toda vazia, descarta
    if not any(v is not None for v in entry["rev"]):
        return None
    return entry


def main():
    try:
        with open(OUT) as f:
            fin = json.load(f)
    except Exception:
        fin = {}
    n = 0
    for tk, sym in SYMBOLS.items():
        try:
            e = fetch_symbol(sym)
        except Exception as ex:
            print(f". {tk} ({sym}): {ex}", file=sys.stderr); continue
        if not e:
            print(f". {tk}: sem dados trimestrais no Yahoo", file=sys.stderr); continue
        fin[tk] = e
        n += 1
        print(f"ok {tk}: {e['q'][0]}..{e['q'][-1]} rev_last={e['rev'][-1]}")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(fin, f, indent=1, ensure_ascii=False)
    print(f"-> {OUT} ({n} estrangeiras atualizadas; {len(fin)} tickers no total)")


if __name__ == "__main__":
    main()

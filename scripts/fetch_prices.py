#!/usr/bin/env python3
"""
Gera data/prices.json: cotacao ao vivo (Yahoo Finance v8/chart) e P/E calculado
(= preco / LPA 12m). O LPA 12m vem do fin.json (SEC) para as americanas.
Roda no GitHub Actions (o Yahoo costuma responder de IP de servidor; daqui no
ambiente do Claude ele bloqueia, por isso roda so na nuvem).
"""
import datetime, json, os, sys, urllib.request

HERE = os.path.dirname(__file__)
DATA = os.path.join(HERE, "..", "data")
OUT = os.path.join(DATA, "prices.json")
OUT_HIST = os.path.join(DATA, "px_hist.json")

# Quantos pontos manter por ticker (~5 anos de pregao) e a partir de quantos
# pontos o ticker deixa de precisar de backfill.
MAX_PTS = 1400
MIN_PTS = 200
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"

# ticker do dashboard -> simbolo no Yahoo
SYMBOLS = {
    "MSFT": "MSFT", "GOGL": "GOOGL", "META": "META", "AMZN": "AMZN", "JPM": "JPM",
    "BLK": "BLK", "MU": "MU", "AAPL": "AAPL", "NVDA": "NVDA", "AMD": "AMD",
    "INTC": "INTC", "MRVL": "MRVL", "AVGO": "AVGO", "TSM": "TSM", "MELI": "MELI",
    "ASML": "ASML", "RACE": "RACE", "ABI": "BUD", "ROXO": "NU",
    "VZ": "VZ", "TMUS": "TMUS", "T": "T",
    # Software + energia/datacenter (jul/2026)
    "ORCL": "ORCL", "NOW": "NOW", "PLTR": "PLTR",
    "CEG": "CEG", "VST": "VST", "GEV": "GEV",
    "RHM": "RHM.DE",  # Rheinmetall — Xetra, EUR. Adicionado out/2026.
    # Os 10 sufixos .SA (B3) sairam em 17/08/2026 — cobertura 100% internacional.
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


def yhist(sym, rng="5y"):
    """Serie diaria de fechamento, para semear o historico na primeira execucao.

    Usa `quote[0].close`, que ja vem ajustado por desdobramento, e NAO o
    `adjclose`, que tambem desconta dividendo: para posicionar preco dentro da
    propria faixa, o ajuste de provento distorce o nivel sem acrescentar nada.
    """
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
           f"?interval=1d&range={rng}")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.load(r)
    res = (d.get("chart") or {}).get("result")
    if not res:
        return []
    res = res[0]
    ts = res.get("timestamp") or []
    quote = ((res.get("indicators") or {}).get("quote") or [{}])[0]
    closes = quote.get("close") or []
    out = []
    for t, c in zip(ts, closes):
        if c is None:
            continue
        dia = datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y-%m-%d")
        out.append((dia, round(float(c), 4)))
    return out


def merge_hist(entrada, pontos):
    """Junta pontos novos na serie, sem duplicar dia e sem perder ordem.

    Idempotente de proposito: rodar duas vezes no mesmo dia nao cria dois
    pontos, so atualiza o fechamento daquele dia.
    """
    m = dict(zip(entrada.get("d", []), entrada.get("p", [])))
    for dia, px in pontos:
        m[dia] = px
    dias = sorted(m)[-MAX_PTS:]
    return {"d": dias, "p": [m[x] for x in dias]}


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
    hist = load("px_hist.json") or {}
    hoje = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    out, novos = {}, 0
    for tk, sym in SYMBOLS.items():
        try:
            px = yquote(sym)
        except Exception as e:
            print(f". {tk}: {e}", file=sys.stderr)
            continue
        if px is None:
            continue

        # Historico: semeia 5 anos na primeira vez, depois so acrescenta o dia.
        # O backfill custa 1 request extra por ticker e acontece uma vez so --
        # sem ele, a faixa de 5 anos levaria 5 anos para existir.
        ent = hist.get(tk) or {}
        try:
            if len(ent.get("d", [])) < MIN_PTS:
                pts = yhist(sym)
                if pts:
                    ent = merge_hist(ent, pts)
                    novos += 1
                    print(f"   {tk}: backfill de {len(pts)} pregoes")
            hist[tk] = merge_hist(ent, [(hoje, round(px, 4))])
        except Exception as e:
            print(f". {tk} historico: {e}", file=sys.stderr)
            hist[tk] = merge_hist(ent, [(hoje, round(px, 4))])

        rec = {"price": round(px, 2)}
        et = eps_ttm(fin.get(tk))
        if et and et > 0:
            rec["pe"] = round(px / et, 1)   # P/E ao vivo = preco / LPA 12m (SEC)
        out[tk] = rec
        print(f"ok {tk}: {sym} = {rec.get('price')} P/E={rec.get('pe')}")

    agora = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    out["_asof"] = agora
    os.makedirs(DATA, exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    print(f"-> {OUT} ({len(out)-1} tickers)")

    hist["_asof"] = agora
    with open(OUT_HIST, "w") as f:
        json.dump(hist, f, separators=(",", ":"), ensure_ascii=False, sort_keys=True)
    pts = sum(len(v.get("d", [])) for k, v in hist.items() if k != "_asof")
    print(f"-> {OUT_HIST} ({len(hist)-1} tickers, {pts} pontos, {novos} backfills)")
    print(f"HEALTH_N={len(out)-1}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Valida CIKs e disponibilidade de tags XBRL na SEC ANTES de ingerir dados.

Por que existe: CIK errado nao gera erro. O companyconcept responde 200 com o
balanco de OUTRA empresa e o dado entra silenciosamente no dashboard. Este
script confronta cada CIK do nosso mapa contra o proprio indice da SEC
(company_tickers.json) e so depois testa as tags.

Roda no GitHub Actions via .github/workflows/test.yml (workflow_dispatch).
A sandbox local bloqueia data.sec.gov -> aqui nao roda.

Saida: _validation_ciks.json na raiz do repo + relatorio no stdout.
Codigo de saida 1 se qualquer CIK divergir (falha visivel na aba Actions).
"""
import json, os, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "_validation_ciks.json")

# SEC exige User-Agent identificavel com contato. Sem isso: HTTP 403.
# https://www.sec.gov/os/webmaster-faq#developers
SEC_UA = os.environ.get("SEC_UA", "ClaudeAdvisor/1.0 pedro.beisl@gmail.com")
SLEEP = 0.2   # <= 10 req/s e o teto da SEC; 0.2s da margem contra 429.

# ─── O que validar ───────────────────────────────────────────────────────────
# ticker do dashboard -> (simbolo na SEC, CIK que pretendemos usar)
# Os 6 NOVOS primeiro: sao eles que motivam esta rodada.
NOVOS = {
    "ORCL": ("ORCL", "0001341439"),   # Oracle          — FY fecha em MAIO
    "NOW":  ("NOW",  "0001373715"),   # ServiceNow
    "PLTR": ("PLTR", "0001321655"),   # Palantir
    "CEG":  ("CEG",  "0001868275"),   # Constellation Energy
    "VST":  ("VST",  "0001692819"),   # Vistra
    "GEV":  ("GEV",  "0001996810"),   # GE Vernova
}
# Universo ja em producao — validado junto de graca, pega drift de CIK
# (ex.: BlackRock trocou de CIK em 2024).
ATUAIS = {
    "MSFT": ("MSFT", "0000789019"), "GOGL": ("GOOGL", "0001652044"),
    "META": ("META", "0001326801"), "AMZN": ("AMZN", "0001018724"),
    "JPM":  ("JPM",  "0000019617"), "BLK":  ("BLK",  "0002012383"),
    "MU":   ("MU",   "0000723125"), "MELI": ("MELI", "0001099590"),
    "NVDA": ("NVDA", "0001045810"), "AAPL": ("AAPL", "0000320193"),
    "AMD":  ("AMD",  "0000002488"), "INTC": ("INTC", "0000050863"),
    "MRVL": ("MRVL", "0001835632"), "AVGO": ("AVGO", "0001730168"),
    "VZ":   ("VZ",   "0000732712"), "TMUS": ("TMUS", "0001283699"),
    "T":    ("T",    "0000732717"), "TSM":  ("TSM",  "0001046179"),
}

# Tags candidatas a testar por ticker novo. A ordem e a ordem de preferencia
# que ira para o CFG do fetch_us.py.
TAGS_TESTE = {
    "rev": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues",
            "RegulatedAndUnregulatedOperatingRevenue", "ElectricUtilityRevenue"],
    "gp": ["GrossProfit"],
    # fallback de margem bruta para geradoras (CEG/VST/GEV raramente publicam GrossProfit)
    "cogs": ["CostOfGoodsAndServicesSold", "CostOfRevenue", "CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization"],
    "ebit": ["OperatingIncomeLoss"],
    "ni": ["NetIncomeLoss"],
    "eps": ["EarningsPerShareDiluted"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
    "div": ["PaymentsOfDividendsCommonStock", "PaymentsOfDividends"],
    "buyback": ["PaymentsForRepurchaseOfCommonStock"],
}


def get(url, accept="application/json"):
    req = urllib.request.Request(url, headers={"User-Agent": SEC_UA, "Accept": accept})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def indice_sec():
    """{TICKER: (cik10, nome)} a partir do indice oficial da SEC."""
    d = get("https://www.sec.gov/files/company_tickers.json")
    time.sleep(SLEEP)
    return {v["ticker"].upper(): (str(v["cik_str"]).zfill(10), v["title"])
            for v in d.values()}


def concept(cik, tag):
    """Retorna (n_fatos, ultima_data_fim) ou None se a tag nao existir."""
    url = f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/{tag}.json"
    try:
        d = get(url)
    except Exception:
        return None
    finally:
        time.sleep(SLEEP)
    units = d.get("units", {})
    key = "USD/shares" if "USD/shares" in units else "USD"
    fatos = units.get(key)
    if not fatos:
        return None
    ends = sorted(f["end"] for f in fatos if "end" in f)
    return (len(fatos), ends[-1] if ends else None)


def fiscal(cik):
    """Fim do ano fiscal (MMDD) e ultimo 10-Q, do submissions."""
    try:
        d = get(f"https://data.sec.gov/submissions/CIK{cik}.json")
    except Exception as e:
        return {"erro": str(e)}
    finally:
        time.sleep(SLEEP)
    rec = d.get("filings", {}).get("recent", {})
    forms, dates, per = (rec.get(k, []) for k in ("form", "filingDate", "reportDate"))
    ult = next(({"form": forms[i], "filingDate": dates[i], "reportDate": per[i]}
                for i in range(len(forms)) if forms[i] in ("10-Q", "10-K")), None)
    return {"nome": d.get("name"), "fiscalYearEnd": d.get("fiscalYearEnd"),
            "sic": d.get("sicDescription"), "ultimo_report": ult}


def main():
    print(f"User-Agent: {SEC_UA}\n")
    idx = indice_sec()
    print(f"indice da SEC carregado: {len(idx)} tickers\n")

    rel = {"ok": True, "novos": {}, "atuais": {}}

    # ── 1. Conferencia de CIK (todos) ────────────────────────────────────────
    for grupo, mapa in (("novos", NOVOS), ("atuais", ATUAIS)):
        print(f"── CIK · {grupo} " + "─" * 40)
        for tk, (sym, cik_nosso) in mapa.items():
            real = idx.get(sym.upper())
            if not real:
                st, msg = "NAO_ENCONTRADO", f"simbolo {sym} ausente no indice da SEC"
                rel["ok"] = False
            elif real[0] != cik_nosso:
                st, msg = "DIVERGENTE", f"nosso {cik_nosso} != SEC {real[0]} ({real[1]})"
                rel["ok"] = False
            else:
                st, msg = "OK", real[1]
            rel[grupo][tk] = {"symbol": sym, "cik_usado": cik_nosso,
                              "cik_sec": real[0] if real else None,
                              "nome_sec": real[1] if real else None, "status": st}
            print(f"  {'x' if st != 'OK' else 'v'} {tk:<6} {cik_nosso}  {st:<15} {msg}")
        print()

    # ── 2. Tags XBRL + ano fiscal (so os novos) ──────────────────────────────
    print("── Tags XBRL e ano fiscal · novos " + "─" * 25)
    for tk, (sym, cik) in NOVOS.items():
        cik = rel["novos"][tk]["cik_sec"] or cik   # usa o da SEC se divergiu
        info = fiscal(cik)
        rel["novos"][tk]["perfil"] = info
        fye = info.get("fiscalYearEnd")
        print(f"\n  {tk} · {info.get('nome')} · FY termina {fye} · SIC: {info.get('sic')}")
        if fye and fye not in ("1231",):
            print(f"     ATENCAO: ano fiscal NAO-CALENDARIO ({fye}) — conferir labels de trimestre")
        achadas = {}
        for campo, tags in TAGS_TESTE.items():
            for tag in tags:
                r = concept(cik, tag)
                if r:
                    achadas.setdefault(campo, []).append({"tag": tag, "fatos": r[0], "ate": r[1]})
        rel["novos"][tk]["tags"] = achadas
        for campo in TAGS_TESTE:
            hits = achadas.get(campo, [])
            if hits:
                print(f"     {campo:<8} {hits[0]['tag']} ({hits[0]['fatos']} fatos, ate {hits[0]['ate']})"
                      + (f"  [+{len(hits)-1} alt]" if len(hits) > 1 else ""))
            else:
                print(f"     {campo:<8} AUSENTE")
        # regra explicita do plano: fallback de margem bruta
        if not achadas.get("gp"):
            alt = achadas.get("cogs")
            print(f"     -> sem GrossProfit. Fallback: "
                  + (f"Revenues - {alt[0]['tag']}" if alt else "usar OperatingIncomeLoss (EBIT), gp=[]"))
            rel["novos"][tk]["fallback_gp"] = alt[0]["tag"] if alt else None

    with open(OUT, "w") as f:
        json.dump(rel, f, indent=1, ensure_ascii=False)
    print(f"\n-> {os.path.abspath(OUT)}")
    print("RESULTADO:", "TODOS OS CIKs CONFEREM" if rel["ok"] else "HA DIVERGENCIA — NAO INGERIR")
    return 0 if rel["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

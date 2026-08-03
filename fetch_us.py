#!/usr/bin/env python3
"""
Gera data/fin.json com fundamentos trimestrais (12 trimestres) das US holdings,
direto da SEC EDGAR (companyconcept XBRL). Sem chave de API.
Roda no GitHub Actions. Requer: requests.

SEC exige um User-Agent identificavel. Ajuste SEC_UA com seu email.
"""
import json, time, datetime, os, sys, urllib.request
from collections import defaultdict

SEC_UA = os.environ.get("SEC_UA", "claude-advisor-dashboard pedro.beisl@gmail.com")
OUT = os.path.join(os.path.dirname(__file__), "..", "data", "fin.json")

# ticker -> config. cik pode ser lista (ex.: BlackRock trocou de CIK em 2024).
# tags: ordem de tentativa (usa a 1a que tiver dados ate o trimestre mais recente).
COMMON = dict(
    ni=["NetIncomeLoss"],
    eps=["EarningsPerShareDiluted"],
    capex=["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
    buyback=["PaymentsForRepurchaseOfCommonStock"],
)
CFG = {
    "MSFT": dict(cik=["0000789019"], rev=["RevenueFromContractWithCustomerExcludingAssessedTax"],
                 gp=["GrossProfit"], ebitda=["OperatingIncomeLoss"], div=["PaymentsOfDividendsCommonStock"], **COMMON),
    "GOGL": dict(cik=["0001652044"], rev=["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"],
                 gp=["GrossProfit"], ebitda=["OperatingIncomeLoss"], div=["PaymentsOfDividends"], **COMMON),
    "META": dict(cik=["0001326801"], rev=["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"],
                 gp=["GrossProfit"], ebitda=["OperatingIncomeLoss"], div=["PaymentsOfDividends"], **COMMON),
    "AMZN": dict(cik=["0001018724"], rev=["RevenueFromContractWithCustomerExcludingAssessedTax"],
                 gp=["GrossProfit"], ebitda=["OperatingIncomeLoss"], div=["PaymentsOfDividends"], **COMMON),
    "JPM":  dict(cik=["0000019617"], rev=["RevenuesNetOfInterestExpense", "Revenues"],
                 gp=[], ebitda=[], div=["PaymentsOfDividends", "PaymentsOfDividendsCommonStock"],
                 equity=["StockholdersEquity"], **{k: COMMON[k] for k in ("ni", "eps", "buyback")}),
    "BLK":  dict(cik=["0002012383", "0001364742"], rev=["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"],
                 gp=[], ebitda=["OperatingIncomeLoss"], div=["PaymentsOfDividends"],
                 equity=["StockholdersEquity"], **{k: COMMON[k] for k in ("ni", "eps", "buyback")}),
    "MU":   dict(cik=["0000723125"], rev=["RevenueFromContractWithCustomerExcludingAssessedTax"],
                 gp=["GrossProfit"], ebitda=["OperatingIncomeLoss"], div=["PaymentsOfDividendsCommonStock", "PaymentsOfDividends"], **COMMON),
    # MercadoLibre: incorporada em Delaware (EUA) -> arquiva 10-Q na SEC, apesar da operacao LatAm.
    "MELI": dict(cik=["0001099590"], rev=["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"],
                 gp=["GrossProfit"], ebitda=["OperatingIncomeLoss"], div=[], **COMMON),
    # Semis / big-tech adicionais (todas 10-Q domesticas):
    "NVDA": dict(cik=["0001045810"], rev=["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"],
                 gp=["GrossProfit"], ebitda=["OperatingIncomeLoss"], div=["PaymentsOfDividendsCommonStock", "PaymentsOfDividends"], **COMMON),
    "AAPL": dict(cik=["0000320193"], rev=["RevenueFromContractWithCustomerExcludingAssessedTax"],
                 gp=["GrossProfit"], ebitda=["OperatingIncomeLoss"], div=["PaymentsOfDividendsCommonStock", "PaymentsOfDividends"], **COMMON),
    "AMD":  dict(cik=["0000002488"], rev=["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"],
                 gp=["GrossProfit"], ebitda=["OperatingIncomeLoss"], div=[], **COMMON),
    "INTC": dict(cik=["0000050863"], rev=["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"],
                 gp=["GrossProfit"], ebitda=["OperatingIncomeLoss"], div=["PaymentsOfDividendsCommonStock", "PaymentsOfDividends"], **COMMON),
    "MRVL": dict(cik=["0001835632"], rev=["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"],
                 gp=["GrossProfit"], ebitda=["OperatingIncomeLoss"], div=["PaymentsOfDividendsCommonStock"], **COMMON),
    "AVGO": dict(cik=["0001730168"], rev=["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"],
                 gp=["GrossProfit"], ebitda=["OperatingIncomeLoss"], div=["PaymentsOfDividendsCommonStock", "PaymentsOfDividends"], **COMMON),
    # Telecom US (10-Q domesticas). Telecom normalmente nao reporta GrossProfit -> gp=[].
    "VZ":   dict(cik=["0000732712"], rev=["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"],
                 gp=[], ebitda=["OperatingIncomeLoss"], div=["PaymentsOfDividendsCommonStock", "PaymentsOfDividends"], **COMMON),
    "TMUS": dict(cik=["0001283699"], rev=["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"],
                 gp=[], ebitda=["OperatingIncomeLoss"], div=["PaymentsOfDividendsCommonStock", "PaymentsOfDividends"], **COMMON),
    "T":    dict(cik=["0000732717"], rev=["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"],
                 gp=[], ebitda=["OperatingIncomeLoss"], div=["PaymentsOfDividendsCommonStock", "PaymentsOfDividends"], **COMMON),
    # ── Software (jul/2026). Padrao de software: GrossProfit publicado normalmente.
    # ORCL: ano fiscal fecha em MAIO -> fy_end=5 (ver qlabel/nota de fiscal abaixo).
    "ORCL": dict(cik=["0001341439"], fy_end=5,
                 rev=["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"],
                 gp=["GrossProfit"], ebitda=["OperatingIncomeLoss"],
                 div=["PaymentsOfDividendsCommonStock", "PaymentsOfDividends"], **COMMON),
    "NOW":  dict(cik=["0001373715"],
                 rev=["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"],
                 gp=["GrossProfit"], ebitda=["OperatingIncomeLoss"], div=[], **COMMON),
    "PLTR": dict(cik=["0001321655"],
                 rev=["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"],
                 gp=["GrossProfit"], ebitda=["OperatingIncomeLoss"], div=[], **COMMON),
    # ── Energia / datacenter (jul/2026). Geradoras raramente publicam GrossProfit:
    # cogs= habilita o fallback  GrossProfit = Revenues - CostOfGoodsAndServicesSold.
    # Se nem isso existir, gp fica vazio e o EBIT (OperatingIncomeLoss) e a referencia.
    "CEG":  dict(cik=["0001868275"],
                 rev=["Revenues", "RegulatedAndUnregulatedOperatingRevenue",
                      "RevenueFromContractWithCustomerExcludingAssessedTax"],
                 gp=["GrossProfit"],
                 cogs=["CostOfGoodsAndServicesSold", "CostOfRevenue",
                       "CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization"],
                 ebitda=["OperatingIncomeLoss"],
                 div=["PaymentsOfDividendsCommonStock", "PaymentsOfDividends"], **COMMON),
    "VST":  dict(cik=["0001692819"],
                 rev=["Revenues", "RegulatedAndUnregulatedOperatingRevenue",
                      "RevenueFromContractWithCustomerExcludingAssessedTax"],
                 gp=["GrossProfit"],
                 cogs=["CostOfGoodsAndServicesSold", "CostOfRevenue",
                       "CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization"],
                 ebitda=["OperatingIncomeLoss"],
                 div=["PaymentsOfDividendsCommonStock", "PaymentsOfDividends"], **COMMON),
    "GEV":  dict(cik=["0001996810"],
                 rev=["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"],
                 gp=["GrossProfit"],
                 cogs=["CostOfGoodsAndServicesSold", "CostOfRevenue"],
                 ebitda=["OperatingIncomeLoss"],
                 div=["PaymentsOfDividendsCommonStock", "PaymentsOfDividends"], **COMMON),
    # Estrangeiras (ASML/TSM/RACE/ABI/NU): foreign private issuers (so 20-F anual na SEC)
    # -> cobertas em fetch_intl.py (Yahoo fundamentals timeseries; IR do pais como referencia).
}
NQ = 17  # trimestres (~4 anos: cobre 2022 -> trimestre corrente)


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": SEC_UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def concept(cik, tag):
    url = f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/{tag}.json"
    try:
        d = get(url)
    except Exception:
        return None
    time.sleep(0.25)  # respeita rate-limit da SEC
    unit = "USD/shares" if "USD/shares" in d.get("units", {}) else "USD"
    if unit not in d.get("units", {}):
        return None
    return d["units"][unit], (unit == "USD/shares")


def qlabel(end):
    y, m, _ = map(int, end.split("-")[:3])
    return f"CY{y}Q{(m - 1) // 3 + 1}", f"Q{(m - 1) // 3 + 1}'{str(y)[2:]}"


def fqlabel(end, fy_end):
    """Rotulo do trimestre FISCAL para empresas com exercicio nao-calendario.

    fy_end = mes em que o ano fiscal fecha (ORCL = 5, ou seja, maio).
    Ex.: trimestre terminado em 2026-08-31 da Oracle -> Q1 FY27 (nao 'Q3 2026').
    O rotulo civil continua em `q` para os graficos nao mudarem de eixo; este vai
    em `qf` e evita a leitura errada de sobreposicao com o calendario civil.
    """
    y, m, _ = map(int, end.split("-")[:3])
    fq = ((m - fy_end - 1) % 12) // 3 + 1          # 1..4 dentro do ano fiscal
    fy = y + 1 if m > fy_end else y                # exercicio a que o trimestre pertence
    return f"Q{fq} FY{str(fy)[2:]}"


def quarterly(units):
    """Agrupa por inicio de exercicio e tira diferencas consecutivas -> valor de 3 meses.
    Funciona para fiscal nao-calendario. Retorna {end_date: valor}."""
    byval = {}
    for e in units:
        if "start" not in e or "end" not in e:
            continue
        byval[(e["start"], e["end"])] = e["val"]
    g = defaultdict(list)
    for (s, en), v in byval.items():
        g[s].append((en, v))
    out = {}
    for s, lst in g.items():
        lst.sort()
        prev = 0
        for i, (en, v) in enumerate(lst):
            out[en] = v if i == 0 else v - prev
            prev = v
    return out


def series(cik_list, tags, per_share=False):
    """Tenta cada tag/CIK, mescla por data-fim. Retorna {end_date: valor}."""
    merged = {}
    for tag in tags:
        for cik in cik_list:
            res = concept(cik, tag)
            if not res:
                continue
            units, is_ps = res
            q = quarterly(units)
            for en, v in q.items():
                merged.setdefault(en, v)
    return merged


def main():
    out = {}
    for tk, c in CFG.items():
        rev = series(c["cik"], c.get("rev", []))
        if not rev:
            print(f"!! {tk}: sem receita", file=sys.stderr)
            continue
        ends = sorted(rev.keys())[-NQ:]
        labels = [qlabel(e)[1] for e in ends]

        def col(tags, scale=1e9):
            s = series(c["cik"], tags) if tags else {}
            return [round(s[e] / scale, 3) if e in s and s[e] is not None else None for e in ends]

        def col_ps(tags):  # eps: usa valor 3-meses do diff (aprox p/ fiscal Q4)
            s = series(c["cik"], tags) if tags else {}
            return [round(s[e], 2) if e in s and s[e] is not None else None for e in ends]

        def col_inst(tags):  # patrimonio: valor instantaneo no fim do trimestre
            for tag in tags:
                for cik in c["cik"]:
                    res = concept(cik, tag)
                    if not res:
                        continue
                    units, _ = res
                    m = {}
                    for e in units:
                        if "end" in e and "start" not in e:
                            m[e["end"]] = e["val"]
                    if m:
                        return [round(m[e] / 1e9, 3) if e in m else None for e in ends]
            return [None] * len(ends)

        entry = dict(
            src="SEC EDGAR", asof=qlabel(ends[-1])[1],
            q=labels,
            rev=col(c.get("rev", [])),
            gp=col(c.get("gp", [])),
            ebitda=col(c.get("ebitda", [])),
            ni=col(c.get("ni", [])),
            eps=col_ps(c.get("eps", [])),
            capex=col(c.get("capex", [])),
            div=col(c.get("div", [])),
            buyback=col(c.get("buyback", [])),
            netdebt=[None] * len(ends),
        )

        # ── Ano fiscal nao-calendario (ORCL fecha em maio) ────────────────────
        # Mantem o rotulo civil em `q` (eixo dos graficos) e acrescenta o rotulo
        # fiscal em `qf`, para o trimestre nao ser lido como se fosse o civil.
        if c.get("fy_end"):
            entry["fy_end"] = c["fy_end"]
            entry["qf"] = [fqlabel(e, c["fy_end"]) for e in ends]
            entry["asof"] = entry["qf"][-1]
            if len(set(labels)) != len(labels):
                print(f"!! {tk}: rotulos civis repetidos ({labels}) — usar qf",
                      file=sys.stderr)

        # ── Fallback de margem bruta (geradoras: CEG, VST, GEV) ───────────────
        # Utilities raramente publicam a tag GrossProfit. Sem isso a linha de
        # margem bruta viria vazia e pareceria bug. Ordem: GrossProfit ->
        # Revenues - CostOfGoodsAndServicesSold -> nada (EBIT vira a referencia).
        if c.get("cogs") and all(v is None for v in entry["gp"]):
            cogs = col(c["cogs"])
            derivado = [round(r - k, 3) if (r is not None and k is not None) else None
                        for r, k in zip(entry["rev"], cogs)]
            if any(v is not None for v in derivado):
                entry["gp"] = derivado
                entry["gp_src"] = "derivado: Revenues - CostOfGoodsAndServicesSold"
                print(f"   {tk}: sem GrossProfit na SEC -> margem bruta derivada de COGS")
            else:
                entry["gp_src"] = "indisponivel (usar EBIT/OperatingIncomeLoss)"
                print(f"   {tk}: sem GrossProfit e sem COGS -> gp vazio, EBIT e a referencia")

        if c.get("equity"):
            entry["equity"] = col_inst(c["equity"])
        out[tk] = entry
        print(f"ok {tk}: {entry.get('qf', labels)[0]}..{entry.get('qf', labels)[-1]} "
              f"rev_last={entry['rev'][-1]}")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    print(f"-> {OUT} ({len(out)} tickers)")


if __name__ == "__main__":
    main()

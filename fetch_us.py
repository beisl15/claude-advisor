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
# Custo dos produtos/servicos. Usado so quando a empresa nao publica GrossProfit:
# o parser deriva gp = receita - custo (ver main()). Alphabet, Meta, Amazon e
# Oracle caem nesse caso -- todas reportam o custo, nenhuma reporta a linha de
# margem bruta em XBRL.
COGS_TAGS = ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfSales"]

# ── Divida liquida (netdebt) ─────────────────────────────────────────────────
# Grupos em ordem de preferencia; a resolucao e POR DATA (ver netdebt_series).
#
# Duas armadilhas descobertas conferindo as tags reais na SEC em 11/08/2026:
#
# 1. Nao existe uma tag unica de "divida total". `LongTermDebt` parece ser, mas
#    na Alphabet vale 49,1 bi enquanto a divida de balanco e 100,2 bi -- ali e
#    divulgacao a valor justo, nao a linha do balanco. Por isso ela entra so como
#    ultimo fallback de nao-circulante, nunca como total.
#
# 2. Escolher a tag uma vez por empresa e usa-la para todos os trimestres nao
#    funciona: a Microsoft tem `LongTermDebt` parado em 2016 e
#    `LongTermDebtNoncurrent` atualizado. Resolver por data evita tanto a serie
#    velha quanto o zero silencioso (a AT&T aparecia com divida zero somando
#    tags que nao existiam naquela data -- a divida real e 144 bi).
DEBT_TOTAL = ["DebtLongtermAndShorttermCombinedAmount"]
DEBT_NONCURRENT = ["LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations",
                   "LongTermNotesPayable", "LongTermDebt"]
DEBT_CURRENT = ["LongTermDebtCurrent", "DebtCurrent", "ShortTermBorrowings", "CommercialPaper"]
CASH_TAGS = ["CashAndCashEquivalentsAtCarryingValue"]
INVEST_TAGS = ["ShortTermInvestments", "MarketableSecuritiesCurrent", "OtherShortTermInvestments"]
CFG = {
    "MSFT": dict(cik=["0000789019"], rev=["RevenueFromContractWithCustomerExcludingAssessedTax"],
                 gp=["GrossProfit"], ebitda=["OperatingIncomeLoss"], div=["PaymentsOfDividendsCommonStock"], **COMMON),
    "GOGL": dict(cik=["0001652044"], rev=["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"],
                 gp=["GrossProfit"], cogs=COGS_TAGS, ebitda=["OperatingIncomeLoss"],
                 div=["PaymentsOfDividends"], **COMMON),
    "META": dict(cik=["0001326801"], rev=["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"],
                 gp=["GrossProfit"], cogs=COGS_TAGS, ebitda=["OperatingIncomeLoss"],
                 div=["PaymentsOfDividends"], **COMMON),
    "AMZN": dict(cik=["0001018724"], rev=["RevenueFromContractWithCustomerExcludingAssessedTax"],
                 gp=["GrossProfit"], cogs=COGS_TAGS, ebitda=["OperatingIncomeLoss"],
                 div=["PaymentsOfDividends"], **COMMON),
    "JPM":  dict(bank=True, cik=["0000019617"], rev=["RevenuesNetOfInterestExpense", "Revenues"],
                 gp=[], ebitda=[], div=["PaymentsOfDividends", "PaymentsOfDividendsCommonStock"],
                 equity=["StockholdersEquity"], **{k: COMMON[k] for k in ("ni", "eps", "buyback")}),
    "BLK":  dict(bank=True, cik=["0002012383", "0001364742"], rev=["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"],
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
                 gp=["GrossProfit"], cogs=COGS_TAGS, ebitda=["OperatingIncomeLoss"],
                 div=["PaymentsOfDividendsCommonStock", "PaymentsOfDividends"], **COMMON),
    "NOW":  dict(cik=["0001373715"],
                 rev=["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"],
                 gp=["GrossProfit"], ebitda=["OperatingIncomeLoss"], div=[], **COMMON),
    "PLTR": dict(cik=["0001321655"],
                 rev=["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"],
                 gp=["GrossProfit"], ebitda=["OperatingIncomeLoss"], div=[], **COMMON),
    # ── Energia / datacenter (jul/2026). Tags CONFIRMADAS pelo validate_ciks.py
    # na execucao de 03/08/2026 (Actions -> test.yml). Nao alterar sem revalidar.
    #
    # CEG e VST: nao publicam GrossProfit NEM CostOfGoodsAndServicesSold -> gp=[]
    # de proposito, EBIT (OperatingIncomeLoss) e a linha de referencia. Sem `cogs`
    # aqui porque o fallback nao tem de onde partir e so gastaria chamadas na SEC.
    # rev fixada numa unica tag: as duas empresas tambem expoem uma alternativa, e
    # como o parser mescla tags por data, deixar duas misturaria definicoes
    # diferentes de receita na mesma serie. Uma tag so falha visivelmente; duas
    # falham em silencio.
    "CEG":  dict(cik=["0001868275"],
                 rev=["RevenueFromContractWithCustomerExcludingAssessedTax"],
                 gp=[], ebitda=["OperatingIncomeLoss"],
                 div=["PaymentsOfDividendsCommonStock", "PaymentsOfDividends"], **COMMON),
    "VST":  dict(cik=["0001692819"],
                 rev=["RevenueFromContractWithCustomerExcludingAssessedTax"],
                 gp=[], ebitda=["OperatingIncomeLoss"],
                 div=["PaymentsOfDividendsCommonStock", "PaymentsOfDividends"], **COMMON),
    # GEV publica GrossProfit e COGS -> entra completa; cogs= fica como rede de
    # seguranca caso a empresa pare de reportar a linha de margem bruta.
    "GEV":  dict(cik=["0001996810"],
                 rev=["RevenueFromContractWithCustomerExcludingAssessedTax"],
                 gp=["GrossProfit"],
                 cogs=["CostOfGoodsAndServicesSold", "CostOfRevenue"],
                 ebitda=["OperatingIncomeLoss"],
                 div=["PaymentsOfDividends", "PaymentsOfDividendsCommonStock"],
                 capex=["PaymentsToAcquireProductiveAssets",
                        "PaymentsToAcquirePropertyPlantAndEquipment"],
                 **{k: COMMON[k] for k in ("ni", "eps", "buyback")}),
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


Q_MIN_DAYS, Q_MAX_DAYS = 80, 100  # janela aceita como "um trimestre"


def _days(a, b):
    da = datetime.date(*map(int, a.split("-")[:3]))
    db = datetime.date(*map(int, b.split("-")[:3]))
    return (db - da).days


def quarterly(units):
    """Agrupa por inicio de exercicio e tira diferencas consecutivas -> valor de 3 meses.

    Funciona para fiscal nao-calendario. Retorna {end_date: valor}.

    IMPORTANTE: so emite o valor se o periodo implicado tiver ~90 dias
    (Q_MIN_DAYS..Q_MAX_DAYS). Sem esse filtro, um grupo cujo unico registro e o
    exercicio inteiro (start=jan-01, end=dez-31) entrava como se fosse o 4o
    trimestre -- foi o que colocou receita anual no lugar do trimestre em GOGL
    (307,4 no Q4'23), BLK (17,9 no Q4'22), GEV (29,7 no Q4'22) e deixou o lucro
    da AVGO quase todo nulo. Melhor um buraco honesto do que um pico falso.
    """
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
        prev_end, prev_val = s, 0.0
        for i, (en, v) in enumerate(lst):
            if i == 0:
                dur, val = _days(s, en), v
            else:
                dur, val = _days(prev_end, en), v - prev_val
            if Q_MIN_DAYS <= dur <= Q_MAX_DAYS:
                out.setdefault(en, val)
            prev_end, prev_val = en, v
    return out


def dedupe_by_quarter(ends):
    """Um end-date por trimestre civil, mantendo o mais recente.

    Empresas de calendario fiscal deslocado publicam periodos que caem no mesmo
    trimestre civil (ex.: Apple com fim em 2023-07-01 e em 2023-09-30, ambos
    'Q3'23'). Sem isso o eixo do grafico repetia rotulo e pulava trimestre --
    era o caso de AAPL, AMD e INTC.
    """
    bykey = {}
    for e in sorted(ends):
        bykey[qlabel(e)[0]] = e
    return [bykey[k] for k in sorted(bykey)]


def instants(cik_list, tags):
    """[(tag, {data_fim: valor})] para tags de saldo (sem `start`), na ordem pedida."""
    out = []
    for tag in tags:
        for cik in cik_list:
            res = concept(cik, tag)
            if not res:
                continue
            units, _ = res
            m = {e["end"]: e["val"] for e in units if "end" in e and "start" not in e}
            if m:
                out.append((tag, m))
                break
    return out


def _at(maps, date):
    """Primeiro grupo que tem valor NAQUELA data. Sem valor -> None (nunca zero)."""
    for _, m in maps:
        if m.get(date) is not None:
            return m[date]
    return None


def netdebt_series(cik_list, ends):
    """Divida liquida = divida bruta - (caixa + aplicacoes de curto prazo).

    Devolve lista alinhada a `ends`, em bilhoes, com None onde a divida nao esta
    publicada na data -- preferivel a um zero que o grafico leria como
    'empresa sem divida'.
    """
    total = instants(cik_list, DEBT_TOTAL)
    noncur = instants(cik_list, DEBT_NONCURRENT)
    curr = instants(cik_list, DEBT_CURRENT)
    cash = instants(cik_list, CASH_TAGS)
    inv = instants(cik_list, INVEST_TAGS)
    out = []
    for e in ends:
        gross = _at(total, e)
        if gross is None:
            nc = _at(noncur, e)
            if nc is None:
                out.append(None)
                continue
            gross = nc + (_at(curr, e) or 0)
        liquid = (_at(cash, e) or 0) + (_at(inv, e) or 0)
        out.append(round((gross - liquid) / 1e9, 3))
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
        ends = dedupe_by_quarter(rev.keys())[-NQ:]
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

        rev_col = col(c.get("rev", []))

        # Margem bruta: varias empresas nao publicam GrossProfit mas publicam o
        # custo. Deriva gp = receita - custo em vez de deixar a linha vazia.
        gp_col = col(c.get("gp", []))
        if all(v is None for v in gp_col) and c.get("cogs"):
            cogs_col = col(c["cogs"])
            gp_col = [None if (r is None or cg is None) else round(r - cg, 3)
                      for r, cg in zip(rev_col, cogs_col)]

        entry = dict(
            src="SEC EDGAR", asof=qlabel(ends[-1])[1],
            q=labels,
            rev=rev_col,
            gp=gp_col,
            ebitda=col(c.get("ebitda", [])),
            ni=col(c.get("ni", [])),
            eps=col_ps(c.get("eps", [])),
            capex=col(c.get("capex", [])),
            div=col(c.get("div", [])),
            buyback=col(c.get("buyback", [])),
            # Banco nao tem "divida liquida" com sentido economico: captacao e
            # materia-prima, nao alavancagem. JPM e BLK ficam de fora de proposito.
            netdebt=([None] * len(ends) if c.get("bank")
                     else netdebt_series(c["cik"], ends)),
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

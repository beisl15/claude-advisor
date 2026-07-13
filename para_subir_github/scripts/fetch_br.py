#!/usr/bin/env python3
"""
Gera data/br.json com fundamentos das posicoes B3 — DIRETO DA CVM (fonte oficial).
Baixa os ZIPs de ITR (trimestral) e DFP (anual) de dados.cvm.gov.br, descompacta
em memoria e parseia a DRE/Balanco consolidados. Sem chave de API.
Roda no GitHub Actions (tem rede e consegue baixar/descompactar os ZIP).

Saida por ticker: receita/EBIT/lucro (12m e ultimo tri), margens, ROE, divida liq,
patrimonio, asof. Valuation (P/L etc.) fica a cargo do fetch_prices.py (precisa de preco).
"""
import json, os, io, csv, zipfile, datetime, sys, urllib.request
from collections import defaultdict

OUT = os.path.join(os.path.dirname(__file__), "..", "data", "br.json")
BASE = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC"
UA = "Mozilla/5.0 (compatible; claude-advisor-dashboard)"

# ticker -> substring do nome em DENOM_CIA (CVM). Expanda aqui p/ cobrir mais B3.
NAMES = {
    "SMFT3": "SMART FIT",
    "PRIO3": "PRIO",
    "SBSP3": "SANEAMENTO BASICO",
    "PETR4": "PETROLEO BRASILEIRO",
    "PETR3": "PETROLEO BRASILEIRO",
    "VALE3": "VALE S.A",
    "VIVT3": "TELEFONICA BRASIL",
    "TIMS3": "TIM S.A",
    "TOTS3": "TOTVS",
    "ABEV3": "AMBEV",
    "CSMG3": "COPASA",
    # Bancos têm DRE de instituição financeira (sem EBIT/3.05); receita e lucro saem,
    # mas margem EBIT/bruta podem vir vazias — ok, o front mostra o que houver.
    "ITUB4": "ITAU UNIBANCO",
    "BPAC11": "BTG PACTUAL",
}
# contas da DRE consolidada (CD_CONTA)
DRE = {"rev": "3.01", "gross": "3.03", "ebit": "3.05", "ni": "3.11"}


def fetch_zip(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        return zipfile.ZipFile(io.BytesIO(r.read()))


def read_csv_from_zip(zf, name_contains):
    for n in zf.namelist():
        if name_contains in n:
            with zf.open(n) as fh:
                txt = io.TextIOWrapper(fh, encoding="latin-1")
                return list(csv.DictReader(txt, delimiter=";"))
    return []


def months(a, b):
    da = datetime.date.fromisoformat(a); db = datetime.date.fromisoformat(b)
    return round((db - da).days / 30.4)


def scale(row):
    return 1000.0 if row.get("ESCALA_MOEDA", "").upper().startswith("MIL") else 1.0


def collect(rows, name, want_months):
    """Retorna {(DT_FIM): {conta: valor_em_R$}} para a empresa, periodos ~want_months,
    pegando ORDEM_EXERC=ULTIMO (exercicio atual)."""
    out = defaultdict(dict)
    inv = {v: k for k, v in DRE.items()}
    for r in rows:
        if name not in (r.get("DENOM_CIA", "") or "").upper():
            continue
        if (r.get("ORDEM_EXERC", "") or "").upper() != "ÚLTIMO" and (r.get("ORDEM_EXERC", "") or "").upper() != "ULTIMO":
            continue
        cc = r.get("CD_CONTA", "")
        if cc not in inv:
            continue
        ini, fim = r.get("DT_INI_EXERC", ""), r.get("DT_FIM_EXERC", "")
        if not ini or not fim:
            continue
        if abs(months(ini, fim) - want_months) > 1:
            continue
        try:
            v = float((r.get("VL_CONTA", "") or "0").replace(",", "."))
        except ValueError:
            continue
        out[fim][inv[cc]] = v * scale(r)
    return out


def equity_for(name, years):
    """Patrimonio liquido (conta 2.03) do BPP consolidado mais recente."""
    best = None
    for y in years:
        try:
            zf = fetch_zip(f"{BASE}/ITR/DADOS/itr_cia_aberta_{y}.zip")
        except Exception:
            continue
        rows = read_csv_from_zip(zf, f"itr_cia_aberta_BPP_con_{y}.csv")
        for r in rows:
            if name not in (r.get("DENOM_CIA", "") or "").upper():
                continue
            if r.get("CD_CONTA") != "2.03":
                continue
            try:
                v = float((r.get("VL_CONTA") or "0").replace(",", ".")) * scale(r)
            except ValueError:
                continue
            dt = r.get("DT_FIM_EXERC", "")
            if best is None or dt > best[0]:
                best = (dt, v)
    return best[1] if best else None


def main():
    now = datetime.date.today()
    years = [now.year, now.year - 1, now.year - 2]
    # baixa DRE 3-meses (ITR) e anual (DFP) de cada ano, uma vez
    itr_q, dfp_y = {}, {}
    for y in years:
        try:
            zf = fetch_zip(f"{BASE}/ITR/DADOS/itr_cia_aberta_{y}.zip")
            itr_q[y] = read_csv_from_zip(zf, f"itr_cia_aberta_DRE_con_{y}.csv")
        except Exception as e:
            print(f". ITR {y}: {e}", file=sys.stderr)
        try:
            zf = fetch_zip(f"{BASE}/DFP/DADOS/dfp_cia_aberta_{y}.zip")
            dfp_y[y] = read_csv_from_zip(zf, f"dfp_cia_aberta_DRE_con_{y}.csv")
        except Exception as e:
            print(f". DFP {y}: {e}", file=sys.stderr)

    out = {}
    for tk, name in NAMES.items():
        name = name.upper()
        q3 = {}     # trimestres isolados (3 meses), {DT_FIM: {conta:val}}
        for y, rows in itr_q.items():
            q3.update(collect(rows, name, 3))
        ann = {}    # anual (12 meses) p/ derivar Q4 e TTM
        for y, rows in dfp_y.items():
            ann.update(collect(rows, name, 12))
        if not q3 and not ann:
            print(f"!! {tk}: nada na CVM (nome '{name}'?)", file=sys.stderr)
            continue

        ends = sorted(q3.keys())
        if not ends:
            print(f"!! {tk}: sem trimestres isolados", file=sys.stderr)
            continue
        last = ends[-1]
        lastq = q3[last]

        # TTM = ultimos 4 trimestres isolados, se disponiveis
        def ttm(metric):
            vals = [q3[e].get(metric) for e in ends[-4:]]
            vals = [v for v in vals if v is not None]
            return sum(vals) if len(vals) == 4 else None

        rev12, ebit12, ni12 = ttm("rev"), ttm("ebit"), ttm("ni")
        eq = equity_for(name, years)
        mi = lambda v: round(v / 1e6, 2) if v is not None else None
        pct = lambda a, b: round(a / b * 100, 1) if (a is not None and b) else None

        out[tk] = dict(
            asof="/".join(reversed(last.split("-"))),  # yyyy-mm-dd -> dd/mm/yyyy
            cot=None, datacot=None, min52=None, max52=None, mktcap=None, ev=None,
            revTTM=mi(rev12), ebitTTM=mi(ebit12), niTTM=mi(ni12),
            revQ=mi(lastq.get("rev")), ebitQ=mi(lastq.get("ebit")), niQ=mi(lastq.get("ni")),
            mBruta=pct(lastq.get("gross"), lastq.get("rev")),
            mEbit=pct(lastq.get("ebit"), lastq.get("rev")),
            mLiq=pct(lastq.get("ni"), lastq.get("rev")),
            roe=pct(ni12, eq) if (ni12 is not None and eq) else None,
            roic=None,
            divLiq=None, patrim=mi(eq),
            pl=None, evEbitda=None, pvp=None, dy=None,   # valuation: preenchido por fetch_prices.py
            fonte="CVM",
        )
        print(f"ok {tk}: asof={out[tk]['asof']} rev12m={out[tk]['revTTM']} ROE={out[tk]['roe']}")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    print(f"-> {OUT} ({len(out)} tickers)")


if __name__ == "__main__":
    main()

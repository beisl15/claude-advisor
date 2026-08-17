#!/usr/bin/env python3
"""
Serie trimestral das brasileiras, direto do portal de dados abertos da CVM.
Grava/atualiza data/fin.json no mesmo formato de fetch_us.py e fetch_intl.py.
Sem chave de API. Roda no GitHub Actions.

POR QUE ESTE SCRIPT EXISTE
--------------------------
As 10 brasileiras do universo estavam com serie interpolada, parada no Q4'24, e
tres delas (SMFT3/PRIO3/SBSP3) nem gerabam grafico. A CVM publica ITR e DFP em
CSV aberto, o que da 4+ anos de DRE trimestral real e auditada.

COMO A CVM ORGANIZA OS DADOS (verificado em 11/08/2026)
------------------------------------------------------
ITR  -> .../DOC/ITR/DADOS/itr_cia_aberta_<ANO>.zip   (1o, 2o e 3o trimestres)
DFP  -> .../DOC/DFP/DADOS/dfp_cia_aberta_<ANO>.zip   (exercicio fechado)

Dentro de cada zip interessam tres arquivos:
  <pref>_DRE_con_<ANO>.csv     resultado consolidado
  <pref>_BPP_con_<ANO>.csv     passivo + patrimonio liquido
  <pref>_DFC_MI_con_<ANO>.csv  fluxo de caixa (metodo indireto)

Colunas: CNPJ_CIA, DT_REFER, VERSAO, DENOM_CIA, CD_CVM, GRUPO_DFP, MOEDA,
ESCALA_MOEDA, ORDEM_EXERC, DT_INI_EXERC, DT_FIM_EXERC, CD_CONTA, DS_CONTA,
VL_CONTA, ST_CONTA_FIXA. (BPP nao tem DT_INI_EXERC: e saldo, nao fluxo.)

Tres detalhes que quebram quem nao olhou o arquivo antes:

1. ORDEM_EXERC vale 'ULTIMO' ou 'PENULTIMO'. PENULTIMO e o comparativo do ano
   anterior dentro do mesmo documento -- entra em duplicidade se nao for
   filtrado.

2. O ITR traz o trimestre discreto E o acumulado do ano lado a lado (ex.: no ITR
   de jun/26 vem 2026-04-01->2026-06-30 e 2026-01-01->2026-06-30). O 4o
   trimestre nunca aparece: sai do DFP (ano cheio) menos o acumulado de 9 meses.
   Ambos os casos sao resolvidos pela mesma regra de fetch_us.py -- agrupa por
   data de inicio, tira diferenca consecutiva e so aceita o que der ~90 dias.

3. Banco tem outro plano de contas. Em industria o lucro e 3.11; em banco e
   3.09. O patrimonio liquido e 2.03 em industria e 2.08 em banco -- por isso
   aqui ele e localizado pelo NOME da conta ('Patrimonio Liquido Consolidado'),
   que e estavel nos dois layouts, e nao pelo codigo.

Valores vem em ESCALA_MOEDA = MIL (milhares de reais) e saem em R$ bilhoes.
"""
import csv
import datetime
import io
import json
import os
import sys
import urllib.request
import unicodedata
import zipfile
from collections import defaultdict

UA = os.environ.get("SEC_UA", "claude-advisor-dashboard pedro.beisl@gmail.com")
BASE = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC"
OUT = os.path.join(os.path.dirname(__file__), "..", "data", "fin.json")

NQ = 17                       # trimestres publicados (~4 anos)
Q_MIN_DAYS, Q_MAX_DAYS = 80, 100

# CD_CVM confirmado no proprio arquivo da CVM (nao confiar em busca por nome:
# 'PRIO' casa com PRIO FORTE, subsidiaria; 'BTG PACTUAL' casa com a Sertrading).
TICKERS = {
    "PETR3":  dict(cvm="009512", eps="3.99.02.01"),                 # ON
    "PETR4":  dict(cvm="009512", eps="3.99.02.02"),                 # PN
    "SMFT3":  dict(cvm="024260", eps="3.99.02.01"),
    "PRIO3":  dict(cvm="022187", eps="3.99.02.01"),
    "SBSP3":  dict(cvm="014443", eps="3.99.02.01"),
    "VIVT3":  dict(cvm="017671", eps="3.99.02.01"),
    "TIMS3":  dict(cvm="024929", eps="3.99.02.01"),
    "ABEV3":  dict(cvm="023264", eps="3.99.02.01"),
    "ITUB4":  dict(cvm="019348", eps="3.99.02.02", bank=True),
    # BPAC11 e unit (1 ON + 2 PN); a CVM nao publica lucro por unit, entao o EPS
    # aqui e o da ON. Serve para a tendencia, nao para multiplo.
    "BPAC11": dict(cvm="022616", eps="3.99.02.01", bank=True),
}

# CD_CONTA da DRE. Ordem = tentativa: usa o primeiro que existir.
DRE = {
    "rev":    ["3.01"],
    "gp":     ["3.03"],
    "ebitda": ["3.05"],        # EBIT, na verdade -- ver nota no dashboard
    "ni":     ["3.11", "3.09"],  # 3.11 industria / 3.09 banco
}


def norm(s):
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn").upper().strip()


def days(a, b):
    fmt = "%Y-%m-%d"
    return (datetime.datetime.strptime(b, fmt) - datetime.datetime.strptime(a, fmt)).days


def fetch_zip(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=180) as r:
        return zipfile.ZipFile(io.BytesIO(r.read()))


def read_csv(zf, name):
    """Le um CSV de dentro do zip. A CVM publica em latin-1, separador ';'."""
    try:
        raw = zf.read(name)
    except KeyError:
        return []
    txt = raw.decode("latin-1")
    return list(csv.DictReader(io.StringIO(txt), delimiter=";"))


def scale(row):
    """Fator para converter VL_CONTA em bilhoes de reais."""
    return 1e6 if norm(row.get("ESCALA_MOEDA", "")) == "MIL" else 1e9


def val(row):
    try:
        return float(row["VL_CONTA"]) / scale(row)
    except (TypeError, ValueError, KeyError):
        return None


def quarterly(periods):
    """{(inicio, fim): valor} -> {fim: valor do trimestre}.

    Mesma regra de fetch_us.py: agrupa por data de inicio, tira a diferenca
    consecutiva e so aceita o resultado se o periodo implicado tiver ~90 dias.
    E o que transforma 'acumulado de 9 meses' e 'ano cheio do DFP' nos
    trimestres 3 e 4, e o que impede um valor anual de entrar como trimestral.
    """
    g = defaultdict(list)
    for (ini, fim), v in periods.items():
        g[ini].append((fim, v))
    out = {}
    for ini, lst in g.items():
        lst.sort()
        prev_end, prev_val = ini, 0.0
        for i, (fim, v) in enumerate(lst):
            if i == 0:
                dur, x = days(ini, fim), v
            else:
                dur, x = days(prev_end, fim), v - prev_val
            if Q_MIN_DAYS <= dur <= Q_MAX_DAYS:
                out.setdefault(fim, round(x, 3))
            prev_end, prev_val = fim, v
    return out


def qlabel(end):
    y, m = int(end[:4]), int(end[5:7])
    return f"CY{y}Q{(m - 1) // 3 + 1}", f"Q{(m - 1) // 3 + 1}'{end[2:4]}"


# Contas do balanco (codigos estaveis, conferidos na CVM em 11/08/2026).
# Divida bruta = circulante + nao circulante. Os codigos de 2o nivel ja somam as
# sub-contas (emprestimos, debentures, arrendamento), entao usar so eles evita
# contagem dupla.
DIVIDA_CIRC, DIVIDA_NCIRC = "2.01.04", "2.02.01"
CAIXA, APLICACOES = "1.01.01", "1.01.02"


def collect(years):
    """Baixa ITR + DFP dos anos pedidos. Devolve as linhas ja filtradas por
    ORDEM_EXERC='ULTIMO' e indexadas por CD_CVM, para nao varrer 10 vezes.

    Le a versao consolidada E a individual de cada balanco. Motivo: a TIM publica
    o BPP/BPA consolidado inteiramente zerado (nao consolida), e sem o arquivo
    individual ela sairia com patrimonio e divida = 0 -- numero errado, pior que
    ausente. Ver `com_fallback`.
    """
    dre = defaultdict(list)
    bal = {"BPP_con": defaultdict(list), "BPP_ind": defaultdict(list),
           "BPA_con": defaultdict(list), "BPA_ind": defaultdict(list)}
    dfc = defaultdict(list)
    alvos = {c["cvm"] for c in TICKERS.values()}
    for kind, pref in (("ITR", "itr"), ("DFP", "dfp")):
        for y in years:
            url = f"{BASE}/{kind}/DADOS/{pref}_cia_aberta_{y}.zip"
            try:
                zf = fetch_zip(url)
            except Exception as ex:
                print(f". {kind} {y}: {ex}", file=sys.stderr)
                continue
            alvo_bucket = [("DRE_con", dre), ("DFC_MI_con", dfc)]
            alvo_bucket += [(t, bal[t]) for t in bal]
            for tag, bucket in alvo_bucket:
                for row in read_csv(zf, f"{pref}_cia_aberta_{tag}_{y}.csv"):
                    if row.get("CD_CVM") in alvos and norm(row.get("ORDEM_EXERC", "")) == "ULTIMO":
                        bucket[row["CD_CVM"]].append(row)
            print(f"ok {kind} {y}")
    return dre, bal, dfc


def com_fallback(con_rows, ind_rows, fn):
    """Roda `fn` no consolidado; se vier vazio ou tudo zero, tenta o individual."""
    r = fn(con_rows)
    if r and any(v for v in r.values()):
        return r
    return fn(ind_rows)


def saldo_series(rows, codes):
    """Soma de contas de saldo por data-fim. Sem nenhuma das contas -> data ausente."""
    per = defaultdict(float)
    achou = defaultdict(bool)
    for r in rows:
        if r.get("CD_CONTA") in codes and r.get("DT_FIM_EXERC"):
            v = val(r)
            if v is not None:
                per[r["DT_FIM_EXERC"]] += v
                achou[r["DT_FIM_EXERC"]] = True
    return {d: round(v, 3) for d, v in per.items() if achou[d]}


def dre_series(rows, codes):
    per = {}
    for code in codes:
        for r in rows:
            if r.get("CD_CONTA") == code and r.get("DT_INI_EXERC") and r.get("DT_FIM_EXERC"):
                v = val(r)
                if v is not None:
                    # VERSAO maior = retificadora; prevalece.
                    key = (r["DT_INI_EXERC"], r["DT_FIM_EXERC"])
                    prev = per.get(key)
                    if prev is None or int(r.get("VERSAO", 1)) >= prev[1]:
                        per[key] = (v, int(r.get("VERSAO", 1)))
        if per:
            break   # achou o plano de contas certo, nao mistura com o fallback
    return quarterly({k: v[0] for k, v in per.items()})


def eps_series(rows, code):
    """Lucro por acao ja vem em R$/acao -- nao escalar."""
    per = {}
    for r in rows:
        if r.get("CD_CONTA") == code and r.get("DT_INI_EXERC"):
            try:
                per[(r["DT_INI_EXERC"], r["DT_FIM_EXERC"])] = float(r["VL_CONTA"])
            except (TypeError, ValueError):
                pass
    return {k: round(v, 2) for k, v in quarterly(per).items()}


def equity_series(rows):
    """Patrimonio liquido: saldo instantaneo, localizado pelo NOME da conta
    porque o codigo muda entre industria (2.03) e banco (2.08)."""
    out = {}
    for r in rows:
        if norm(r.get("DS_CONTA", "")) == "PATRIMONIO LIQUIDO CONSOLIDADO":
            v = val(r)
            if v is not None:
                out[r["DT_FIM_EXERC"]] = round(v, 3)
    return out


def cash_series(rows, section, include, exclude=()):
    """Linhas do fluxo de caixa por secao + padrao no nome da conta.

    A CVM nao padroniza o codigo dessas linhas (capex e 6.02.01 na Petrobras e
    6.02.02 na Ambev), so a secao: 6.02 = investimento, 6.03 = financiamento.
    Sai em valor absoluto, somando as linhas que casarem.
    """
    per = defaultdict(float)
    seen = set()
    for r in rows:
        cd, ds = r.get("CD_CONTA", ""), norm(r.get("DS_CONTA", ""))
        if not cd.startswith(section) or not r.get("DT_INI_EXERC"):
            continue
        if not any(p in ds for p in include) or any(p in ds for p in exclude):
            continue
        v = val(r)
        if v is None:
            continue
        k = (r["DT_INI_EXERC"], r["DT_FIM_EXERC"], cd)
        if k in seen:
            continue
        seen.add(k)
        per[(r["DT_INI_EXERC"], r["DT_FIM_EXERC"])] += abs(v)
    return quarterly(dict(per))


def build(tk, cfg, dre_rows, bal, dfc_rows):
    rev = dre_series(dre_rows, DRE["rev"])
    if not rev:
        return None
    ends, bykey = sorted(rev.keys()), {}
    for e in ends:
        bykey[qlabel(e)[0]] = e
    ends = [bykey[k] for k in sorted(bykey)][-NQ:]

    def col(series):
        return [series.get(e) for e in ends]

    ni = dre_series(dre_rows, DRE["ni"])
    cvm = cfg["cvm"]
    eq = com_fallback(bal["BPP_con"][cvm], bal["BPP_ind"][cvm], equity_series)

    # Divida liquida = (circulante + nao circulante) - (caixa + aplicacoes).
    # Banco fica de fora: captacao e materia-prima, nao alavancagem.
    if cfg.get("bank"):
        nd = {}
    else:
        div = com_fallback(bal["BPP_con"][cvm], bal["BPP_ind"][cvm],
                           lambda r: saldo_series(r, {DIVIDA_CIRC, DIVIDA_NCIRC}))
        cx = com_fallback(bal["BPA_con"][cvm], bal["BPA_ind"][cvm],
                          lambda r: saldo_series(r, {CAIXA, APLICACOES}))
        nd = {d: round(v - cx.get(d, 0.0), 3) for d, v in div.items()}
    entry = dict(
        src="CVM (ITR/DFP)", asof=qlabel(ends[-1])[1], moeda="BRL",
        q=[qlabel(e)[1] for e in ends],
        rev=col(rev),
        gp=col(dre_series(dre_rows, DRE["gp"])),
        ebitda=col(dre_series(dre_rows, DRE["ebitda"])),
        ni=col(ni),
        eps=col(eps_series(dre_rows, cfg["eps"])),
        capex=col(cash_series(dfc_rows, "6.02", ("AQUISI",),
                              exclude=("RECEBID", "VENDA", "PROVENTO"))),
        div=col(cash_series(dfc_rows, "6.03", ("DIVIDENDO", "JUROS SOBRE O CAPITAL"),
                            exclude=("RECEBID",))),
        buyback=col(cash_series(dfc_rows, "6.03", ("RECOMPRA", "TESOURARIA"))),
        netdebt=[nd.get(e) for e in ends],
        equity=[eq.get(e) for e in ends],
    )
    if cfg.get("bank"):
        entry["bank"] = True
    return entry


def main():
    hoje = datetime.date.today()
    anos = list(range(hoje.year - 4, hoje.year + 1))
    dre, bal, dfc = collect(anos)

    try:
        with open(OUT) as f:
            fin = json.load(f)
    except Exception:
        fin = {}

    n = 0
    for tk, cfg in TICKERS.items():
        cvm = cfg["cvm"]
        try:
            e = build(tk, cfg, dre[cvm], bal, dfc[cvm])
        except Exception as ex:
            print(f"!! {tk}: {ex}", file=sys.stderr)
            continue
        if not e:
            print(f"!! {tk}: sem receita na CVM (CD_CVM {cvm})", file=sys.stderr)
            continue
        fin[tk] = e
        n += 1
        print(f"ok {tk}: {e['q'][0]}..{e['q'][-1]} ({len(e['q'])} tri) "
              f"rev_ult={e['rev'][-1]} ni_ult={e['ni'][-1]}")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(fin, f, indent=1, ensure_ascii=False)
    print(f"-> {OUT} ({n} brasileiras; {len(fin)} tickers no total)")


if __name__ == "__main__":
    main()

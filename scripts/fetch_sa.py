#!/usr/bin/env python3
"""
Serie trimestral longa de TSM, RACE, ABI e ROXO. Atualiza data/fin.json.
Sem dependencia externa (so a biblioteca padrao).

POR QUE ESTE SCRIPT EXISTE
--------------------------
Esses quatro sao foreign private issuers: so arquivam 20-F anual na SEC, sem
10-Q, logo nao ha serie trimestral em XBRL (verificado em 11/08/2026 varrendo
companyfacts dos quatro CIKs -- nenhuma tag com periodo de ~90 dias). O Yahoo
entrega no maximo 5 trimestres, teto do proprio servidor.

A rota preferida seria o RI de cada companhia, como foi feito para a ASML em
fetch_ir_asml.py. Nao funciona para estes quatro, e a razao e tecnica, nao de
esforco: os sites de RI da Ferrari, AB InBev e Nu montam os links de download
por JavaScript. Um script Python no GitHub Actions nao executa JS, entao nem
descobre o endereco do arquivo -- a questao de saber parsear PDF nem chega a se
colocar. A TSMC ate tem URL de trimestre previsivel, mas publica so PDF com
caminho hasheado. A ASML foi a excecao: HTML server-rendered, URL previsivel e
XLSX oficial.

Daqui saem os quatro de uma vez, de uma pagina que e server-rendered (o HTML ja
vem com a tabela pronta, sem JS) e traz 20 trimestres. Uso pessoal, 12 requests
por dia no total -- por isso o intervalo entre chamadas.

ATENCAO: fonte secundaria, nao a companhia. Roda DEPOIS do fetch_intl.py e so
sobrescreve se conseguir extrair receita; se o layout mudar, o script falha alto
(retorna erro) em vez de gravar serie vazia, e o dashboard fica com os 5
trimestres do Yahoo.
"""
import json
import os
import re
import sys
import time
import urllib.request

HERE = os.path.dirname(__file__)
OUT = os.path.join(HERE, "..", "data", "fin.json")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124 Safari/537.36")
BASE = "https://stockanalysis.com/stocks/{s}/financials/{p}?p=quarterly"
NQ = 17

# ticker no dashboard -> (simbolo no site, moeda de reporte)
SYMBOLS = {
    "TSM":  ("tsm",  "TWD"),
    "RACE": ("race", "EUR"),
    "ABI":  ("bud",  "USD"),
    "ROXO": ("nu",   "USD"),
}

# Nu e banco: divida liquida nao tem sentido economico. Mesmo criterio de
# JPM e BLK.
SEM_NETDEBT = {"ROXO"}

# pagina -> {rotulo inicial da linha: chave no nosso FIN}
PAGINAS = {
    "": {                                   # demonstracao de resultado
        "revenue": "rev",
        "gross profit": "gp",
        "operating income": "ebitda",       # EBIT (ver nota do dashboard)
        "net income": "ni",
        "earnings per share": "eps",
    },
    "balance-sheet/": {
        "cash & equivalents": "_cash",
        "cash & short-term investments": "_cash2",
        "total debt": "_debt",
    },
    "cash-flow-statement/": {
        "capital expenditures": "capex",
        "dividends paid": "div",
        "share repurchases": "buyback",
    },
}


def baixa(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace")


def celulas(tr):
    return [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c))
            .replace(" ", " ").strip()
            for c in re.findall(r"<(?:td|th)[^>]*>([\s\S]*?)</(?:td|th)>", tr, re.I)]


def tabelas(html):
    for t in re.findall(r"<table[\s\S]*?</table>", html, re.I):
        linhas = [celulas(tr) for tr in re.findall(r"<tr[^>]*>([\s\S]*?)</tr>", t, re.I)]
        linhas = [l for l in linhas if l]
        if linhas:
            yield linhas


def data_iso(txt):
    """'Jun '26 Jun 30, 2026' -> '2026-06-30'. A celula repete o periodo em dois
    formatos; o segundo e o completo."""
    m = re.search(r"([A-Z][a-z]{2}) (\d{1,2}), (\d{4})", txt)
    if not m:
        return None
    meses = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
             "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}
    mes = meses.get(m.group(1))
    return f"{m.group(3)}-{mes:02d}-{int(m.group(2)):02d}" if mes else None


def numero(txt):
    """'1,270,381' -> 1270381.0 ; '(123)' -> -123.0 ; '-' e '' -> None."""
    t = (txt or "").strip().replace(",", "").replace("%", "")
    if t in ("", "-", "--", "n/a", "N/A", "Upgrade"):
        return None
    neg = t.startswith("(") and t.endswith(")")
    if neg:
        t = t[1:-1]
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v


def rotulo(cel):
    """A celula do rotulo vem colada com a linha de crescimento
    ('Revenue Revenue Growth'). Interessa so o comeco."""
    return re.sub(r"\s+", " ", (cel or "")).strip().lower()


def le_pagina(sym, pag, mapa):
    html = baixa(BASE.format(s=sym, p=pag))
    melhor, ndatas = None, 0
    for linhas in tabelas(html):
        idx = next((i for i, l in enumerate(linhas)
                    if l and rotulo(l[0]).startswith("period ending")), None)
        if idx is None:
            continue
        datas = [data_iso(c) for c in linhas[idx][1:]]
        if sum(1 for d in datas if d) > ndatas:
            melhor, ndatas = (linhas, idx, datas), sum(1 for d in datas if d)
    if not melhor:
        return {}
    linhas, idx, datas = melhor
    out = {}
    for l in linhas[idx + 1:]:
        r = rotulo(l[0])
        chave = next((v for k, v in mapa.items() if r.startswith(k)), None)
        if chave is None:
            continue
        for i, d in enumerate(datas):
            if d is None or i + 1 >= len(l):
                continue
            v = numero(l[i + 1])
            if v is not None:
                out.setdefault(chave, {}).setdefault(d, v)
    return out


def qlabel(d):
    y, m = int(d[:4]), int(d[5:7])
    return f"CY{y}Q{(m - 1) // 3 + 1}", f"Q{(m - 1) // 3 + 1}'{d[2:4]}"


def monta(tk, sym, moeda):
    dados = {}
    for pag, mapa in PAGINAS.items():
        try:
            for k, serie in le_pagina(sym, pag, mapa).items():
                dados.setdefault(k, {}).update(serie)
        except Exception as ex:
            print(f". {tk} [{pag or 'income'}]: {ex}", file=sys.stderr)
        time.sleep(1.5)
    if not dados.get("rev"):
        return None

    bykey = {}
    for d in sorted(dados["rev"]):
        bykey[qlabel(d)[0]] = d
    datas = [bykey[k] for k in sorted(bykey)][-NQ:]

    def col(k, escala=1e3, absoluto=False):     # milhoes -> bilhoes
        s = dados.get(k, {})
        out = []
        for d in datas:
            v = s.get(d)
            if v is None:
                out.append(None)
            else:
                v = v / escala
                out.append(round(abs(v) if absoluto else v, 3))
        return out

    nd = []
    for d in datas:
        dv = dados.get("_debt", {}).get(d)
        if dv is None or tk in SEM_NETDEBT:
            nd.append(None)
            continue
        cx = dados.get("_cash2", {}).get(d)
        if cx is None:
            cx = dados.get("_cash", {}).get(d) or 0.0
        nd.append(round((dv - cx) / 1e3, 3))

    return dict(
        src="stockanalysis.com (trimestral)", asof=qlabel(datas[-1])[1], moeda=moeda,
        q=[qlabel(d)[1] for d in datas],
        rev=col("rev"), gp=col("gp"), ebitda=col("ebitda"), ni=col("ni"),
        eps=col("eps", 1),
        capex=col("capex", absoluto=True), div=col("div", absoluto=True),
        buyback=col("buyback", absoluto=True),
        netdebt=nd,
    )


def main():
    try:
        with open(OUT) as f:
            fin = json.load(f)
    except Exception:
        fin = {}
    n = 0
    for tk, (sym, moeda) in SYMBOLS.items():
        try:
            e = monta(tk, sym, moeda)
        except Exception as ex:
            print(f"!! {tk}: {ex}", file=sys.stderr)
            continue
        if not e:
            print(f"!! {tk}: sem receita extraida — entrada anterior mantida", file=sys.stderr)
            continue
        fin[tk] = e
        n += 1
        print(f"ok {tk}: {e['q'][0]}..{e['q'][-1]} ({len(e['q'])} tri) "
              f"rev_ult={e['rev'][-1]} {moeda}")
    if not n:
        print("!! nenhum ticker extraido — layout da fonte pode ter mudado", file=sys.stderr)
        return 1
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(fin, f, indent=1, ensure_ascii=False)
    print(f"-> {n} estrangeiras com serie longa; {len(fin)} tickers no total")
    return 0


if __name__ == "__main__":
    sys.exit(main())

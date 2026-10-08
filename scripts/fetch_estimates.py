#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gera data/estimates.json: consenso de mercado por empresa, de stockanalysis.com.
Sem dependencia externa (so a biblioteca padrao).

POR QUE ESTE SCRIPT EXISTE
--------------------------
Tudo que o dashboard tinha ate agora era REALIZADO (SEC / RI / CVM). Sem uma
linha de base do consenso nao da nem para enunciar a frase que justifica uma
posicao -- "o consenso projeta X, eu projeto Y". Este e o insumo que destrava a
caixinha de valuation e a de variant perception.

A pagina /forecast/ e server-rendered (o HTML ja vem com as tabelas prontas,
sem JS) e traz, de uma vez:

  tabela "Target"       preco-alvo low / average / median / high + upside
  tabela "Rating"       distribuicao de recomendacoes nos ultimos ~6 meses
  tabela "Fiscal Year"  projecao anual: receita, EPS, forward PE, FCF, nº de
                        analistas -- com a linha "Period Ending", que e' o que
                        permite achar o proximo exercicio sem chutar calendario
  tabelas "Revenue"/"EPS"  dispersao alto / medio / baixo do consenso

A dispersao importa tanto quanto a media: banda larga significa nome contestado,
que e' onde uma visao divergente vale alguma coisa. Media sozinha esconde isso.

DECISOES QUE PARECEM DETALHE E NAO SAO
--------------------------------------
1. O forward PE vem PRONTO da fonte; nao e' recalculado aqui. ASML e RACE
   projetam em EUR e a TSM em TWD, enquanto o preco no dashboard e' o do ADR em
   USD -- dividir um pelo outro daria um numero sem sentido. A pagina declara a
   moeda ("currency is EUR") e ela e' gravada junto; ausencia da nota = USD.
2. O proximo exercicio sai da linha "Period Ending" (primeira data no futuro),
   nao da posicao da coluna. A Microsoft fecha em junho e a Nvidia em janeiro;
   qualquer regra posicional erra em uma das duas.
3. "Upgrade"/"Pro" sao celulas de paywall, viram None -- nao zero.
4. A tendencia de revisao NAO precisa de estado guardado: a propria tabela de
   ratings ja vem com 6 meses de historico.

Fonte secundaria, nao a companhia. Se o layout mudar, o script grava o que
conseguiu e o run_step.py marca a fonte; nada e' inventado.
"""
import datetime
import json
import os
import re
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "data", "estimates.json")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124 Safari/537.36")
URL = "https://stockanalysis.com/stocks/{s}/forecast/"
PAUSA = 1.5          # uso pessoal: ~28 requests/dia


def url_de(sym):
    """RHM nao tem listagem americana: stockanalysis usa /quote/etr/RHM/ em vez
    de /stocks/{s}/ para nomes sem ticker US. Symbol com '/' ja vem com o path
    completo (ver SYMBOLS['RHM'])."""
    if "/" in sym:
        return f"https://stockanalysis.com/{sym}/forecast/"
    return URL.format(s=sym)

# ticker do dashboard -> simbolo no site (a listagem americana, quando existe)
SYMBOLS = {
    "GOGL": "googl", "MSFT": "msft", "META": "meta", "AMZN": "amzn",
    "MELI": "meli", "ASML": "asml", "JPM": "jpm", "BLK": "blk", "MU": "mu",
    "AAPL": "aapl", "NVDA": "nvda", "AMD": "amd", "INTC": "intc",
    "MRVL": "mrvl", "AVGO": "avgo", "TSM": "tsm", "ROXO": "nu", "RACE": "race",
    "VZ": "vz", "TMUS": "tmus", "T": "t", "ABI": "bud",
    "ORCL": "orcl", "NOW": "now", "PLTR": "pltr",
    "CEG": "ceg", "VST": "vst", "GEV": "gev",
    "RHM": "quote/etr/RHM",  # Rheinmetall — sem ADR, path proprio (ver url_de)
}

MESES = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
         "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}
VAZIO = {"", "-", "--", "n/a", "N/A", "Upgrade", "Pro", "upgrade", "pro"}


# ── parsing generico de tabela (mesmo estilo do fetch_sa.py) ──────────────────
def baixa(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace")


def celulas(tr):
    return [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c))
            .replace(" ", " ").strip()
            for c in re.findall(r"<(?:td|th)[^>]*>([\s\S]*?)</(?:td|th)>", tr, re.I)]


def tabelas(html):
    """Devolve cada <table> como lista de linhas, cada linha lista de celulas."""
    for t in re.findall(r"<table[\s\S]*?</table>", html, re.I):
        linhas = [celulas(tr) for tr in re.findall(r"<tr[^>]*>([\s\S]*?)</tr>", t, re.I)]
        linhas = [l for l in linhas if l]
        if linhas:
            yield linhas


def acha(tabs, padrao):
    """Primeira tabela cuja celula [0][0] casa com o padrao."""
    rx = re.compile(padrao, re.I)
    for linhas in tabs:
        if linhas[0] and rx.match(linhas[0][0].strip()):
            return linhas
    return None


def linha(tab, rotulo):
    if not tab:
        return None
    r = rotulo.lower()
    for l in tab[1:]:
        if l and l[0].strip().lower().startswith(r):
            return l[1:]
    return None


def num(txt):
    """'393.93B' -> 393.93 (em bilhoes) ; '$302.83' -> 302.83 ; '(12)' -> -12 ;
    '1,799.40%' -> 1799.4 ; 'Upgrade'/'Pro'/'-' -> None."""
    t = (txt or "").strip()
    if t in VAZIO:
        return None
    neg = t.startswith("(") and t.endswith(")")
    if neg:
        t = t[1:-1]
    t = t.replace(",", "").replace("$", "").replace("%", "").replace("€", "").strip()
    mult = 1.0
    if t[-1:] in ("T", "B", "M", "K"):
        mult = {"T": 1000.0, "B": 1.0, "M": 0.001, "K": 0.000001}[t[-1]]
        t = t[:-1]
    try:
        v = float(t)
    except ValueError:
        return None
    v *= mult
    return round(-v if neg else v, 4)


def data_iso(txt):
    m = re.search(r"([A-Z][a-z]{2}) (\d{1,2}), (\d{4})", txt or "")
    if not m or m.group(1) not in MESES:
        return None
    return "%s-%02d-%02d" % (m.group(3), MESES[m.group(1)], int(m.group(2)))


# ── extracao por empresa ──────────────────────────────────────────────────────
def parse(html, hoje=None):
    hoje = hoje or datetime.date.today()
    tabs = list(tabelas(html))
    rec = {}

    # moeda: a pagina so avisa quando NAO e' dolar
    m = re.search(r"currency is (\w+)", html, re.I)
    rec["moeda"] = (m.group(1).upper() if m else "USD")

    # ── projecao anual ────────────────────────────────────────────────────────
    anual = acha(tabs, r"fiscal year")
    if anual:
        anos = anual[0][1:]
        fins = [data_iso(c) for c in (linha(anual, "period ending") or [])]
        # o proximo exercicio e' a primeira data no futuro — nao uma posicao fixa:
        # a Microsoft fecha em junho e a Nvidia em janeiro.
        i = next((k for k, d in enumerate(fins) if d and d > hoje.isoformat()), None)
        if i is not None:
            def cel(rot):
                l = linha(anual, rot)
                return num(l[i]) if l and i < len(l) else None
            rec["ntm"] = {
                "fy":         anos[i] if i < len(anos) else None,
                "fim":        fins[i],
                "rev":        cel("revenue"),
                "rev_growth": cel("revenue growth"),
                "ebit":       cel("operating income"),
                "ni":         cel("net income"),
                "eps":        cel("eps"),
                "eps_growth": cel("eps growth"),
                "fpe":        cel("forward pe"),
                "fcf":        cel("free cash flow"),
                "n":          cel("no. analysts"),
            }
            # Serie historica do PROPRIO forward PE, como a fonte calcula.
            # Esta e a peca que permite dizer "caro contra a propria historia"
            # sem cruzar duas fontes: o P/E historico montado a mao (preco de um
            # lado, EPS da SEC do outro) quebra em quem fez split -- a Nvidia
            # desdobrou 10:1 em 2024. Aqui preco e lucro vem do mesmo lugar e ja
            # estao na mesma base.
            l_fpe, l_rev, l_eps = (linha(anual, "forward pe"), linha(anual, "revenue"),
                                   linha(anual, "eps"))
            rec["hist"] = {
                "anos": anos,
                "fim":  fins,
                "i_ntm": i,
                "fpe":  [num(x) for x in (l_fpe or [])],
                "rev":  [num(x) for x in (l_rev or [])],
                "eps":  [num(x) for x in (l_eps or [])],
            }

            # o exercicio corrente serve de base para ler a inflexao
            if i > 0:
                def cel0(rot):
                    l = linha(anual, rot)
                    return num(l[i - 1]) if l and i - 1 < len(l) else None
                rec["atual"] = {"fy": anos[i - 1] if i - 1 < len(anos) else None,
                                "fim": fins[i - 1], "rev": cel0("revenue"),
                                "eps": cel0("eps"), "fpe": cel0("forward pe")}

    # ── dispersao do consenso (alto / medio / baixo) ──────────────────────────
    def banda(tab):
        if not tab:
            return None
        hi, avg, lo = linha(tab, "high"), linha(tab, "avg"), linha(tab, "low")
        if not (hi and avg and lo):
            return None
        v = {"hi": num(hi[0]), "avg": num(avg[0]), "lo": num(lo[0]),
             "ano": tab[0][1] if len(tab[0]) > 1 else None}
        return v if v["avg"] is not None else None

    d_rev, d_eps = banda(acha(tabs, r"^revenue$")), banda(acha(tabs, r"^eps$"))
    if d_rev or d_eps:
        rec["disp"] = {"rev": d_rev, "eps": d_eps}

    # ── preco-alvo ────────────────────────────────────────────────────────────
    alvo = acha(tabs, r"^target$")
    if alvo:
        cab = [c.strip().lower() for c in alvo[0][1:]]
        preco, mud = linha(alvo, "price"), linha(alvo, "change")
        if preco:
            pt = {}
            for k, nome in (("low", "lo"), ("average", "avg"), ("median", "med"), ("high", "hi")):
                if k in cab:
                    j = cab.index(k)
                    if j < len(preco):
                        pt[nome] = num(preco[j])
                    if mud and j < len(mud):
                        pt[nome + "_up"] = num(mud[j])
            if pt:
                rec["pt"] = pt

    # ── postura do sell-side, com os ~6 meses que a propria tabela ja traz ────
    rat = acha(tabs, r"^rating$")
    if rat:
        meses = rat[0][1:]
        serie = {}
        for chave, rot in (("sb", "strong buy"), ("b", "buy"), ("h", "hold"),
                           ("s", "sell"), ("ss", "strong sell"), ("total", "total")):
            l = linha(rat, rot)
            if l:
                serie[chave] = [num(x) for x in l]
        if serie:
            rec["ratings"] = {"meses": meses, **serie}

    return rec


def coleta(tk, sym):
    html = baixa(url_de(sym))
    rec = parse(html)
    if not rec.get("ntm"):
        raise ValueError("tabela anual nao encontrada (layout mudou?)")
    rec["sym"] = sym
    rec["src"] = "stockanalysis.com/forecast"
    rec["asof"] = datetime.date.today().isoformat()
    return rec


def main():
    out, falhas = {}, []
    for tk, sym in SYMBOLS.items():
        try:
            rec = coleta(tk, sym)
            out[tk] = rec
            n = rec["ntm"]
            print("ok %-5s %-6s %s  eps=%s  fPE=%s  n=%s  %s"
                  % (tk, sym, n.get("fim"), n.get("eps"), n.get("fpe"),
                     n.get("n"), rec["moeda"]))
        except Exception as exc:                               # noqa: BLE001
            falhas.append(tk)
            print(". %s (%s): %s" % (tk, sym, exc), file=sys.stderr)
        time.sleep(PAUSA)

    if not out:
        # nada extraido = layout quebrou. Falha alto em vez de gravar arquivo
        # vazio por cima de um bom.
        print("nenhuma empresa extraida — nao vou sobrescrever o arquivo",
              file=sys.stderr)
        return 1

    out["_asof"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1, sort_keys=True)
    print("-> %s (%d de %d empresas%s)"
          % (OUT, len(out) - 1, len(SYMBOLS),
             ("; falharam: " + ", ".join(falhas)) if falhas else ""))
    print("HEALTH_N=%d" % (len(out) - 1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

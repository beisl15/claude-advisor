#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Confere a CONSISTENCIA DE CADASTRO do dashboard, sem rede, em segundos.

POR QUE ESTE SCRIPT EXISTE
--------------------------
O `validate_ciks.py` ja cuida do risco de dado errado ("CIK errado nao gera
erro, o companyconcept responde 200 com o balanco de outra empresa"). Este aqui
cuida do risco irmao, que ja aconteceu duas vezes neste projeto: **cadastro
incompleto tambem nao gera erro**.

  - a tira "Coverage Universe" era lista fixa e ficou congelada em 12 de 38 nomes;
  - a tupla de regioes do fetch_news aparecia em 6 lugares e esquecer um quebrava
    o funil em silencio;
  - `bucketOf()` cai em 'other' quando nao reconhece o setor -- um setor com
    typo some da leitura sem avisar ninguem.

Nenhum desses aparece como excecao. Todos aparecem aqui.

Roda antes do push (`python scripts/selftest.py`) e em CI a cada push. Sai com
codigo 1 se houver ERRO; AVISO nao reprova.
"""
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
INDEX = os.path.join(ROOT, "index.html")
WORKFLOW = os.path.join(ROOT, ".github", "workflows", "update.yml")

ERROS, AVISOS = [], []
def erro(msg):  ERROS.append(msg)
def aviso(msg): AVISOS.append(msg)


# ── leitura do index.html ─────────────────────────────────────────────────────
def bloco(txt, nome, abre):
    """Corpo de `const NOME = [` ou `const NOME = {` ate o fechamento na coluna 0."""
    fecha = "];" if abre == "[" else "};"
    m = re.search(r"^const %s = \%s$" % (re.escape(nome), abre), txt, re.M)
    if not m:
        m = re.search(r"^const %s = \%s" % (re.escape(nome), abre), txt, re.M)
    if not m:
        return None
    fim = txt.find("\n" + fecha, m.end())
    return txt[m.end():fim] if fim > 0 else None


def chaves(corpo):
    """Chaves de primeiro nivel de um objeto JS ( 'ABC': ... )."""
    return re.findall(r"^  '([A-Z0-9]+)':", corpo or "", re.M)


def ler_index():
    txt = io.open(INDEX, encoding="utf-8").read()
    d = {"_txt": txt}

    corpo_p = bloco(txt, "P", "[")
    if corpo_p is None:
        erro("nao encontrei o bloco `const P = [` no index.html")
        return d
    d["P"] = []
    for l in corpo_p.split("\n"):
        m = re.search(r"\{t:'([A-Z0-9]+)'", l)
        if not m:
            continue
        campo = lambda k: (re.search(r"\b%s:'([A-Z_0-9]+)'" % k, l) or [None, None])[1]
        d["P"].append({
            "t": m.group(1), "s": campo("s"), "g": campo("g"),
            "d": campo("d"), "d2": campo("d2"),
            "etf": "etf:true" in l.replace(" ", ""),
        })

    d["BUCKET_SECTORS"] = set()
    for linha in (bloco(txt, "BUCKETS", "[") or "").split("\n"):
        for s in re.findall(r"'([A-Z]+)'", linha.split("sectors:")[-1] if "sectors:" in linha else ""):
            d["BUCKET_SECTORS"].add(s)

    d["DRIVERS"] = set(re.findall(r"\{k:'([A-Z_]+)'", bloco(txt, "DRIVERS", "[") or ""))
    d["ANALYSIS"] = set(chaves(bloco(txt, "ANALYSIS", "{")))
    d["DEEPDIVE"] = set(chaves(bloco(txt, "DEEPDIVE", "{")))
    d["PEERS"] = set(chaves(bloco(txt, "PEERS", "{")))
    d["ETF_NOTES"] = set(chaves(bloco(txt, "ETF_NOTES", "{")))
    d["EARNINGS"] = set(re.findall(r"\{t:'([A-Z0-9]+)'", bloco(txt, "EARNINGS", "[") or ""))
    d["DATAS_FICHA"] = re.findall(r"date: '([^']+)'", bloco(txt, "ANALYSIS", "{") or "")
    return d


# ── leitura dos coletores ─────────────────────────────────────────────────────
def mod(nome):
    sys.path.insert(0, HERE)
    try:
        return __import__(nome)
    except Exception as exc:                                   # noqa: BLE001
        erro("nao consegui importar scripts/%s.py: %s" % (nome, exc))
        return None


def mapa(nome, atributo):
    m = mod(nome)
    if m is None:
        return None
    v = getattr(m, atributo, None)
    if v is None:
        erro("scripts/%s.py nao expoe mais `%s` (renomeado?)" % (nome, atributo))
        return None
    return set(v)


# ── verificacoes ──────────────────────────────────────────────────────────────
def checa_index(ix):
    P = ix.get("P") or []
    vivos = [p for p in P if not p["etf"]]
    tickers = [p["t"] for p in P]
    dup = {t for t in tickers if tickers.count(t) > 1}
    if dup:
        erro("ticker duplicado em P: %s" % ", ".join(sorted(dup)))

    # setor que nao cai em nenhum bucket vira 'other' calado — o bug mais dificil de ver
    for p in vivos:
        if p["s"] and ix["BUCKET_SECTORS"] and p["s"] not in ix["BUCKET_SECTORS"]:
            erro("%s tem setor '%s', que nao esta em nenhum BUCKET — bucketOf() vai "
                 "silenciosamente jogar em 'other'" % (p["t"], p["s"]))
        for campo in ("d", "d2"):
            v = p[campo]
            if v and ix["DRIVERS"] and v not in ix["DRIVERS"]:
                erro("%s tem %s='%s', que nao existe em DRIVERS" % (p["t"], campo, v))
        if not p["d"]:
            erro("%s nao tem driver primario (campo d) — some da aba Exposure" % p["t"])

    conjunto = {p["t"] for p in P}
    for nome in ("ANALYSIS", "DEEPDIVE", "PEERS", "ETF_NOTES", "EARNINGS"):
        orfaos = ix.get(nome, set()) - conjunto
        if orfaos:
            erro("%s tem chave(s) que nao existem em P (nome removido?): %s"
                 % (nome, ", ".join(sorted(orfaos))))

    vt = {p["t"] for p in vivos}
    for nome, rotulo in (("EARNINGS", "data de resultado"), ("PEERS", "lista de peers")):
        faltam = vt - ix.get(nome, set())
        if faltam:
            aviso("sem %s: %s" % (rotulo, ", ".join(sorted(faltam))))
    faltam = vt - ix.get("ANALYSIS", set())
    if faltam:
        aviso("sem ficha ANALYSIS escrita: %s" % ", ".join(sorted(faltam)))

    ruins = [x for x in ix.get("DATAS_FICHA", []) if not re.match(r"^\d{4}-\d{2}$", x)]
    if ruins:
        erro("data de ficha fora do padrao ISO 'YYYY-MM': %s" % ", ".join(sorted(set(ruins))))
    return vt


def checa_coletores(vt):
    prices = mapa("fetch_prices", "SYMBOLS")
    estim  = mapa("fetch_estimates", "SYMBOLS")
    us     = mapa("fetch_us", "CFG")
    intl   = mapa("fetch_intl", "SYMBOLS")
    sa     = mapa("fetch_sa", "SYMBOLS")

    for nome, s in (("fetch_prices", prices), ("fetch_estimates", estim)):
        if s is None:
            continue
        faltam, sobram = vt - s, s - vt
        if faltam:
            erro("%s nao cobre: %s — o nome fica sem dado e nada avisa"
                 % (nome, ", ".join(sorted(faltam))))
        if sobram:
            aviso("%s tem ticker fora da cobertura: %s" % (nome, ", ".join(sorted(sobram))))

    if None not in (us, intl, sa):
        fund = us | intl | sa
        orfaos = vt - fund
        if orfaos:
            erro("sem nenhum coletor de fundamento (us/intl/sa): %s — os 4 graficos "
                 "ficam vazios" % ", ".join(sorted(orfaos)))
        dobrados = (us & intl) | (us & sa)
        if dobrados:
            aviso("em mais de um coletor de fundamento: %s (ok se for sobrescrita "
                  "proposital, como ASML e TSM)" % ", ".join(sorted(dobrados)))


def checa_workflow():
    if not os.path.exists(WORKFLOW):
        erro("nao encontrei .github/workflows/update.yml")
        return
    txt = io.open(WORKFLOW, encoding="utf-8").read()
    steps = re.findall(r"run_step\.py\s+(\S+)\s+(\S+)(.*)", txt)
    fontes_wf = [s[0] for s in steps]
    if not fontes_wf:
        erro("nenhum step do update.yml usa run_step.py — a telemetria de fontes "
             "nao esta ligada")
        return

    dups = {f for f in fontes_wf if fontes_wf.count(f) > 1}
    if dups:
        erro("fonte repetida no update.yml (uma sobrescreve a outra no _health.json): %s"
             % ", ".join(sorted(dups)))

    ch = mod("check_health")
    if ch is not None:
        esperadas = list(getattr(ch, "ESPERADAS", []))
        so_wf = set(fontes_wf) - set(esperadas)
        so_ch = set(esperadas) - set(fontes_wf)
        if so_wf:
            erro("fonte no update.yml e ausente de check_health.ESPERADAS "
                 "(roda mas nunca e cobrada): %s" % ", ".join(sorted(so_wf)))
        if so_ch:
            erro("fonte em check_health.ESPERADAS sem step no update.yml "
                 "(vai reprovar o job para sempre): %s" % ", ".join(sorted(so_ch)))

    # o --out declarado tem que ser um arquivo que o script realmente escreve
    for fonte, script, resto in steps:
        m = re.search(r"--out\s+(\S+)", resto)
        if not m:
            aviso("step '%s' sem --out: o run_step so vai olhar o codigo de saida" % fonte)
            continue
        declarado = os.path.basename(m.group(1))
        nome_mod = os.path.splitext(os.path.basename(script))[0]
        mm = mod(nome_mod)
        if mm is None:
            continue
        saidas = {os.path.basename(getattr(mm, a)) for a in ("OUT", "OUT_HIST")
                  if isinstance(getattr(mm, a, None), str)}
        if saidas and declarado not in saidas:
            erro("step '%s': --out aponta para %s, mas %s.py escreve em %s"
                 % (fonte, declarado, nome_mod, " / ".join(sorted(saidas))))


def main():
    print("Autoteste de cadastro — %s\n" % os.path.basename(ROOT))
    ix = ler_index()
    if ix.get("P"):
        vivos = [p for p in ix["P"] if not p["etf"]]
        print("index.html: %d nomes (%d com ficha, %d drivers, %d setores em buckets)"
              % (len(vivos), len(ix["ANALYSIS"]), len(ix["DRIVERS"]), len(ix["BUCKET_SECTORS"])))
        vt = checa_index(ix)
        checa_coletores(vt)
    checa_workflow()

    print()
    for a in AVISOS:
        print("AVISO  " + a)
    for e in ERROS:
        print("ERRO   " + e)
    print()
    if ERROS:
        print("REPROVADO: %d erro(s), %d aviso(s)." % (len(ERROS), len(AVISOS)))
        return 1
    print("OK: nenhum erro de cadastro%s."
          % (" (%d aviso[s] — nao reprovam)" % len(AVISOS) if AVISOS else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reprova o job do Actions quando alguma fonte do dashboard esta quebrada.

Roda como ULTIMO step do workflow, DEPOIS do commit -- assim o `_health.json`
com o diagnostico ja esta no repo (e ja chegou no banner do dashboard) antes de
o job ficar vermelho. Job vermelho faz o proprio GitHub mandar e-mail para o
dono do repo, o que resolve a notificacao sem depender de nenhuma API paga.

Criterio de reprovacao, por fonte:
  - nunca teve sucesso registrado;              -> reprova
  - ultimo sucesso mais velho que `max_age_h`;  -> reprova
  - status `fail` na execucao de hoje.          -> reprova
`warn` (rodou, mas nao reescreveu a saida) apenas aparece no relatorio.

Fontes internas: coletores agregadores (papers, news) reportam contagem por
feed via `HEALTH_SRC`. Uma fonte interna vazia vira AVISO -- feed lento pode
legitimamente nao ter novidade. Mas se MAIS DA METADE das fontes internas de um
coletor nao retornou nada, isso nao e' feed lento, e' quebra: reprova.

`--soft` imprime o relatorio e sai 0 -- util para rodar na mao sem quebrar nada.
"""

import argparse
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
HEALTH = os.path.join(ROOT, "data", "_health.json")

# Fontes que o dashboard espera encontrar. Uma fonte ausente do JSON conta como
# falha: significa que o step nem chegou a rodar.
ESPERADAS = [
    "us", "intl", "asml", "sa", "prices", "estimates",
    "transcripts", "news", "papers", "letters", "insiders",
]


def horas(iso, agora):
    if not iso:
        return None
    try:
        d = datetime.datetime.fromisoformat(iso)
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=datetime.timezone.utc)
    return (agora - d).total_seconds() / 3600.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--soft", action="store_true", help="nunca reprova; so relata")
    args = ap.parse_args()

    agora = datetime.datetime.now(datetime.timezone.utc)
    try:
        with open(HEALTH, encoding="utf-8") as fh:
            state = json.load(fh)
    except Exception as exc:                                   # noqa: BLE001
        print("ERRO: nao consegui ler data/_health.json (%s)" % exc)
        print("Nenhum coletor reportou -- o workflow provavelmente nem chegou a rodar.")
        return 0 if args.soft else 1

    ruins, fracas = [], []
    print("%-12s %-6s %-10s %-8s %s" % ("FONTE", "STATUS", "ULT. OK", "REG.", "OBS"))
    print("-" * 74)
    for src in ESPERADAS:
        e = state.get(src)
        if not e:
            print("%-12s %-6s %-10s %-8s %s" % (src, "AUSENTE", "-", "-", "step nao rodou"))
            ruins.append("%s: ausente do _health.json" % src)
            continue
        idade = horas(e.get("last_ok"), agora)
        teto = e.get("max_age_h") or 36
        idade_txt = "-" if idade is None else "%.0fh" % idade
        obs = e.get("erro") or ""
        print("%-12s %-6s %-10s %-8s %s"
              % (src, (e.get("status") or "?").upper(), idade_txt,
                 "-" if e.get("n") is None else e["n"], obs[:32]))
        # granularidade por fonte interna
        f = e.get("fontes")
        if isinstance(f, dict):
            nomeadas = {k: v for k, v in f.items() if not k.startswith("_")}
            mortas = [k for k, v in nomeadas.items()
                      if isinstance(v, (int, float)) and v <= 0]
            if nomeadas and mortas:
                linha = "%s: %d de %d fontes internas sem retorno (%s)" % (
                    src, len(mortas), len(nomeadas), ", ".join(sorted(mortas)))
                if len(mortas) * 2 > len(nomeadas):
                    ruins.append(linha + " — maioria caiu, nao e feed lento")
                else:
                    fracas.append(linha)
            erro_int = f.get("_erro")
            if isinstance(erro_int, (int, float)) and erro_int:
                fracas.append("%s: %d de %s fontes deram erro"
                              % (src, int(erro_int), f.get("_fontes", "?")))

        if e.get("status") == "fail":
            ruins.append("%s: falhou hoje (%s)" % (src, obs[:120]))
        elif idade is None:
            ruins.append("%s: nunca teve sucesso registrado" % src)
        elif idade > teto:
            ruins.append("%s: ultimo sucesso ha %.0fh (teto %dh)" % (src, idade, teto))

    print("-" * 74)
    if fracas:
        print("FONTES INTERNAS SEM RETORNO (nao reprovam):")
        for f in fracas:
            print("  ~ " + f)
        print()
    if not ruins:
        print("OK -- todas as %d fontes dentro do prazo%s."
              % (len(ESPERADAS), " (com ressalvas acima)" if fracas else ""))
        return 0

    print("FONTES COM PROBLEMA (%d):" % len(ruins))
    for r in ruins:
        print("  - " + r)
    if args.soft:
        return 0
    print("\nReprovando o job para gerar notificacao. Os dados bons ja foram commitados;")
    print("o banner do dashboard ja mostra qual fonte esta velha.")
    return 1


if __name__ == "__main__":
    sys.exit(main())

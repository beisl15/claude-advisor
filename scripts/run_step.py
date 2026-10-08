#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Executa um coletor e registra o veredito em data/_health.json.

Motivacao
---------
Todo step do workflow roda com `continue-on-error: true`. Sem isso, um RSS fora
do ar derruba o job inteiro -- pior. O efeito colateral, porem, era que uma
fonte quebrada falhava em SILENCIO: o dashboard continuava exibindo o dado da
semana passada com a mesma confianca do dado de hoje.

Este wrapper resolve sem tocar em nenhum coletor. Roda o script como
subprocesso e cruza duas evidencias independentes:

  1. codigo de saida do processo;
  2. o arquivo de saida foi de fato reescrito DURANTE esta execucao.

A evidencia (2) importa porque quatro coletores gravam no mesmo `data/fin.json`
(us / intl / ir_asml / sa). Comparar o mtime contra o instante em que ESTE step
comecou -- e nao contra "hoje" -- distingue quem realmente escreveu de quem
apenas herdou o arquivo do step anterior.

Estados
-------
  ok    codigo 0 e arquivo de saida reescrito
  warn  codigo 0 mas o arquivo nao mudou (fonte pode ter devolvido vazio)
  fail  codigo != 0

Uso
---
  python scripts/run_step.py <fonte> <script.py> [--out data/fin.json]
                             [--min-bytes 500] [--max-age-h 36]
                             [--label "Texto exibido no dashboard"]

Duas convencoes opcionais de saida, que nenhum coletor precisa adotar para o
wrapper funcionar:

  HEALTH_N=<int>        quantos registros o script gravou
  HEALTH_SRC=<json>     contagem POR FONTE INTERNA, ex.:
                        {"NBER": 12, "BIS": 0, "IMF": -1}
                        (-1 = a fonte deu erro; 0 = respondeu vazio)

A segunda existe porque codigo de saida e' granularidade grossa demais para
coletores agregadores: o fetch_papers junta 6 feeds e o fetch_news junta ~59.
Ambos saem com 0 e escrevem o arquivo mesmo trazendo metade das fontes -- foi
exatamente assim que o papers.json ficou sem NBER, BIS e IMF sem ninguem notar.

Sai SEMPRE com codigo 0 -- quem reprova o job e o check_health.py, no fim.
"""

import argparse
import datetime
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
HEALTH = os.path.join(ROOT, "data", "_health.json")


def _now():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)


def load_health():
    try:
        with open(HEALTH, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_health(state):
    os.makedirs(os.path.dirname(HEALTH), exist_ok=True)
    tmp = HEALTH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, HEALTH)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source", help="chave estavel da fonte (ex: us, news, insiders)")
    ap.add_argument("script", help="caminho do coletor a executar")
    ap.add_argument("--out", default="", help="arquivo que o coletor deveria reescrever")
    ap.add_argument("--min-bytes", type=int, default=200)
    ap.add_argument("--max-age-h", type=int, default=36,
                    help="idade maxima tolerada do ultimo sucesso, em horas")
    ap.add_argument("--label", default="", help="rotulo legivel para o banner")
    ap.add_argument("--timeout", type=int, default=1800)
    args = ap.parse_args()

    script = args.script if os.path.isabs(args.script) else os.path.join(ROOT, args.script)
    out = ""
    if args.out:
        out = args.out if os.path.isabs(args.out) else os.path.join(ROOT, args.out)

    started = _now()
    started_mono = started.timestamp()

    print("=" * 62)
    print("[run_step] fonte=%s script=%s" % (args.source, args.script))
    print("=" * 62)
    sys.stdout.flush()

    rc, stdout, stderr = 0, "", ""
    try:
        proc = subprocess.run(
            [sys.executable, script],
            cwd=ROOT, capture_output=True, text=True, timeout=args.timeout,
        )
        rc, stdout, stderr = proc.returncode, proc.stdout or "", proc.stderr or ""
    except subprocess.TimeoutExpired:
        rc, stderr = 124, "timeout apos %ds" % args.timeout
    except Exception as exc:                                   # noqa: BLE001
        rc, stderr = 1, "%s: %s" % (type(exc).__name__, exc)

    # Repassa a saida do coletor para o log do Actions -- o wrapper nao engole nada.
    if stdout:
        sys.stdout.write(stdout if stdout.endswith("\n") else stdout + "\n")
    if stderr:
        sys.stderr.write(stderr if stderr.endswith("\n") else stderr + "\n")
    sys.stdout.flush()

    # ---- evidencia 2: o arquivo de saida mudou durante ESTA execucao? ----------
    wrote, size = None, None
    if out:
        try:
            st = os.stat(out)
            size = st.st_size
            # 2s de folga para relogio de sistema de arquivos de baixa resolucao
            wrote = (st.st_mtime >= started_mono - 2) and (size >= args.min_bytes)
        except FileNotFoundError:
            wrote, size = False, 0

    if rc != 0:
        status = "fail"
        erro = (stderr.strip().splitlines() or ["codigo de saida %d" % rc])[-1]
    elif wrote is False:
        status = "warn"
        erro = ("saida nao reescrita (%s, %s bytes)"
                % (os.path.basename(out), size if size is not None else "?"))
    else:
        status = "ok"
        erro = ""

    n, m = None, None
    for m in re.finditer(r"^HEALTH_N=(\d+)\s*$", stdout, re.M):
        pass
    if m:
        n = int(m.group(1))

    fontes, ms = None, None
    for ms in re.finditer(r"^HEALTH_SRC=(\{.*\})\s*$", stdout, re.M):
        pass
    if ms:
        try:
            v = json.loads(ms.group(1))
            if isinstance(v, dict):
                fontes = v
        except ValueError:
            pass

    now = _now()
    state = load_health()
    prev = state.get(args.source, {})
    state[args.source] = {
        "source": args.source,
        "label": args.label or args.source,
        "status": status,
        "erro": erro[:300],
        "n": n,
        "fontes": fontes,
        "bytes": size,
        "ts": now.isoformat(),
        # o ultimo sucesso sobrevive a uma falha: e ele que o banner mede
        "last_ok": now.isoformat() if status == "ok" else prev.get("last_ok"),
        "max_age_h": args.max_age_h,
        "dur_s": round((now - started).total_seconds(), 1),
    }
    save_health(state)

    print("[run_step] %s -> %s%s" % (args.source, status.upper(), (" | " + erro) if erro else ""))
    if fontes:
        mortas = [k for k, v in fontes.items()
                  if not k.startswith("_") and isinstance(v, (int, float)) and v <= 0]
        print("[run_step] %s: %d fontes internas%s"
              % (args.source, len([k for k in fontes if not k.startswith("_")]),
                 (", sem retorno: " + ", ".join(sorted(mortas))) if mortas else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())

# Coletores desativados

Scripts aposentados em **17/08/2026**, quando a cobertura passou a ser 100%
internacional e os 10 nomes da B3 (SMFT3, PRIO3, SBSP3, PETR3, PETR4, ITUB4,
BPAC11, VIVT3, TIMS3, ABEV3) sairam do universo.

| Arquivo | O que fazia | Saida |
|---|---|---|
| `fetch_br.py` | Fundamentos B3 direto da CVM (ZIPs de ITR/DFP, DRE/balanco consolidados) | `data/br.json` |
| `fetch_cvm.py` | Serie trimestral de 17 trimestres das 10 brasileiras (ITR/DFP, com fallback `_ind` para a TIM, que publica o consolidado zerado) | `data/fin.json` (entradas BR) |

Ambos rodavam como steps do `.github/workflows/update.yml` e foram removidos de la.
Para restaurar: mover de volta para `scripts/`, re-adicionar os dois steps no
workflow e devolver os tickers a `P`, `EARNINGS`, `PEERS` e `fetch_prices.py`.

Os arquivos `data/br.json` e as entradas brasileiras de `data/fin.json` param de
ser atualizados, mas nao sao apagados pelo workflow — o front simplesmente nao
os le mais.

# Cobertura descontinuada

Fichas de research de nomes que sairam do universo ativo. Nada aqui e gerado por
script: e texto escrito a mao. Arquivado em vez de deletado porque reativar um
nome custa uma linha de codigo, mas reescrever a ficha custa horas.

| Ticker | Nome | Setor | Removido em | Motivo |
|---|---|---|---|---|
| [VALE3](VALE3.md) | Vale S.A. | Mineracao | 2026-07-28 | corte de universo |
| [TOTS3](TOTS3.md) | TOTVS | Software BR | 2026-07-28 | corte de universo |
| [CSMG3](CSMG3.md) | COPASA | Saneamento | 2026-07-28 | corte de universo |

## Como reativar um nome

1. Devolver a entrada em `index.html` -> `const P` (o bloco esta no fim de cada ficha).
2. Devolver os blocos `ANALYSIS` / `ETF_NOTES`, `FIN`, `EARNINGS` e `PEERS`.
3. Adicionar o ticker de volta em `scripts/fetch_br.py` (NAMES), `fetch_prices.py`
   (SYMBOLS), `fetch_insiders.py` (BR_NAMES) e, se fizer sentido, no feed de
   `fetch_news.py`.
4. Recolocar no `GROUPS.brazil.tickers` do `index.html`.

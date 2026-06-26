# Research Portal — versão hospedada (GitHub Pages + Actions)

Dashboard estático no **GitHub Pages** com dados atualizados por uma rotina agendada
(**GitHub Actions**) que grava `data/*.json`. A página lê esses JSON (mesma origem → sem CORS).
Sem servidor, de graça.

## Fontes (tudo da fonte oficial onde possível)
| Dado | Fonte | Script | Saída |
|---|---|---|---|
| Fundamentos US (17 tri ≈ 3 anos) | **SEC EDGAR** (10-Q/10-K XBRL) — inclui telecom VZ/TMUS/T | `fetch_us.py` | `data/fin.json` |
| Fundamentos estrangeiras (ASML/TSM/RACE/ABI/NU) | **Yahoo fundamentals timeseries** (foreign issuers só têm 20-F anual na SEC); IR do país como referência | `fetch_intl.py` | merge em `data/fin.json` |
| Fundamentos Brasil | **CVM** (ITR/DFP, direto) | `fetch_br.py` | `data/br.json` |
| Cotação + P/E ao vivo | **Yahoo Finance** (v8/chart); P/E = preço ÷ LPA 12m (SEC) | `fetch_prices.py` | `data/prices.json` |
| Release de resultados | **SEC 8-K** (item 2.02) + link de RI | `fetch_transcripts.py` | `data/transcripts.json` |
| Notícias (RSS, por região) | **BR**: Brazil Journal, InfoMoney, Money Times · **US**: CNBC, MarketWatch · **Mundo**: Investing.com, Reuters (Google News) (+ IA opcional) | `fetch_news.py` | `data/news.json` |

O `index.html` busca esses arquivos ao abrir; se não existirem (1ª vez ou aberto como arquivo
local), usa os dados embutidos como fallback — nunca quebra.

## Deploy (uma vez, ~5 min)
1. Crie um repositório no GitHub (ex.: `claude-advisor`), público.
2. Suba os arquivos desta pasta `site/` para a raiz. Copie seu `dashboard.html` para a raiz **como `index.html`**.
3. Settings → Actions → General → *Workflow permissions* → **Read and write** → Save.
4. Settings → Pages → Source **Deploy from a branch** → **main / (root)** → Save.
5. Aba **Actions** → "Atualiza dados do dashboard" → **Run workflow** (gera os `data/*.json`).
6. Abra `https://SEU_USUARIO.github.io/claude-advisor/`.

Depois, o cron roda **todo dia 09:00 UTC**.

## Notícias com IA (opcional, recomendado)
Para a curadoria inteligente (a IA escolhe as mais relevantes e escreve resumo + "provocação"):
- Settings → Secrets and variables → Actions → **New repository secret**
- Nome: `ANTHROPIC_API_KEY` · Valor: sua chave da API Anthropic.
Sem a chave, as notícias caem no ranqueamento por palavra-chave (ainda multi-fonte).

## Expandir Brasil
Edite `NAMES` em `scripts/fetch_br.py` (casa pelo nome em DENOM_CIA da CVM), ex.:
`"PETR4":"PETROLEO BRASILEIRO", "VALE3":"VALE S.A", "ITUB4":"ITAU UNIBANCO"`.
Para cotação/P-E desses, acrescente em `SYMBOLS` no `fetch_prices.py`.

## O que NÃO dá (e por quê)
- **Transcrição falada completa da call:** não existe gratuita na fonte (fica em provedores pagos).
  Entregamos o **release oficial (SEC 8-K)** + link de **RI/webcast** — o mais perto da fonte.
- **Seeking Alpha / Bloomberg / WSJ / Financial Times:** exigem login/paywall; a rotina na nuvem não tem sessão e os sites bloqueiam robôs. Entram no dashboard só como **atalhos de leitura manual** (campo `manual` no `news.json`), nunca coletados.
- **Twitter/X:** API é paga e exige conta/credencial — fora do que a automação pode fazer.
- **Reuters:** descontinuou o RSS público; cobrimos os wires da Reuters via Investing.com e via Google News.
- **Yahoo (preço):** o `v8/chart` dá só cotação; P/E é calculado (preço ÷ LPA 12m da SEC). A API de
  fundamentos via `quoteSummary` exige "crumb"/cookie e é frágil — por isso o fundamento das US/BR
  vem de SEC/CVM.

## Limitações honestas
- IPs de datacenter (Actions) podem ser limitados ocasionalmente por alguma fonte; o workflow usa
  `continue-on-error`, mantendo o último dado válido.
- O parser da CVM é best-effort; valide no 1º "Run workflow" (os logs mostram cada ticker).
- **Estrangeiras (`fetch_intl.py`):** usa o `fundamentals-timeseries` do Yahoo (mais estável que o
  `quoteSummary`, sem crumb). Cobertura trimestral pode ser irregular e a moeda é a do reporte
  (ASML/RACE em €, TSM em NT$, ABI/NU em US$). Valide contra o IR do país; se o Yahoo falhar para um
  nome, o último dado válido é mantido.

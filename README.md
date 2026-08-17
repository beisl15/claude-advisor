# Research Portal — versão hospedada (GitHub Pages + Actions)

Dashboard estático no **GitHub Pages** com dados atualizados por uma rotina agendada
(**GitHub Actions**) que grava `data/*.json`. A página lê esses JSON (mesma origem → sem CORS).
Sem servidor, de graça.

## Fontes (tudo da fonte oficial onde possível)
| Dado | Fonte | Script | Saída |
|---|---|---|---|
| Fundamentos US (17 tri ≈ 3 anos) | **SEC EDGAR** (10-Q/10-K XBRL) — inclui telecom VZ/TMUS/T | `fetch_us.py` | `data/fin.json` |
| Fundamentos estrangeiras (ASML/TSM/RACE/ABI/NU) | **Yahoo fundamentals timeseries** (foreign issuers só têm 20-F anual na SEC); IR do país como referência | `fetch_intl.py` | merge em `data/fin.json` |
| Cotação + P/E ao vivo | **Yahoo Finance** (v8/chart); P/E = preço ÷ LPA 12m (SEC) | `fetch_prices.py` | `data/prices.json` |
| Release de resultados | **SEC 8-K** (item 2.02) + link de RI | `fetch_transcripts.py` | `data/transcripts.json` |
| Série longa ASML | **RI oficial** (XLSX por trimestre) | `fetch_ir_asml.py` | merge em `data/fin.json` |
| Série longa TSM/RACE/ABI/ROXO | **stockanalysis.com** (20 tri) | `fetch_sa.py` | merge em `data/fin.json` |
| Notícias (RSS, 3 regiões) | **US**: CNBC, MarketWatch, Yahoo, Barron's, SemiAnalysis, Stratechery · **EU**: Euronews Business, Reuters/FT/Bloomberg Europe, Economist · **ASIA**: Nikkei Asia, Investing.com, Reuters Asia, SCMP, Japan Times (+ GDELT nas três) | `fetch_news.py` | `data/news.json` |
| Insider activity | **SEC Form 4** (90d, códigos P/S) | `fetch_insiders.py` | `data/insiders.json` |

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

## Adicionar um nome
1. `index.html`: entrada em `P` (o `s:` precisa existir em `SECTOR_PT` **e** em algum
   `BUCKETS[].sectors`, senão o nome cai no bucket `other`), mais `EARNINGS` e `PEERS`.
2. `fetch_us.py` + `fetch_insiders.py` + `fetch_transcripts.py`: o CIK — **valide antes**
   (ver abaixo). Estrangeira sem 10-Q vai para `fetch_intl.py` / `fetch_sa.py`.
3. `fetch_prices.py`: o símbolo no Yahoo.
4. `fetch_news.py`: uma linha em `COMPANY_FEEDS` e, se fizer sentido, uma regra em `RULES`.
5. O caro é a ficha `ANALYSIS` (6 parágrafos escritos à mão). O front degrada bem
   (`if (ANALYSIS[p.t])`), mas nome novo entra com ficha vazia.

As regiões de notícia vivem em **uma** constante: `REGIONS = ("US", "EU", "ASIA")` no
`fetch_news.py`. Nunca repita a lista literal em outro lugar — era exatamente isso que
fazia uma troca de região quebrar o funil em silêncio.

## Validar antes de ingerir (`test.yml`)
CIK errado **não gera erro**: o `companyconcept` responde 200 com o balanço de outra
empresa e o dado entra silenciosamente no dashboard. Antes de adicionar qualquer nome US:

- Aba **Actions** → "Teste isolado de script" → **Run workflow** → `validate_ciks.py`.
- O job confronta cada CIK contra o índice oficial da SEC (`company_tickers.json`),
  reporta o fim do ano fiscal e lista quais tags XBRL existem de fato para o ticker.
- Sai com erro se qualquer CIK divergir. O relatório fica no *artifact*
  `resultado-validate_ciks.py` (`_validation_ciks.json`) e no resumo do job.

O mesmo workflow roda qualquer `fetch_*.py` isolado e publica o JSON gerado como
artifact — sem commitar, a menos que você marque a opção `commit`. Serve para testar
fontes que a sandbox local bloqueia (SEC, Yahoo, FINRA).

## Cobertura descontinuada
Nomes que saíram do universo têm a ficha de research preservada em
`archive/deprecated_coverage/` (VALE3, TOTS3, CSMG3 em 28/07/2026; os 10 nomes da B3 em
`BR_2026-08-17.md`). Reativar é devolver os blocos listados em cada `.md`. Os coletores
aposentados (`fetch_br.py`, `fetch_cvm.py`) estão em `archive/deprecated_scripts/`.

## O que NÃO dá (e por quê)
- **Transcrição falada completa da call:** não existe gratuita na fonte (fica em provedores pagos).
  Entregamos o **release oficial (SEC 8-K)** + link de **RI/webcast** — o mais perto da fonte.
- **Seeking Alpha / Bloomberg / WSJ / Financial Times:** exigem login/paywall; a rotina na nuvem não tem sessão e os sites bloqueiam robôs. Entram no dashboard só como **atalhos de leitura manual** (campo `manual` no `news.json`), nunca coletados.
- **Twitter/X:** API é paga e exige conta/credencial — fora do que a automação pode fazer.
- **Reuters:** descontinuou o RSS público; cobrimos os wires da Reuters via Investing.com e via Google News.
- **Yahoo (preço):** o `v8/chart` dá só cotação; P/E é calculado (preço ÷ LPA 12m da SEC). A API de
  fundamentos via `quoteSummary` exige "crumb"/cookie e é frágil — por isso o fundamento das US
  vem da SEC.
- **SCMP e Channel News Asia:** devolvem **403 para bot** no RSS direto. Entram via
  `gnews("site:...")`, o mesmo padrão já usado para WSJ e Barron's.

## Limitações honestas
- IPs de datacenter (Actions) podem ser limitados ocasionalmente por alguma fonte; o workflow usa
  `continue-on-error`, mantendo o último dado válido.
- ⚠️ **Todo step usa `continue-on-error: true`** — uma fonte que quebra falha em silêncio e o
  dashboard segue exibindo o JSON do dia anterior como se fosse de hoje. Confira os logs do job,
  ou implemente o banner de "última atualização por fonte" (pendência da Fase 4).
- **Estrangeiras (`fetch_intl.py`):** usa o `fundamentals-timeseries` do Yahoo (mais estável que o
  `quoteSummary`, sem crumb). Cobertura trimestral pode ser irregular e a moeda é a do reporte
  (ASML/RACE em €, TSM em NT$, ABI/NU em US$). Valide contra o IR do país; se o Yahoo falhar para um
  nome, o último dado válido é mantido.

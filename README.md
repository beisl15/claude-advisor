# Research Portal — versão hospedada (GitHub Pages + Actions)

Dashboard estático no **GitHub Pages** com dados atualizados por uma rotina agendada
(**GitHub Actions**) que grava `data/*.json`. A página lê esses JSON (mesma origem → sem CORS).
Sem servidor, de graça, sem nenhuma chave de API paga.

Cobertura **100% internacional** desde 17/08/2026: 28 nomes, organizados por bucket setorial
(Software & Platforms · Semis & Compute · Power & Infrastructure · Financials & Fintech ·
Consumer, Telecom & LatAm) e, em paralelo, por **driver econômico** (aba Exposure).

## Fontes (tudo da fonte oficial onde possível)

| Dado | Fonte | Script | Saída |
|---|---|---|---|
| Fundamentos US (17 tri ≈ 4 anos) | **SEC EDGAR** (10-Q/10-K XBRL) | `fetch_us.py` | `data/fin.json` |
| Fundamentos estrangeiras (ASML/TSM/RACE/ABI/NU) | **Yahoo fundamentals timeseries** (foreign issuers só têm 20-F anual na SEC) | `fetch_intl.py` | merge em `data/fin.json` |
| Série longa ASML | **RI oficial** (XLSX por trimestre) | `fetch_ir_asml.py` | merge em `data/fin.json` |
| Série longa TSM/RACE/ABI/ROXO | **stockanalysis.com** (20 tri) | `fetch_sa.py` | merge em `data/fin.json` |
| Cotação + P/E ao vivo | **Yahoo Finance** (v8/chart); P/E = preço ÷ LPA 12m (SEC) | `fetch_prices.py` | `data/prices.json` |
| Série diária de preço (5 anos) | **Yahoo** `chart?range=5y`, backfill na 1ª execução | `fetch_prices.py` | `data/px_hist.json` |
| **Consenso de mercado** | **stockanalysis.com** `/forecast/` — projeção anual, preço-alvo, dispersão, ratings de 6 meses | `fetch_estimates.py` | `data/estimates.json` |
| Release de resultados | **SEC 8-K** (item 2.02) + link de RI | `fetch_transcripts.py` | `data/transcripts.json` |
| Notícias (RSS, 3 regiões) | ~59 fontes US / EU / ASIA + GDELT | `fetch_news.py` | `data/news.json` |
| Papers de research | NBER, BIS, IMF, Fed (FEDS), arXiv q-fin, arXiv cs.AI | `fetch_papers.py` | `data/papers.json` |
| Cartas de gestoras | monitor incremental de páginas + RSS | `fetch_letters.py` | `data/letters.json` |
| Insider activity | **SEC Form 4** (90d, códigos P/S) | `fetch_insiders.py` | `data/insiders.json` |
| **Telemetria dos coletores** | gerado pelo próprio wrapper | `run_step.py` | `data/_health.json` |

O `index.html` busca esses arquivos ao abrir; se não existirem (1ª vez ou aberto como arquivo
local), usa os dados embutidos como fallback — nunca quebra.

## Fim da falha silenciosa

Todo step do workflow roda com `continue-on-error: true` — e **continua rodando**: sem isso, um
RSS fora do ar derruba o job inteiro, o que é pior. O que mudou é que agora existe testemunha.

Cada coletor roda por **`scripts/run_step.py`**, que cruza duas evidências independentes e grava
o veredito em `data/_health.json`:

1. código de saída do processo;
2. o arquivo de saída foi de fato reescrito **durante aquele step**.

A evidência (2) importa porque quatro coletores gravam no mesmo `data/fin.json`. Comparar o mtime
contra o instante em que o step começou — e não contra "hoje" — distingue quem realmente escreveu
de quem só herdou o arquivo do step anterior.

Estados: `ok` (saiu 0 e reescreveu) · `warn` (saiu 0 e não reescreveu) · `fail` (saiu ≠ 0).

**Fontes internas.** Código de saída é granularidade grossa demais para coletores agregadores:
`fetch_papers.py` junta 6 feeds e `fetch_news.py` junta ~59. Ambos saem com 0 e escrevem o
arquivo mesmo trazendo metade — foi assim que o `papers.json` ficou sem NBER, BIS e IMF sem
ninguém notar. Os dois passaram a imprimir uma linha `HEALTH_SRC={...}` com a contagem por feed,
que o `run_step.py` captura. Fonte interna vazia vira aviso; **maioria** das fontes internas caída
reprova o job.

**`scripts/check_health.py`** é o último step e o único **sem** `continue-on-error`. Roda **depois
do commit**, de propósito: o diagnóstico já está no repo e no banner do dashboard antes de o job
ficar vermelho. Job vermelho faz o próprio GitHub mandar e-mail — notificação sem API.

No dashboard isso aparece como uma tira de chips abaixo do título: verde dentro do prazo, amarelo
a partir de 75% do teto, vermelho vencido. Tetos: 36h para tudo, 96h para `letters`.

Para rodar o diagnóstico na mão, sem reprovar nada: `python scripts/check_health.py --soft`.

## Autoteste de cadastro (`selftest.py`)

O `validate_ciks.py` cuida do risco de **dado** errado. O `selftest.py` cuida do risco irmão:
**cadastro incompleto também não gera erro**. Ele roda offline, em segundos, e confere:

- todo ticker de `P` existe nos mapas de `fetch_prices` e `fetch_estimates`, e em ao menos um
  coletor de fundamento (`us` / `intl` / `sa`);
- nenhuma chave órfã em `ANALYSIS`, `DEEPDIVE`, `PEERS`, `ETF_NOTES`, `EARNINGS`;
- todo `d`/`d2` existe em `DRIVERS` e todo setor cai em algum `BUCKETS[].sectors` — hoje
  `bucketOf()` joga em `other` calado, então um setor com typo some da leitura;
- datas de ficha em ISO `YYYY-MM`;
- as fontes declaradas no `update.yml` batem com `check_health.ESPERADAS`;
- cada `--out` aponta para um arquivo que o script realmente escreve.

Roda a cada push pelo workflow **"Autoteste de cadastro"**. Sai com código 1 em erro; aviso não
reprova. Antes de qualquer push: `python scripts/selftest.py`.

## As abas

| Aba | O que responde |
|---|---|
| Market Intelligence | notícias US/EU/ASIA, papers e cartas de gestoras |
| Fundamentals | ficha por empresa: 5 seções do framework, 4 gráficos, drivers, horizonte, regulação, peers, **Valuation** |
| **Exposure** | exposição por **driver econômico**, não por setor — e a matriz driver × bucket |
| Earnings Calendar | datas de resultado da cobertura |
| Macro Agenda | decisões de banco central e divulgações |
| Insider Activity | Form 4 dos últimos 90 dias |

**Por que a aba Exposure existe:** o bucket setorial organiza a leitura, não mede risco. Somando
driver primário e secundário, **18 dos 28 nomes tocam o mesmo ciclo de IA**, espalhados por três
buckets — o que faz o livro *parecer* diversificado na aba Fundamentals. A matriz driver × bucket
seria diagonal se as duas taxonomias coincidissem; cada célula fora da diagonal é um lugar onde o
setor engana sobre o risco.

**A aba Valuation** traz: forward P/E contra a **própria** história (mesma fonte dos dois lados —
P/E montado a mão quebra em quem fez split), consenso com dispersão alto–baixo, preço-alvo,
postura do sell-side, **DCF reverso** com sliders (o crescimento de FCF que o preço já cobra) e
**cenários bull/base/bear manuais**, salvos no navegador. O DCF reverso se esconde de propósito —
e diz o porquê — para bancos (FCF não é a métrica), para quem não reporta em USD (ASML/RACE/TSM:
projeção em EUR/TWD contra preço do ADR em dólar) e quando não há FCF de consenso.

## Deploy (uma vez, ~5 min)

1. Crie um repositório no GitHub (ex.: `claude-advisor`), público.
2. Suba os arquivos desta pasta para a raiz, **preservando as pastas** `scripts/` e `.github/`.
3. Settings → Actions → General → *Workflow permissions* → **Read and write** → Save.
4. Settings → Pages → Source **Deploy from a branch** → **main / (root)** → Save.
5. Aba **Actions** → "Atualiza dados do dashboard" → **Run workflow** (gera os `data/*.json`).
6. Abra `https://SEU_USUARIO.github.io/claude-advisor/`.

Depois, o cron roda **todo dia 09:00 UTC** (~06:00 BRT).

> Na primeira execução o step de cotações demora bem mais que o normal: é o backfill de 5 anos de
> preço dos 28 nomes, que acontece uma vez só.

## Notícias com IA (opcional)

Para a curadoria inteligente (a IA escolhe as mais relevantes e escreve resumo + "provocação"):
Settings → Secrets and variables → Actions → **New repository secret** → nome `ANTHROPIC_API_KEY`.
Sem a chave, as notícias caem no ranqueamento por palavra-chave (ainda multi-fonte).

## Adicionar um nome

1. `index.html`: entrada em `P` — o `s:` precisa existir em `SECTOR_PT` **e** em algum
   `BUCKETS[].sectors`, e o `d:` (driver primário, mais `d2:` opcional) precisa existir em
   `DRIVERS`. Depois `EARNINGS` e `PEERS`.
2. `fetch_us.py` + `fetch_insiders.py` + `fetch_transcripts.py`: o CIK — **valide antes**
   (ver abaixo). Estrangeira sem 10-Q vai para `fetch_intl.py` / `fetch_sa.py`.
3. `fetch_prices.py` e `fetch_estimates.py`: o símbolo (Yahoo e stockanalysis).
4. `fetch_news.py`: uma linha em `COMPANY_FEEDS` e, se fizer sentido, uma regra em `RULES`.
5. **Rode `python scripts/selftest.py`** — ele reclama de cada um dos passos acima que faltar.
6. O caro é a ficha `ANALYSIS` (5 seções escritas à mão) e os cenários da aba Valuation. O front
   degrada bem: nome sem ficha ainda mostra resumo, consenso e cenários, com aviso explícito.

As regiões de notícia vivem em **uma** constante: `REGIONS = ("US", "EU", "ASIA")` no
`fetch_news.py`. Nunca repita a lista literal em outro lugar — era exatamente isso que fazia uma
troca de região quebrar o funil em silêncio.

## Validar antes de ingerir (`test.yml`)

CIK errado **não gera erro**: o `companyconcept` responde 200 com o balanço de outra empresa e o
dado entra silenciosamente no dashboard. Antes de adicionar qualquer nome US:

- Aba **Actions** → "Teste isolado de script" → **Run workflow** → `validate_ciks.py`.
- O job confronta cada CIK contra o índice oficial da SEC (`company_tickers.json`), reporta o fim
  do ano fiscal e lista quais tags XBRL existem de fato para o ticker.
- Sai com erro se qualquer CIK divergir. O relatório fica no artifact `resultado-validate_ciks.py`.

O mesmo workflow roda qualquer script isolado (incluindo `selftest.py` e `check_health.py`) e
publica o JSON gerado como artifact — sem commitar, a menos que você marque `commit`. Serve para
testar fontes que a sandbox local bloqueia (SEC, Yahoo, stockanalysis).

## Cobertura descontinuada

Nomes que saíram do universo têm a ficha de research preservada em `archive/deprecated_coverage/`
(VALE3, TOTS3, CSMG3 em 28/07/2026; os 10 nomes da B3 em `BR_2026-08-17.md`). Reativar é devolver
os blocos listados em cada `.md`. Os coletores aposentados (`fetch_br.py`, `fetch_cvm.py`) estão em
`archive/deprecated_scripts/`.

## O que NÃO dá (e por quê)

- **Transcrição falada completa da call:** não existe gratuita na fonte. Entregamos o **release
  oficial (SEC 8-K)** + link de **RI/webcast** — o mais perto da fonte.
- **Seeking Alpha / Bloomberg / WSJ / FT:** login/paywall; a rotina na nuvem não tem sessão. Entram
  só como atalhos de leitura manual (campo `manual` no `news.json`), nunca coletados.
- **Twitter/X:** API paga.
- **Reuters:** descontinuou o RSS público; cobrimos os wires via Investing.com e Google News.
- **SCMP e Channel News Asia:** devolvem **403 para bot** no RSS direto. Entram via
  `gnews("site:...")`, o mesmo padrão do WSJ e do Barron's.
- **Yahoo (fundamentos):** `quoteSummary` exige crumb/cookie e é frágil — por isso o fundamento
  das US vem da SEC.

## Limitações honestas

- IPs de datacenter (Actions) podem ser limitados ocasionalmente por alguma fonte; o workflow usa
  `continue-on-error`, mantendo o último dado válido — mas agora isso **aparece** no banner e no
  `check_health`.
- **Consenso (`fetch_estimates.py`)** é fonte secundária, não a companhia. A moeda de projeção é a
  do reporte (ASML/RACE em €, TSM em NT$); o forward P/E vem pronto da fonte justamente para não
  cruzar com o preço do ADR em dólar. Colunas marcadas "Upgrade"/"Pro" são paywall e viram nulo,
  nunca zero.
- **Estrangeiras (`fetch_intl.py`):** cobertura trimestral pode ser irregular. Se o Yahoo falhar
  para um nome, o último dado válido é mantido.
- **Cenários da aba Valuation** ficam no `localStorage` do navegador, não no repo. Trocar de
  máquina ou limpar o navegador apaga.

#!/usr/bin/env python3
"""
Gera data/insiders.json com atividade de insiders da cobertura:

 - US: SEC EDGAR Form 4 (ultimos 90 dias) das empresas domesticas.
   Só transacoes com codigo P (compra em mercado) e S (venda) — o sinal que
   interessa. Codigos F/M/A (imposto, exercicio, award) ficam de fora.
   FPIs (ASML, TSM, RACE, ABI, NU) nao arquivam Form 4 (isentas da Section 16).

 - BR: CVM Formulario 44 (VLMO consolidado, dados.cvm.gov.br) — compras e
   vendas a vista de Acoes por grupo (controlador, diretoria, conselhos),
   agregado por mes de referencia. Ultimos 4 meses.

Sem chave de API. Roda no GitHub Actions (SEC/CVM bloqueiam alguns IPs locais).
"""
import json, os, io, time, zipfile, datetime, urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict

HERE = os.path.dirname(__file__)
OUT = os.path.join(HERE, "..", "data", "insiders.json")
SEC_UA = os.environ.get("SEC_UA", "claude-advisor-dashboard pedro.beisl@gmail.com")
CVM_UA = "Mozilla/5.0 (compatible; claude-advisor-dashboard)"
DAYS = 90                 # janela p/ Form 4
MAX_FILINGS_PER_CO = 12   # limite de XMLs por empresa
BR_MONTHS = 4             # meses de referencia CVM

# ticker do dashboard -> CIK (10 digitos). Igual ao fetch_us.py.
US_CIKS = {
    "MSFT": "0000789019", "GOGL": "0001652044", "META": "0001326801",
    "AMZN": "0001018724", "JPM": "0000019617", "BLK": "0002012383",
    "MU": "0000723125", "MELI": "0001099590", "NVDA": "0001045810",
    "AAPL": "0000320193", "AMD": "0000002488", "INTC": "0000050863",
    "MRVL": "0001835632", "AVGO": "0001730168", "VZ": "0000732712",
    "TMUS": "0001283699", "T": "0000732717",
}

# ticker -> substring de Nome_Companhia no VLMO (mesma convencao do fetch_br.py)
BR_NAMES = {
    "SMFT3": "SMART FIT", "PRIO3": "PRIO", "SBSP3": "SANEAMENTO BASICO",
    "PETR4": "PETROLEO BRASILEIRO", "VALE3": "VALE S.A",
    "VIVT3": "TELEFONICA BRASIL", "TIMS3": "TIM S.A", "TOTS3": "TOTVS",
    "ABEV3": "AMBEV", "CSMG3": "COPASA", "ITUB4": "ITAU UNIBANCO",
    "BPAC11": "BTG PACTUAL",
}


def get(url, ua, timeout=60, binary=False):
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    return data if binary else data.decode("utf-8", "replace")


# ─── US: SEC Form 4 ──────────────────────────────────────────────────────────

def txt(el, path):
    e = el.find(path)
    return e.text.strip() if e is not None and e.text else None


def num(el, path):
    v = txt(el, path)
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse_form4(xml_str, ticker):
    """Extrai transacoes P/S de um Form 4 (ownershipDocument, sem namespace)."""
    xml_str = xml_str[xml_str.find("<ownershipDocument"):]
    root = ET.fromstring(xml_str)
    owner = root.find(".//reportingOwner")
    name = txt(owner, ".//rptOwnerName") if owner is not None else None
    rel = owner.find(".//reportingOwnerRelationship") if owner is not None else None
    role = None
    if rel is not None:
        role = txt(rel, "officerTitle")
        if not role and txt(rel, "isDirector") in ("1", "true"):
            role = "Director"
        if not role and txt(rel, "isTenPercentOwner") in ("1", "true"):
            role = "10% owner"
    rows = []
    for t in root.findall(".//nonDerivativeTransaction"):
        code = txt(t, ".//transactionCode")
        if code not in ("P", "S"):
            continue
        shares = num(t, ".//transactionShares/value")
        price = num(t, ".//transactionPricePerShare/value")
        rows.append({
            "t": ticker,
            "insider": name or "?",
            "role": role or "—",
            "date": txt(t, ".//transactionDate/value"),
            "code": code,                      # P = buy, S = sell
            "shares": shares,
            "price": price,
            "value": round(shares * price) if shares and price else None,
            "after": num(t, ".//sharesOwnedFollowingTransaction/value"),
        })
    return rows


def us_form4():
    cutoff = (datetime.date.today() - datetime.timedelta(days=DAYS)).isoformat()
    out = []
    for ticker, cik in US_CIKS.items():
        try:
            d = json.loads(get(f"https://data.sec.gov/submissions/CIK{cik}.json", SEC_UA))
        except Exception as e:
            print(f"[us] {ticker}: submissions falhou: {e}", file=os.sys.stderr)
            continue
        time.sleep(0.15)
        r = d.get("filings", {}).get("recent", {})
        forms, accs, dates, docs = (r.get(k, []) for k in
                                    ("form", "accessionNumber", "filingDate", "primaryDocument"))
        n = 0
        for i in range(len(forms)):
            if forms[i] != "4" or dates[i] < cutoff or n >= MAX_FILINGS_PER_CO:
                continue
            n += 1
            acc = accs[i].replace("-", "")
            doc = docs[i].split("/")[-1]  # tira prefixo xslF345X0*/
            url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/{doc}"
            try:
                rows = parse_form4(get(url, SEC_UA), ticker)
                out.extend(rows)
            except Exception as e:
                print(f"[us] {ticker} {acc}: parse falhou: {e}", file=os.sys.stderr)
            time.sleep(0.15)
    out.sort(key=lambda x: x.get("date") or "", reverse=True)
    return out


# ─── BR: CVM Formulario 44 (VLMO) ────────────────────────────────────────────

def br_vlmo():
    year = datetime.date.today().year
    rows = []
    for y in ({year, year - 1} if datetime.date.today().month <= BR_MONTHS else {year}):
        url = f"https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/VLMO/DADOS/vlmo_cia_aberta_{y}.zip"
        try:
            zf = zipfile.ZipFile(io.BytesIO(get(url, CVM_UA, timeout=120, binary=True)))
        except Exception as e:
            print(f"[br] zip {y} falhou: {e}", file=os.sys.stderr)
            continue
        fname = next((n for n in zf.namelist() if "_con_" in n), None)
        if not fname:
            continue
        with zf.open(fname) as fh:
            lines = io.TextIOWrapper(fh, encoding="latin-1").read().split("\n")
        hdr = lines[0].rstrip().split(";")
        ix = {c: hdr.index(c) for c in hdr}
        for ln in lines[1:]:
            c = ln.rstrip().split(";")
            if len(c) < len(hdr):
                continue
            mov = c[ix["Tipo_Movimentacao"]]
            if mov not in ("Compra à vista", "Venda à vista") or c[ix["Tipo_Ativo"]] != "Ações":
                continue
            nome = c[ix["Nome_Companhia"]].upper()
            ticker = next((t for t, s in BR_NAMES.items() if s in nome), None)
            if not ticker:
                continue
            try:
                qty = float(c[ix["Quantidade"]].replace(",", "."))
                vol = float(c[ix["Volume"]].replace(",", "."))
            except ValueError:
                continue
            rows.append({"ticker": ticker, "month": c[ix["Data_Referencia"]][:7],
                         "cargo": c[ix["Tipo_Cargo"]].replace(" ou Vinculado", ""),
                         "side": "buy" if mov.startswith("Compra") else "sell",
                         "qty": qty, "vol": vol})
    # agrega por ticker+mes+cargo
    agg = defaultdict(lambda: {"buyQty": 0, "buyVol": 0, "sellQty": 0, "sellVol": 0})
    for r in rows:
        a = agg[(r["ticker"], r["month"], r["cargo"])]
        a[r["side"] + "Qty"] += r["qty"]
        a[r["side"] + "Vol"] += r["vol"]
    months = sorted({m for (_, m, _) in agg}, reverse=True)[:BR_MONTHS]
    out = [dict(t=t, month=m, cargo=cg,
                buyQty=round(v["buyQty"]), buyVol=round(v["buyVol"]),
                sellQty=round(v["sellQty"]), sellVol=round(v["sellVol"]),
                netVol=round(v["buyVol"] - v["sellVol"]))
           for (t, m, cg), v in agg.items() if m in months]
    out.sort(key=lambda x: (x["month"], x["t"]), reverse=True)
    return out


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    data = {
        "updated": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "windowDays": DAYS,
        "us": us_form4(),
        "br": br_vlmo(),
    }
    with open(OUT, "w") as f:
        json.dump(data, f, ensure_ascii=False)
    print(f"insiders.json: {len(data['us'])} transacoes US, {len(data['br'])} agregados BR")


if __name__ == "__main__":
    main()

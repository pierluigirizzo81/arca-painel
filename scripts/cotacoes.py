#!/usr/bin/env python3
"""Lê radar.txt, busca cotações (Yahoo Finance) e P/VP (Fundamentus) e grava docs/cotacoes.js.

Roda no GitHub Actions e também no seu computador:
    pip install yfinance lxml
    python scripts/cotacoes.py

Só dados públicos de mercado entram aqui. Nunca coloque saldos ou dados da carteira.
"""
import io
import json
import unicodedata
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import yfinance as yf

RAIZ = Path(__file__).resolve().parent.parent
RADAR = RAIZ / "radar.txt"
SAIDA = RAIZ / "docs" / "cotacoes.js"
TIPOS = {"acao", "fii", "etf_br", "etf_eua", "etf_irlanda"}
DESTAQUES = [("usd", "Dólar (USD/BRL)", "USDBRL=X"), ("eur", "Euro (EUR/BRL)", "EURBRL=X"), ("btc", "Bitcoin (BTC/BRL)", "BTC-BRL")]
FUNDAMENTUS = {
    "acao": "https://www.fundamentus.com.br/resultado.php",
    "fii": "https://www.fundamentus.com.br/fii_resultado.php",
}


def agora():
    return datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")


def ler_radar():
    itens = []
    for linha in RADAR.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#"):
            continue
        partes = [p.strip() for p in linha.split(";")]
        if len(partes) < 2 or partes[0] not in TIPOS:
            print(f"Linha ignorada: {linha}")
            continue
        tipo, ticker = partes[0], partes[1].upper()
        nome = partes[2] if len(partes) > 2 else ""
        simbolo = ticker + ".SA" if tipo in ("acao", "fii", "etf_br") and "." not in ticker else ticker
        itens.append({"tipo": tipo, "ticker": ticker, "nome": nome, "simbolo": simbolo})
    return itens


def buscar(simbolo):
    t = yf.Ticker(simbolo)
    h = t.history(period="5d", interval="1d")["Close"].dropna()
    if h.empty:
        raise ValueError("sem dados")
    ultimo = float(h.iloc[-1])
    anterior = float(h.iloc[-2]) if len(h) > 1 else ultimo
    variacao = (ultimo / anterior - 1) * 100
    moeda = t.fast_info.get("currency") or "USD"
    if moeda == "GBp":  # Londres cota em pence
        ultimo, moeda = ultimo / 100, "GBP"
    return {"price": round(ultimo, 4), "change": round(variacao, 2), "currency": moeda}


def pvp_fundamentus(tipo):
    """Retorna {papel: P/VP} da tabela do Fundamentus (melhor esforço)."""
    try:
        import pandas as pd
        req = urllib.request.Request(FUNDAMENTUS[tipo], headers={"User-Agent": "Mozilla/5.0"})
        html = urllib.request.urlopen(req, timeout=30).read().decode("latin-1")
        tabela = pd.read_html(io.StringIO(html), decimal=",", thousands=".")[0]
        return {str(r["Papel"]).strip().upper(): float(r["P/VP"]) for _, r in tabela.iterrows()
                if str(r["P/VP"]) not in ("nan", "")}
    except Exception as e:
        print(f"P/VP ({tipo}) indisponível: {e}")
        return {}


CKAN_API = "https://www.tesourotransparente.gov.br/ckan/api/3/action/package_show?id=df56aa42-484a-4a59-8184-7676580c81e3"
CSV_FALLBACK = ("https://www.tesourotransparente.gov.br/ckan/dataset/df56aa42-484a-4a59-8184-7676580c81e3/"
                "resource/796d2059-14e9-44e3-80c9-2d9e30b405c1/download/PrecoTaxaTesouroDireto.csv")
UA = {"User-Agent": "Mozilla/5.0"}
ORDEM_TESOURO = {"prefixado": 0, "ipca": 1, "renda": 2}


def sem_acento(t):
    return unicodedata.normalize("NFKD", str(t)).encode("ascii", "ignore").decode().lower().strip()


def baixar_tesouro_csv():
    urls = []
    try:
        pacote = json.load(urllib.request.urlopen(urllib.request.Request(CKAN_API, headers=UA), timeout=30))
        urls += [r["url"] for r in pacote["result"]["resources"]
                 if r.get("url", "").lower().endswith("precotaxatesourodireto.csv")]
    except Exception as e:
        print(f"Tesouro: não consegui consultar o catálogo ({e}); usando o endereço padrão")
    urls.append(CSV_FALLBACK)
    for u in urls:
        try:
            return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=180).read()
        except Exception as e:
            print(f"Tesouro: falha em {u} ({e})")
    raise RuntimeError("CSV do Tesouro indisponível")


def tesouro():
    """Prefixados, IPCA+ e RendA+ 2065, com taxas e PU de abertura do último dia disponível."""
    import pandas as pd
    raw = baixar_tesouro_csv()
    for enc in ("utf-8-sig", "latin-1"):
        try:
            df = pd.read_csv(io.BytesIO(raw), sep=";", decimal=",", encoding=enc)
            break
        except UnicodeDecodeError:
            continue
    df.columns = [sem_acento(c) for c in df.columns]
    col = lambda ini: next(c for c in df.columns if c.startswith(ini))
    ct, cv, cb = col("tipo"), col("data venc"), col("data base")
    cx, cs, cp = col("taxa compra"), col("taxa venda"), col("pu compra")
    for k in (cv, cb):
        df[k] = pd.to_datetime(df[k], format="%d/%m/%Y", errors="coerce")
    df = df.dropna(subset=[cv, cb])
    ultima = df[cb].max()
    atual = df[df[cb] == ultima]
    ant = df[df[cb] < ultima].sort_values(cb).groupby([ct, cv]).tail(1)
    taxa_ant = {(r[ct], r[cv]): r[cx] for _, r in ant.iterrows()}
    saida = []
    for _, r in atual.iterrows():
        t, venc = sem_acento(r[ct]), r[cv]
        if "prefixado" in t:
            g = "prefixado"
        elif "ipca" in t:
            g = "ipca"
        elif "renda" in t and venc.year == 2065:
            g = "renda"
        else:
            continue
        if r[cx] != r[cx]:  # taxa vazia (NaN)
            continue
        antes = taxa_ant.get((r[ct], venc))
        saida.append({
            "grupo": g, "titulo": str(r[ct]).strip(), "vencimento": venc.strftime("%d/%m/%Y"),
            "taxa_compra": round(float(r[cx]), 2),
            "taxa_venda": None if r[cs] != r[cs] else round(float(r[cs]), 2),
            "pu_compra": None if r[cp] != r[cp] else round(float(r[cp]), 2),
            "var_taxa": None if antes is None or antes != antes else round(float(r[cx]) - float(antes), 2),
            "data_base": ultima.strftime("%d/%m/%Y"),
        })
    saida.sort(key=lambda x: (ORDEM_TESOURO[x["grupo"]], x["titulo"], x["vencimento"][6:] + x["vencimento"][3:5]))
    return saida


def main():
    itens = ler_radar()
    pvp = {t: pvp_fundamentus(t) for t in FUNDAMENTUS}
    assets, quotes = [], {}
    for it in itens:
        try:
            q = buscar(it["simbolo"])
        except Exception as e:
            print(f"{it['ticker']}: falhou ({e})")
            assets.append({"tipo": it["tipo"], "ticker": it["ticker"], "nome": it["nome"], "price": None,
                           "change": None, "currency": None, "pvp": None, "at": agora()})
            continue
        v = pvp.get(it["tipo"], {}).get(it["ticker"])
        if v is not None and not (0 < v < 50):
            v = None
        assets.append({"tipo": it["tipo"], "ticker": it["ticker"], "nome": it["nome"], **q,
                       "pvp": v, "at": agora()})
        quotes[it["ticker"]] = {**q, "at": agora()}
        print(f"{it['ticker']}: {q['price']} {q['currency']}  P/VP={v}")
    try:
        td = tesouro()
        print(f"Tesouro Direto: {len(td)} títulos")
    except Exception as e:
        print(f"Tesouro Direto indisponível: {e}")
        td = []
    destaques = []
    for id_, rotulo, simbolo in DESTAQUES:
        try:
            destaques.append({"id": id_, "rotulo": rotulo, **buscar(simbolo)})
        except Exception as e:
            print(f"{rotulo}: falhou ({e})")
    if not assets and not destaques and not td:
        raise SystemExit("Nenhuma cotação obtida; arquivo não foi alterado.")
    dados = {"generated": agora(), "destaques": destaques, "assets": assets, "tesouro": td, "quotes": quotes}
    SAIDA.write_text("window.ARCA_COTACOES = " + json.dumps(dados, ensure_ascii=False, indent=1) + ";\n", encoding="utf-8")
    print(f"Gravado: {SAIDA}")


if __name__ == "__main__":
    main()

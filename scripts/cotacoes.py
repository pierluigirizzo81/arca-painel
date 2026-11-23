#!/usr/bin/env python3
"""Lê radar.txt, busca cotações (Yahoo Finance) e P/VP (Fundamentus) e grava docs/cotacoes.js.

Roda no GitHub Actions e também no seu computador:
    pip install yfinance lxml
    python scripts/cotacoes.py

Só dados públicos de mercado entram aqui. Nunca coloque saldos ou dados da carteira.
"""
import io
import json
import subprocess
import time
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
ORDEM_TESOURO = {"prefixado": 0, "ipca": 1, "renda": 2}


def sem_acento(t):
    return unicodedata.normalize("NFKD", str(t)).encode("ascii", "ignore").decode().lower().strip()


UA_NAV = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
          "Chrome/124.0 Safari/537.36")
UA = {"User-Agent": UA_NAV, "Accept": "*/*", "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"}
TD_JSON = "https://www.tesourodireto.com.br/json/br/com/b3/tesourodireto/service/api/treasurybondsinfo.json"


def baixar(url, timeout=180):
    """Baixa uma URL: urllib (3 tentativas) e, se falhar, curl. Levanta erro se nada funcionar."""
    ultimo = None
    for i in range(3):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()
        except Exception as e:
            ultimo = e
            time.sleep(3 * (i + 1))
    try:
        r = subprocess.run(["curl", "-sSL", "--retry", "3", "--retry-delay", "3", "--max-time", str(timeout),
                            "-A", UA_NAV, "-H", "Accept-Language: pt-BR,pt;q=0.9", url],
                           capture_output=True, timeout=timeout + 60)
        if r.returncode == 0 and len(r.stdout) > 500:
            return r.stdout
        ultimo = f"{ultimo}; curl: código {r.returncode} {r.stderr.decode(errors='ignore')[:120]}"
    except Exception as e:
        ultimo = f"{ultimo}; curl: {e}"
    raise RuntimeError(ultimo)


def baixar_tesouro_csv():
    urls = []
    try:
        pacote = json.loads(baixar(CKAN_API, 30))
        urls += [r["url"] for r in pacote["result"]["resources"]
                 if r.get("url", "").lower().endswith("precotaxatesourodireto.csv")]
    except Exception as e:
        print(f"Tesouro: não consegui consultar o catálogo ({e}); usando o endereço padrão")
    urls.append(CSV_FALLBACK)
    for u in urls:
        try:
            return baixar(u)
        except Exception as e:
            print(f"Tesouro: falha em {u} ({e})")
    raise RuntimeError("CSV do Tesouro indisponível")


def tesouro_json():
    """Fonte alternativa: preços e taxas atuais publicados pelo site do Tesouro Direto."""
    dados = json.loads(baixar(TD_JSON, 60))["response"]
    data_base = str((dados.get("TrsrBondMkt") or {}).get("opngDtTm") or "")[:10]
    try:
        data_base = datetime.strptime(data_base, "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        data_base = datetime.now().strftime("%d/%m/%Y")
    saida = []
    for item in dados.get("TrsrBdTradgList", []):
        b = item.get("TrsrBd", {})
        nome, t = str(b.get("nm", "")).strip(), sem_acento(b.get("nm", ""))
        taxa, pu = b.get("anulInvstmtRate"), b.get("untrInvstmtVal")
        if not taxa or "semestrais" in t:
            continue
        if "prefixado" in t:
            g = "prefixado"
        elif "ipca" in t:
            g = "ipca"
        elif "renda" in t and "2065" in t:
            g = "renda"
        else:
            continue
        venc = str(b.get("mtrtyDt", ""))[:10]
        try:
            venc = datetime.strptime(venc, "%Y-%m-%d").strftime("%d/%m/%Y")
        except ValueError:
            continue
        saida.append({"grupo": g, "titulo": nome, "vencimento": venc, "taxa_compra": round(float(taxa), 2),
                      "taxa_venda": None, "pu_compra": None if not pu else round(float(pu), 2),
                      "var_taxa": None, "data_base": data_base})
    saida.sort(key=lambda x: (ORDEM_TESOURO[x["grupo"]], x["titulo"], x["vencimento"][6:] + x["vencimento"][3:5]))
    return saida


ANOS_RENDA_2065 = (2065, 2084)  # RendA+ 2065: pagamentos a partir de 2065; vencimento em 15/12/2084


def tesouro_csv():
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
    print(f"Tesouro: colunas = {list(df.columns)[:8]}; {len(df)} linhas")
    df = df.dropna(subset=[cv, cb, cx])  # ignora linhas sem taxa (dia ainda não preenchido)

    def relevante(r):
        t = sem_acento(r[ct])
        if "semestrais" in t:
            return False
        return "prefixado" in t or "ipca" in t or ("renda" in t and r[cv].year in ANOS_RENDA_2065)

    df = df[df.apply(relevante, axis=1)]
    if df.empty:
        raise ValueError("nenhum título relevante com taxa no arquivo")
    print("Tesouro: RendA+ no arquivo (vencimentos) =", sorted({d.strftime("%d/%m/%Y") for d in df[df[ct].map(sem_acento).str.contains("renda")][cv]}))
    ultima = df[cb].max()
    atual = df[df[cb] == ultima]
    ant = df[df[cb] < ultima].sort_values(cb).groupby([ct, cv]).tail(1)
    taxa_ant = {(r[ct], r[cv]): r[cx] for _, r in ant.iterrows()}
    saida = []
    for _, r in atual.iterrows():
        t, venc = sem_acento(r[ct]), r[cv]
        if "semestrais" in t:  # só títulos sem pagamento de juros semestrais
            continue
        if "prefixado" in t:
            g = "prefixado"
        elif "ipca" in t:
            g = "ipca"
        elif "renda" in t and venc.year in ANOS_RENDA_2065:
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


HIST_ARQ = RAIZ / "docs" / "historico.js"
HIST_VALIDADE_H = 20


def serie(simbolo):
    """5 anos de fechamentos: diário no último ano e a cada 5 pregões antes disso."""
    t = yf.Ticker(simbolo)
    h = t.history(period="5y", interval="1d")["Close"].dropna()
    if h.empty:
        raise ValueError("sem dados")
    moeda = t.fast_info.get("currency") or "USD"
    div = 100 if moeda == "GBp" else 1
    moeda = "GBP" if moeda == "GBp" else moeda
    pts = [[d.strftime("%Y-%m-%d"), round(float(v) / div, 4)] for d, v in h.items()]
    return {"currency": moeda, "pts": pts[:-250:5] + pts[-250:]}


def atualizar_historico(itens):
    """Gera docs/historico.js no máximo uma vez por dia (ou quando entra ativo novo no radar)."""
    pedidos = {it["ticker"]: it["simbolo"] for it in itens}
    pedidos.update({"usd": "USDBRL=X", "eur": "EURBRL=X", "btc": "BTC-BRL"})
    atual = {}
    if HIST_ARQ.exists():
        try:
            txt = HIST_ARQ.read_text(encoding="utf-8")
            atual = json.loads(txt[txt.index("{"):txt.rindex("}") + 1])
        except Exception:
            atual = {}
    try:
        idade = (datetime.now(timezone.utc) - datetime.fromisoformat(atual["iso"])).total_seconds() / 3600
    except Exception:
        idade = 9999
    faltam = [k for k in pedidos if k not in atual.get("series", {}) and k != "btc"]
    if idade < HIST_VALIDADE_H and not faltam:
        print("Histórico: ainda válido, mantido.")
        return
    series = {}
    for chave, simbolo in pedidos.items():
        try:
            series[chave] = serie(simbolo)
        except Exception as e:
            if chave == "btc":
                try:
                    series[chave] = serie("BTC-USD")  # em US$ quando o Yahoo não tem BTC-BRL
                    continue
                except Exception:
                    pass
            print(f"Histórico {chave}: falhou ({e})")
    if not series:
        print("Histórico: nada obtido; arquivo mantido.")
        return
    dados = {"iso": datetime.now(timezone.utc).isoformat(), "series": series}
    HIST_ARQ.write_text("window.ARCA_HISTORICO = " + json.dumps(dados, ensure_ascii=False, separators=(",", ":")) + ";\n", encoding="utf-8")
    print(f"Histórico gravado: {len(series)} séries")


def tesouro():
    try:
        r = tesouro_csv()
        if r:
            return r
        print("Tesouro: CSV sem títulos relevantes; tentando o site do Tesouro Direto")
    except Exception as e:
        print(f"Tesouro: CSV indisponível ({e}); tentando o site do Tesouro Direto")
    r = tesouro_json()
    print(f"Tesouro: {len(r)} títulos obtidos pelo site do Tesouro Direto")
    return r


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
    if not td:  # mantém a última versão boa em vez de apagar as tabelas
        try:
            txt = SAIDA.read_text(encoding="utf-8")
            td = json.loads(txt[txt.index("{"):txt.rindex("}") + 1]).get("tesouro", [])
            print(f"Tesouro: mantidos {len(td)} títulos da atualização anterior")
        except Exception:
            td = []
    por_id = {}
    for id_, rotulo, simbolo in DESTAQUES:
        try:
            por_id[id_] = {"id": id_, "rotulo": rotulo, **buscar(simbolo)}
        except Exception as e:
            print(f"{rotulo}: falhou ({e})")
    if "btc" not in por_id and "usd" in por_id:  # Yahoo nem sempre tem BTC-BRL: calcula via BTC-USD x USD/BRL
        try:
            b, u = buscar("BTC-USD"), por_id["usd"]
            por_id["btc"] = {"id": "btc", "rotulo": "Bitcoin (BTC/BRL)", "currency": "BRL",
                             "price": round(b["price"] * u["price"], 2),
                             "change": round(((1 + b["change"] / 100) * (1 + u["change"] / 100) - 1) * 100, 2)}
            print("Bitcoin: calculado a partir de BTC-USD x USD/BRL")
        except Exception as e:
            print(f"Bitcoin: falhou ({e})")
    destaques = [por_id[i] for i, _, _ in DESTAQUES if i in por_id]
    if not assets and not destaques and not td:
        raise SystemExit("Nenhuma cotação obtida; arquivo não foi alterado.")
    dados = {"generated": agora(), "destaques": destaques, "assets": assets, "tesouro": td, "quotes": quotes}
    SAIDA.write_text("window.ARCA_COTACOES = " + json.dumps(dados, ensure_ascii=False, indent=1) + ";\n", encoding="utf-8")
    print(f"Gravado: {SAIDA}")
    try:
        atualizar_historico(itens)
    except Exception as e:
        print(f"Histórico indisponível: {e}")


if __name__ == "__main__":
    main()

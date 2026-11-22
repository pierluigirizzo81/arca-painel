#!/usr/bin/env python3
"""Busca cotações públicas (Yahoo Finance) e grava docs/cotacoes.js.

Roda automaticamente no GitHub Actions (veja .github/workflows/cotacoes.yml)
e também pode ser rodado no seu computador:
    pip install yfinance
    python scripts/cotacoes.py

Aqui entram SOMENTE tickers públicos de mercado. Nunca coloque saldos,
quantidades ou dados da carteira neste arquivo: o repositório é público.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import yfinance as yf

# Mesmos símbolos do radar do painel (coluna "Ticker / ID"). Edite à vontade.
TICKERS = [
    "SPY", "CSPX.L", "VUAA.L", "VWRA.L", "EIMI.L",
    # "IWDA.AS", "VWCE.DE", "QQQ", "VOO",
]
SAIDA = Path(__file__).resolve().parent.parent / "docs" / "cotacoes.js"


def buscar(ticker):
    t = yf.Ticker(ticker)
    h = t.history(period="5d", interval="1d")["Close"].dropna()
    if h.empty:
        raise ValueError("sem dados")
    ultimo = float(h.iloc[-1])
    anterior = float(h.iloc[-2]) if len(h) > 1 else ultimo
    variacao = (ultimo / anterior - 1) * 100
    moeda = t.fast_info.get("currency") or "USD"
    if moeda == "GBp":  # Londres cota em pence
        ultimo, moeda = ultimo / 100, "GBP"
    return {
        "price": round(ultimo, 4),
        "change": round(variacao, 2),
        "currency": moeda,
        "at": datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC"),
    }


def main():
    quotes = {}
    for tk in TICKERS:
        try:
            quotes[tk] = buscar(tk)
            print(f"{tk}: {quotes[tk]['price']} {quotes[tk]['currency']}")
        except Exception as e:
            print(f"{tk}: falhou ({e})")
    if not quotes:
        raise SystemExit("Nenhuma cotação obtida; arquivo não foi alterado.")
    dados = {"generated": datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC"), "quotes": quotes}
    SAIDA.write_text("window.ARCA_COTACOES = " + json.dumps(dados, ensure_ascii=False, indent=1) + ";\n", encoding="utf-8")
    print(f"Gravado: {SAIDA}")


if __name__ == "__main__":
    main()

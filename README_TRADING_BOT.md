# Borsa Analiz ve Paper Trading Robotu

Bu proje yurtdisi piyasalari analiz etmek, stratejileri geriye donuk test etmek ve sanal para ile paper trading yapmak icin guvenli bir baslangic iskeletidir.

> Uyari: Bu yazilim finansal tavsiye degildir. Gercek emir gondermez. Canli al-sat icin kullanmadan once lisans, vergi, piyasa riski, broker sozlesmeleri ve teknik guvenlik konulari profesyonelce degerlendirilmelidir.

## Ozellikler

- Yahoo Finance uzerinden OHLCV veri cekme
- SMA crossover stratejisi
- RSI stratejisi
- Stop-loss ve take-profit risk kurallari
- Basit backtest motoru
- Paper trading simulyasyonu
- CLI komutlari

## Kurulum

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Backtest Calistirma

```bash
python -m trading_bot.cli backtest --symbol AAPL --strategy sma --start 2023-01-01 --end 2024-01-01
```

## Paper Trading Simulasyonu

```bash
python -m trading_bot.cli paper --symbol AAPL --strategy rsi --days 180
```

## Proje Yapisi

```text
trading_bot/
  cli.py
  data.py
  risk.py
  backtest.py
  paper.py
  strategies/
    sma.py
    rsi.py
```

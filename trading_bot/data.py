import yfinance as yf


def load_data(symbol: str, start: str, end: str):
    data = yf.download(symbol, start=start, end=end)
    data = data.dropna()
    return data

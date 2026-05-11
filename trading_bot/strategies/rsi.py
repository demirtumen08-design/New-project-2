import pandas as pd


def compute_rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = -delta.where(delta < 0, 0).rolling(period).mean()

    rs = gain / loss
    return 100 - (100 / (1 + rs))


def generate_signals(data: pd.DataFrame):
    signals = pd.DataFrame(index=data.index)
    signals['rsi'] = compute_rsi(data['Close'])
    signals['signal'] = 0

    signals.loc[signals['rsi'] < 30, 'signal'] = 1
    signals.loc[signals['rsi'] > 70, 'signal'] = -1

    return signals

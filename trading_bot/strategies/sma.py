import pandas as pd


def generate_signals(data: pd.DataFrame, short_window: int = 20, long_window: int = 50):
    signals = pd.DataFrame(index=data.index)
    signals['signal'] = 0

    signals['short_ma'] = data['Close'].rolling(window=short_window).mean()
    signals['long_ma'] = data['Close'].rolling(window=long_window).mean()

    signals.loc[signals['short_ma'] > signals['long_ma'], 'signal'] = 1
    signals.loc[signals['short_ma'] < signals['long_ma'], 'signal'] = -1

    return signals

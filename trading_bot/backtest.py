def run_backtest(data, signals, initial_balance=10000):
    balance = initial_balance
    position = 0

    for i in range(len(signals)):
        signal = signals['signal'].iloc[i]
        price = data['Close'].iloc[i]

        if signal == 1 and position == 0:
            position = balance / price
            balance = 0

        elif signal == -1 and position > 0:
            balance = position * price
            position = 0

    final_value = balance if position == 0 else position * data['Close'].iloc[-1]

    return {
        'initial_balance': initial_balance,
        'final_value': round(final_value, 2),
        'profit_pct': round(((final_value - initial_balance) / initial_balance) * 100, 2)
    }

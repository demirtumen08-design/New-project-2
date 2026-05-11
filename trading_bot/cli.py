import argparse

from trading_bot.data import load_data
from trading_bot.backtest import run_backtest
from trading_bot.strategies.sma import generate_signals as sma_signals
from trading_bot.strategies.rsi import generate_signals as rsi_signals


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode')
    parser.add_argument('--symbol', required=True)
    parser.add_argument('--strategy', required=True)
    parser.add_argument('--start', default='2023-01-01')
    parser.add_argument('--end', default='2024-01-01')

    args = parser.parse_args()

    data = load_data(args.symbol, args.start, args.end)

    if args.strategy == 'sma':
        signals = sma_signals(data)
    else:
        signals = rsi_signals(data)

    results = run_backtest(data, signals)

    print('\n=== BACKTEST RESULTS ===')
    for k, v in results.items():
        print(f'{k}: {v}')


if __name__ == '__main__':
    main()

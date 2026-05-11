import SwiftUI

struct ContentView: View {
    @State private var symbol: String = "AAPL"
    @State private var strategy: String = "SMA"
    @State private var profit: String = "+12.4%"

    var body: some View {
        NavigationView {
            VStack(spacing: 24) {
                Text("Trading Analyzer")
                    .font(.largeTitle)
                    .bold()

                VStack(alignment: .leading, spacing: 12) {
                    Text("Symbol")
                    TextField("Ticker", text: $symbol)
                        .textFieldStyle(.roundedBorder)

                    Text("Strategy")
                    Picker("Strategy", selection: $strategy) {
                        Text("SMA").tag("SMA")
                        Text("RSI").tag("RSI")
                    }
                    .pickerStyle(.segmented)
                }
                .padding()

                VStack(spacing: 12) {
                    Text("Backtest Result")
                        .font(.headline)

                    Text(profit)
                        .font(.system(size: 42, weight: .bold))
                }
                .padding()

                Button(action: runSimulation) {
                    Text("Run Simulation")
                        .padding()
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)

                Spacer()

                Text("Paper trading only. Not financial advice.")
                    .font(.footnote)
                    .foregroundColor(.gray)
            }
            .padding()
        }
    }

    func runSimulation() {
        let randomValue = Double.random(in: -5...25)
        profit = String(format: "%+.2f%%", randomValue)
    }
}

#Preview {
    ContentView()
}

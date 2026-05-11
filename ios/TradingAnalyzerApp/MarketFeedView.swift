import SwiftUI

struct MarketFeedView: View {
    @State private var prices: [Double] = [101.2, 102.5, 103.1, 102.8]

    var body: some View {
        VStack(alignment: .leading) {
            Text("Live Market Feed")
                .font(.title2)
                .bold()

            List(prices.indices, id: \.self) { index in
                HStack {
                    Text("Tick \(index + 1)")
                    Spacer()
                    Text(String(format: "$%.2f", prices[index]))
                }
            }

            Button("Simulate Tick") {
                prices.append(Double.random(in: 95...115))
            }
            .buttonStyle(.borderedProminent)
        }
        .padding()
    }
}

#Preview {
    MarketFeedView()
}

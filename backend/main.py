from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import asyncio
import random

app = FastAPI(title="Trading Analyzer API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SignalRequest(BaseModel):
    symbol: str = "AAPL"
    strategy: str = "sma"


@app.get("/health")
def health():
    return {"status": "ok", "mode": "paper_trading_only"}


@app.post("/signal")
def signal(request: SignalRequest):
    score = round(random.uniform(-1, 1), 3)
    if score > 0.35:
        action = "watch_buy_zone"
    elif score < -0.35:
        action = "watch_sell_zone"
    else:
        action = "hold"
    return {
        "symbol": request.symbol.upper(),
        "strategy": request.strategy,
        "score": score,
        "action": action,
        "disclaimer": "Analysis only. Not financial advice. No live orders are sent."
    }


@app.websocket("/ws/market/{symbol}")
async def market_feed(websocket: WebSocket, symbol: str):
    await websocket.accept()
    price = 100.0
    while True:
        price += random.uniform(-1.5, 1.5)
        await websocket.send_json({
            "symbol": symbol.upper(),
            "price": round(price, 2),
            "volume": random.randint(1000, 100000)
        })
        await asyncio.sleep(1)

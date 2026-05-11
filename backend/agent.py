import os
from typing import Any, Dict

from openai import OpenAI
from pydantic import BaseModel


class AgentInput(BaseModel):
    symbol: str
    strategy: str
    market_snapshot: Dict[str, Any]
    risk_profile: str = "moderate"


class AgentOutput(BaseModel):
    symbol: str
    summary: str
    signal_explanation: str
    risk_notes: str
    suggested_action: str
    confidence: float
    disclaimer: str


SYSTEM_PROMPT = """
You are a cautious market analysis assistant for a paper-trading app.
You do not provide financial advice.
You do not guarantee profit.
You do not place live orders.
You explain signals, risks, uncertainty, and possible scenarios.
Allowed actions: hold, watch_buy_zone, watch_sell_zone, reduce_risk, wait_for_confirmation.
"""


def build_fallback_response(payload: AgentInput) -> AgentOutput:
    return AgentOutput(
        symbol=payload.symbol.upper(),
        summary="AI service is not configured. Using deterministic fallback analysis.",
        signal_explanation=f"Strategy {payload.strategy} produced a paper-trading analysis request.",
        risk_notes="Keep position sizing small, use stop-loss planning, and avoid trading around unclear volatility.",
        suggested_action="wait_for_confirmation",
        confidence=0.25,
        disclaimer="Analysis only. Not financial advice. No live orders are sent."
    )


def analyze_with_openai(payload: AgentInput) -> AgentOutput:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return build_fallback_response(payload)

    client = OpenAI(api_key=api_key)

    response = client.responses.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        input=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Analyze this paper-trading market snapshot and return JSON with keys: "
                    "symbol, summary, signal_explanation, risk_notes, suggested_action, confidence, disclaimer.\n\n"
                    f"Symbol: {payload.symbol}\n"
                    f"Strategy: {payload.strategy}\n"
                    f"Risk profile: {payload.risk_profile}\n"
                    f"Market snapshot: {payload.market_snapshot}"
                )
            }
        ]
    )

    text = response.output_text
    return AgentOutput(
        symbol=payload.symbol.upper(),
        summary=text[:700],
        signal_explanation="See summary for AI-generated reasoning.",
        risk_notes="Review AI output manually before any real-world decision.",
        suggested_action="hold",
        confidence=0.5,
        disclaimer="Analysis only. Not financial advice. No live orders are sent."
    )

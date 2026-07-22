# Repository expectations

## Purpose

This repository is a Trading Analyzer prototype with a FastAPI backend, SwiftUI iOS client, websocket market feed, notifications, and an OpenAI-assisted paper-trading analysis layer.

## Current source of truth

- Backend API: `backend/main.py`
- Analysis agent: `backend/agent.py`
- iOS app: `ios/TradingAnalyzerApp/`
- Deployment notes: `DEPLOYMENT.md`
- The root README is minimal and may describe an older project identity. Prefer current code and deployment files when they conflict with it.

## Safety and product boundaries

- Paper trading and analysis only. Do not add live order execution unless the user creates a separate, explicit scope with broker, authentication, risk, compliance, and approval requirements.
- Never promise profit, certainty, or a guaranteed market outcome.
- Clearly distinguish simulated/random data from real market data in API responses and UI.
- Keep risk, uncertainty, and human review visible in every AI-generated analysis.
- Store API keys and provider credentials only in environment variables or approved secret storage; never commit them.
- Preserve deterministic fallback behavior when the AI service is unavailable.

## Engineering rules

- Keep backend schemas, websocket payloads, and iOS models synchronized.
- Add or update focused tests for API contracts, fallback behavior, validation, and failure cases.
- Validate the backend locally before describing it as deployable.
- Do not describe prototype random-price or random-signal behavior as real market analysis.
- Treat financial-output changes as high risk: cite assumptions, bound confidence, and avoid automatic real-world action.

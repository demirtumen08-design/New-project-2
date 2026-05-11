# Deployment Guide

## Backend Local Run

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
```

## Docker

```bash
docker build -t trading-analyzer .
docker run -p 8000:8000 trading-analyzer
```

## iOS

1. Open Xcode
2. Import ios folder
3. Build for iPhone simulator
4. Run

## Suggested Infrastructure

- FastAPI backend
- Redis cache
- PostgreSQL
- Nginx reverse proxy
- Render or Railway deployment
- Firebase notifications

## Security Notes

- No live trading enabled
- Paper trading only
- API keys should stay in .env
- Use rate limiting in production

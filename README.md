# AnimaRH Candidate Screener API

A FastAPI service that wraps AI-powered candidate pre-screening. Extracted from a
production executive recruitment system (AnimaRH ATS) that has processed 700+
candidates across 15 active roles.

## What it does

POST `/screen` takes a candidate summary and role requirements, calls Claude, and
returns a structured fit assessment: numeric score, rating tier (A/A-/B+/B/DISCARD),
dealbreakers, strengths, gaps, and ADVANCE/HOLD/DISCARD recommendation.

This mirrors the format AnimaRH uses internally — the same output feeds into
Google Sheets delivery to clients.

## Run locally

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=your-key
export API_KEY=your-api-token
uvicorn main:app --reload
```

Try it:

```bash
curl -X POST http://localhost:8000/screen \
  -H "Authorization: Bearer your-api-token" \
  -H "Content-Type: application/json" \
  -d '{
    "candidate_name": "Ana Lima",
    "candidate_summary": "12 years in manufacturing ops. Last role: Production Manager at a 400-person plastics plant (ISO 9001). Managed 3 shifts, reduced scrap rate by 18%. CLT preferred.",
    "role_requirements": "Gerente de Producao for injection molding plant, 200+ headcount, 5+ years managing shifts, lean manufacturing experience required."
  }'
```

## Deploy to Railway

1. Push this folder to a GitHub repo
2. Connect repo to [railway.app](https://railway.app)
3. Set env vars: `ANTHROPIC_API_KEY`, `API_KEY`
4. Deploy — Railway auto-detects Python via Nixpacks

## Auth

Bearer token. Set `API_KEY` env var server-side. Pass `Authorization: Bearer <token>`
on every request to `/screen`. The `/health` endpoint is public.

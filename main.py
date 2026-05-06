"""
AnimaRH Candidate Screener API
A lightweight screening layer over a production recruitment system.

Deployed at: [railway url after deploy]
Auth: Bearer token (set API_KEY env var)
"""
from __future__ import annotations

import os
from typing import Annotated

import anthropic
from fastapi import FastAPI, Header, HTTPException, status
from pydantic import BaseModel

app = FastAPI(
    title="AnimaRH Screener API",
    description="AI-powered candidate pre-screening for executive recruitment.",
    version="1.0.0",
)

# Mount GraphQL at /graphql (alternative transport, same scoring logic)
try:
    from graphql_app import graphql_app
    app.include_router(graphql_app, prefix="/graphql")
except ImportError:
    pass  # GraphQL is optional — REST endpoints work without strawberry installed

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def verify_token(authorization: Annotated[str | None, Header()] = None) -> str:
    """Validate Bearer token against API_KEY env var."""
    expected = os.environ.get("API_KEY")
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="API_KEY not configured on server.",
        )
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header. Expected: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.removeprefix("Bearer ").strip()
    if token != expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid token.",
        )
    return token


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class ScreenRequest(BaseModel):
    candidate_name: str
    candidate_summary: str  # 2-3 sentences from CV or LinkedIn
    role_requirements: str  # what the client is looking for


class ScreenResult(BaseModel):
    candidate: str
    fit_score: int          # 0-10
    rating: str             # A / A- / B+ / B / DISCARD
    dealbreakers: list[str] # empty if none detected
    strengths: list[str]
    gaps: list[str]
    recommendation: str     # ADVANCE / HOLD / DISCARD
    reasoning: str          # 2-3 sentences


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "animarh-screener"}


@app.post("/screen", response_model=ScreenResult)
def screen_candidate(
    payload: ScreenRequest,
    authorization: Annotated[str | None, Header()] = None,
) -> ScreenResult:
    """
    Pre-screen a candidate against role requirements using Claude.
    Returns structured fit assessment — same format AnimaRH uses in production.
    """
    verify_token(authorization)

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    prompt = f"""You are an executive recruiter scoring a candidate.

ROLE REQUIREMENTS:
{payload.role_requirements}

CANDIDATE ({payload.candidate_name}):
{payload.candidate_summary}

Return ONLY valid JSON with these exact keys:
{{
  "fit_score": <integer 0-10>,
  "rating": <"A"|"A-"|"B+"|"B"|"DISCARD">,
  "dealbreakers": [<strings, empty list if none>],
  "strengths": [<2-4 strings>],
  "gaps": [<1-3 strings, empty if none>],
  "recommendation": <"ADVANCE"|"HOLD"|"DISCARD">,
  "reasoning": <string, 2-3 sentences>
}}

Rating scale: A=8-10, A-=6.5-7.9, B+=5.5-6.4, B=4-5.4, DISCARD=<4.
No markdown, no explanation outside the JSON."""

    message = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )

    import json
    raw = message.content[0].text.strip()
    data = json.loads(raw)

    return ScreenResult(
        candidate=payload.candidate_name,
        fit_score=data["fit_score"],
        rating=data["rating"],
        dealbreakers=data.get("dealbreakers", []),
        strengths=data.get("strengths", []),
        gaps=data.get("gaps", []),
        recommendation=data["recommendation"],
        reasoning=data["reasoning"],
    )

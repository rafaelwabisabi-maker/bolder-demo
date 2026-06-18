"""
GraphQL endpoint for the candidate screener — same scoring logic, GraphQL transport.

Demonstrates: GraphQL schema design, resolver pattern, query + mutation,
type-safe results. Mounted at /graphql in main.py.

Run locally:
    pip install strawberry-graphql[fastapi]
    uvicorn main:app --reload
    open http://localhost:8000/graphql

Sample query:
    mutation {
      screenCandidate(
        input: {
          candidateName: "Ana Lima"
          candidateSummary: "12 years manufacturing ops, ISO 9001 plant, 18% scrap reduction"
          roleRequirements: "Gerente de Produção for injection molding, 5+ years shifts"
        }
      ) {
        candidate
        fitScore
        rating
        recommendation
        reasoning
      }
    }
"""
from __future__ import annotations

import json
import os
from typing import Optional

import anthropic
import strawberry
from strawberry.fastapi import GraphQLRouter
from strawberry.types import Info


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

@strawberry.input
class ScreenInput:
    candidate_name: str
    candidate_summary: str
    role_requirements: str


@strawberry.type
class ScreenResult:
    candidate: str
    fit_score: int
    rating: str
    dealbreakers: list[str]
    strengths: list[str]
    gaps: list[str]
    recommendation: str
    reasoning: str


@strawberry.type
class HealthStatus:
    status: str
    service: str
    version: str


# ---------------------------------------------------------------------------
# Resolvers
# ---------------------------------------------------------------------------

def _verify_token(authorization: Optional[str]) -> None:
    expected = os.environ.get("API_KEY")
    if not expected:
        raise PermissionError("API_KEY not configured on server.")
    if not authorization or not authorization.startswith("Bearer "):
        raise PermissionError("Missing or malformed Authorization header.")
    if authorization.removeprefix("Bearer ").strip() != expected:
        raise PermissionError("Invalid token.")


def _call_claude(payload: ScreenInput) -> dict:
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
    raw = message.content[0].text.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        # Surface as a clean GraphQL error instead of an opaque 500.
        raise ValueError(f"Model did not return valid JSON ({exc}). Raw output: {raw[:500]}")


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

@strawberry.type
class Query:
    @strawberry.field
    def health(self) -> HealthStatus:
        return HealthStatus(
            status="ok",
            service="animarh-screener-graphql",
            version="1.0.0",
        )


@strawberry.type
class Mutation:
    @strawberry.mutation
    def screen_candidate(self, input: ScreenInput, info: Info) -> ScreenResult:
        # Auth via Bearer header (read from request context)
        request = info.context["request"]
        _verify_token(request.headers.get("authorization"))

        data = _call_claude(input)
        return ScreenResult(
            candidate=input.candidate_name,
            fit_score=data["fit_score"],
            rating=data["rating"],
            dealbreakers=data.get("dealbreakers", []),
            strengths=data.get("strengths", []),
            gaps=data.get("gaps", []),
            recommendation=data["recommendation"],
            reasoning=data["reasoning"],
        )


schema = strawberry.Schema(query=Query, mutation=Mutation)
graphql_app = GraphQLRouter(schema)

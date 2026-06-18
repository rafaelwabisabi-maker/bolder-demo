# SPEC — `/screen` endpoint

Spec-Driven Development: this is the spec the agent built against. The feature was
defined here *first*; the agent implemented it; the test suite verifies each
acceptance criterion below. Spec → implementation → test, in that order.

## Problem

Given a candidate summary and a role's requirements, return a structured,
machine-readable fit assessment — the same primitive a recruiter runs by hand,
done by Claude, behind an auth boundary so it can be exposed as a service.

## Interface

`POST /screen` — auth required (Bearer token).

**Request**
```json
{ "candidate_name": "string",
  "candidate_summary": "string (2-3 sentences from CV/LinkedIn)",
  "role_requirements": "string (what the client wants)" }
```

**Response** (`200`)
```json
{ "candidate": "string",
  "fit_score": "int 0-10",
  "rating": "A | A- | B+ | B | DISCARD",
  "dealbreakers": ["string"],
  "strengths": ["string"],
  "gaps": ["string"],
  "recommendation": "ADVANCE | HOLD | DISCARD",
  "reasoning": "string (2-3 sentences)" }
```

`GET /health` — public, no auth, liveness only.

## Behavior rules

1. **Rating scale is fixed:** A = 8–10, A- = 6.5–7.9, B+ = 5.5–6.4, B = 4–5.4, DISCARD < 4.
2. **Auth is mandatory on `/screen`:** Bearer token compared to the `API_KEY` env var.
3. **Failures are explicit, never silent:**
   - missing/malformed `Authorization` → `401`
   - wrong token → `403`
   - server misconfigured (no `API_KEY` set) → `500` with a clear message
   - model returns anything that isn't the expected JSON → `502` (not an opaque `500` stack trace), with the raw output included for debugging.
4. **The model is never trusted blindly.** Its output is parsed and validated against the response schema before anything is returned.

## Non-goals (deliberately out of scope)

- **No persistence.** Stateless by design; persistence belongs to the parent system.
- **No testing of the model's *judgment*.** We test the system around the model (auth, parsing, failure handling), not whether Claude's score is "right" — that isn't a deterministic unit-test target.
- **No rate limiting / quotas.** Belongs at the gateway, not here.

## Acceptance criteria → tests

Each criterion is pinned by a test in [`tests/test_main.py`](./tests/test_main.py). This
is the SDD contract: a criterion without a test isn't done.

| # | Acceptance criterion | Test |
|---|----------------------|------|
| 1 | `GET /health` is public and returns `200` | `test_health_is_public` |
| 2 | `/screen` with no `Authorization` header → `401` | `test_screen_missing_auth_401` |
| 3 | `/screen` with a wrong token → `403` | `test_screen_wrong_token_403` |
| 4 | Valid request + valid model JSON → `200` with the structured result | `test_screen_happy_path` |
| 5 | Model returns non-JSON → `502` (clean), not `500` | `test_screen_non_json_returns_502` |

Run them: `python -m pytest -q` → **9 passed** (the 5 above plus the
`candidates.json` → Postgres field-mapping tests in `test_migrate.py`).

## How this was built

1. Wrote this spec.
2. Directed Claude Code to implement `main.py` against it.
3. Wrote a test per acceptance criterion; ran the suite; iterated until green.
4. The [governance layer](./governance) ran throughout, blocking any destructive
   command the agent might have attempted.

The spec is the source of truth. If the code and this file disagree, the spec is
wrong or the code is — and one of them gets fixed, not quietly tolerated.

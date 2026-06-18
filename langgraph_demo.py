"""
langgraph_demo.py — Multi-stage candidate triage as a LangGraph state machine.

Demonstrates LangGraph fluency with a real domain (recruitment triage), not a toy.
Three nodes: triage → score → decide. Each node has explicit inputs/outputs;
state mutations are auditable. Graph visualization via .get_graph().draw_mermaid().

The orchestration patterns mirror the multi-agent loop I run in production
(plan → implement → verify → improve), expressed here as a typed Python state
machine: explicit nodes, conditional routing, and auditable state transitions.

Run:
    pip install langgraph anthropic
    export ANTHROPIC_API_KEY=sk-ant-...
    python3 langgraph_demo.py
"""
from __future__ import annotations

import json
import os
from typing import Literal, TypedDict

import anthropic
from langgraph.graph import END, StateGraph

# ---------------------------------------------------------------------------
# Typed state — every node reads + mutates this
# ---------------------------------------------------------------------------

class TriageState(TypedDict):
    candidate_name: str
    candidate_summary: str
    role_requirements: str
    # Filled by triage node
    triage_passes: bool
    triage_reason: str
    # Filled by score node
    fit_score: int
    rating: str
    strengths: list[str]
    gaps: list[str]
    # Filled by decide node
    recommendation: Literal["ADVANCE", "HOLD", "DISCARD"]
    reasoning: str


# ---------------------------------------------------------------------------
# Claude helper (Haiku for speed, swap to Sonnet for harder calls)
# ---------------------------------------------------------------------------

def _claude_json(prompt: str, model: str = "claude-haiku-4-5", max_tokens: int = 512) -> dict:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    msg = client.messages.create(
        model=model, max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return json.loads(msg.content[0].text.strip())


# ---------------------------------------------------------------------------
# Node 1: Triage — fast YES/NO gate. Cheap model. Filters obvious mismatches.
# ---------------------------------------------------------------------------

def node_triage(state: TriageState) -> dict:
    prompt = f"""Triage this candidate against the role. ONE-PASS YES/NO gate, no nuance yet.

ROLE: {state['role_requirements']}
CANDIDATE: {state['candidate_summary']}

Return ONLY JSON:
{{"passes": true|false, "reason": "<one sentence>"}}

Pass = candidate has the bare minimum to be worth deeper scoring.
Fail = obvious dealbreaker (wrong domain, wrong country, missing must-have)."""
    result = _claude_json(prompt)
    return {"triage_passes": result["passes"], "triage_reason": result["reason"]}


# ---------------------------------------------------------------------------
# Node 2: Score — only runs if triage passed. Detailed scoring, anchored.
# ---------------------------------------------------------------------------

def node_score(state: TriageState) -> dict:
    prompt = f"""Score this candidate against the role. Detailed pass.

ROLE: {state['role_requirements']}
CANDIDATE: {state['candidate_summary']}

Return ONLY JSON:
{{
  "fit_score": <0-10>,
  "rating": <"A"|"A-"|"B+"|"B"|"DISCARD">,
  "strengths": [<2-4 specific items from the candidate summary>],
  "gaps": [<1-3 honest gaps>]
}}

Rating: A=8-10, A-=6.5-7.9, B+=5.5-6.4, B=4-5.4, DISCARD<4."""
    result = _claude_json(prompt)
    return {
        "fit_score": result["fit_score"],
        "rating": result["rating"],
        "strengths": result["strengths"],
        "gaps": result["gaps"],
    }


# ---------------------------------------------------------------------------
# Node 3: Decide — strategic call (advance / hold / discard) + reasoning.
# ---------------------------------------------------------------------------

def node_decide(state: TriageState) -> dict:
    prompt = f"""Make a final routing decision based on the score and gaps.

CANDIDATE: {state['candidate_name']}
SCORE: {state['fit_score']}/10 ({state['rating']})
STRENGTHS: {state['strengths']}
GAPS: {state['gaps']}

Return ONLY JSON:
{{
  "recommendation": <"ADVANCE"|"HOLD"|"DISCARD">,
  "reasoning": <2-3 sentences explaining the decision>
}}

ADVANCE = present to client now.
HOLD = needs one more conversation or info before deciding.
DISCARD = stop investing time."""
    result = _claude_json(prompt)
    return {"recommendation": result["recommendation"], "reasoning": result["reasoning"]}


def node_discard_at_triage(state: TriageState) -> dict:
    """Short-circuit when triage fails — skip scoring, write a clean discard."""
    return {
        "fit_score": 0,
        "rating": "DISCARD",
        "strengths": [],
        "gaps": [state["triage_reason"]],
        "recommendation": "DISCARD",
        "reasoning": f"Triage gate: {state['triage_reason']}",
    }


# ---------------------------------------------------------------------------
# Conditional routing: triage decides what runs next
# ---------------------------------------------------------------------------

def route_after_triage(state: TriageState) -> str:
    return "score" if state["triage_passes"] else "discard"


# ---------------------------------------------------------------------------
# Build the graph
# ---------------------------------------------------------------------------

def build_graph():
    g = StateGraph(TriageState)
    g.add_node("triage", node_triage)
    g.add_node("score", node_score)
    g.add_node("decide", node_decide)
    g.add_node("discard", node_discard_at_triage)

    g.set_entry_point("triage")
    g.add_conditional_edges("triage", route_after_triage,
                            {"score": "score", "discard": "discard"})
    g.add_edge("score", "decide")
    g.add_edge("decide", END)
    g.add_edge("discard", END)
    return g.compile()


# ---------------------------------------------------------------------------
# Demo run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    graph = build_graph()

    initial: TriageState = {
        "candidate_name": "Ana Lima",
        "candidate_summary": "12 years in manufacturing operations. Last role: Production Manager at a 400-person plastics plant (ISO 9001). Managed 3 shifts, reduced scrap rate by 18%. CLT preferred. São Paulo state.",
        "role_requirements": "Gerente de Produção for injection molding plant, 200+ headcount, 5+ years managing shifts, lean manufacturing experience required. Located in Cajamar SP.",
        "triage_passes": False, "triage_reason": "",
        "fit_score": 0, "rating": "", "strengths": [], "gaps": [],
        "recommendation": "DISCARD", "reasoning": "",
    }

    final = graph.invoke(initial)
    print(json.dumps(final, indent=2, ensure_ascii=False))

    # Optional: visualize the graph
    # print(graph.get_graph().draw_mermaid())

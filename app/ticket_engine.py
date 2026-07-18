"""Legacy compatibility module.

Ticket construction is intentionally owned by Laravel. FastAPI returns eligible
prediction candidates and eligibility evidence only. Existing imports may call
``recommend_tickets`` during a rolling deployment, so the function returns no
packages and exposes eligible candidates as single-match insights.
"""
from __future__ import annotations

from app.schemas import PredictionCandidate


def recommend_tickets(
    league_slug: str,
    candidates: list[PredictionCandidate],
    other_candidates: list[PredictionCandidate] | None = None,
):
    del league_slug, other_candidates
    return [], [candidate for candidate in candidates if candidate.ticket_eligible]

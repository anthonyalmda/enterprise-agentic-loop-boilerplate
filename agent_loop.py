"""
In-memory hierarchical RBAC via Closure Binding.
Ensures the LLM never generates raw SQL and cannot access rows outside the authenticated user's scope.
"""
from dataclasses import dataclass
from functools import partial
from typing import Callable, Dict, Any
import pandas as pd


@dataclass(frozen=True)
class UserSessionScope:
    user_email: str
    self_df: pd.DataFrame
    subtree_df: pd.DataFrame  # Only direct/indirect reportees


def _analyze_my_metrics(session: UserSessionScope) -> Dict[str, Any]:
    return session.self_df.to_dict(orient="records")[0]


def _analyze_team_metrics(session: UserSessionScope, department: str | None = None) -> Dict[str, Any]:
    df = session.subtree_df
    if df.empty:
        return {"error": "No direct or indirect reportees found for your scope."}
    if department:
        df = df[df["department"].str.lower() == department.lower()]
    return {
        "headcount": len(df),
        "records": df[["employee_email", "role", "timebank_hours"]].to_dict(orient="records"),
    }


def build_scoped_tools(session: UserSessionScope) -> Dict[str, Callable]:
    """Binds the pre-filtered session to tool callables before exposing them to the LLM loop."""
    return {
        "analyze_my_metrics": partial(_analyze_my_metrics, session),
        "analyze_team_metrics": partial(_analyze_team_metrics, session),
    }

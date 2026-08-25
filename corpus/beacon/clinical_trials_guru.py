from __future__ import annotations

from typing import Optional, TypedDict

import anthropic
from rich import box
from rich.markdown import Markdown
from rich.panel import Panel
from langgraph.graph import StateGraph, START, END

# Re-exports — backward compat for app.py and any external callers
from config import CTGOV_BASE, INTAKE_MODEL, RESEARCH_MODEL  # noqa: F401
from models import PatientProfile, geocode_zip, haversine_miles  # noqa: F401
from prompts import INTAKE_SYSTEM, RESEARCH_SYSTEM, build_intake_system, lookup_disease_profile  # noqa: F401
from tools import SUBMIT_PROFILE_TOOL, SEARCH_TRIALS_TOOL, IDENTIFY_DISEASE_TOOL, INTAKE_TOOLS, RESEARCH_TOOLS  # noqa: F401
from trials_api import search_trials_api, _flatten_and_rank  # noqa: F401
from agents import run_intake_agent, run_research_agent, intake_greeting, stream_intake_turn, stream_research_agent  # noqa: F401
from _console import console


class BeaconState(TypedDict):
    profile: Optional[PatientProfile]
    analysis: str


def _build_graph(client: anthropic.Anthropic):
    def intake_node(_state: BeaconState) -> BeaconState:
        return {"profile": run_intake_agent(client), "analysis": ""}

    def research_node(state: BeaconState) -> BeaconState:
        analysis = run_research_agent(client, state["profile"])
        console.print()
        console.print(Panel(
            Markdown(analysis),
            title="[bold cyan]BEACON ANALYSIS[/bold cyan]",
            border_style="cyan",
            box=box.DOUBLE_EDGE,
            padding=(1, 2),
        ))
        console.print()
        return {"analysis": analysis}

    graph = StateGraph(BeaconState)
    graph.add_node("intake", intake_node)
    graph.add_node("research", research_node)
    graph.add_edge(START, "intake")
    graph.add_edge("intake", "research")
    graph.add_edge("research", END)
    return graph.compile()


def guru_main(_provider=None):  # _provider kept for backward-compat, unused
    client = anthropic.Anthropic()
    graph = _build_graph(client)
    try:
        graph.invoke({"profile": None, "analysis": ""})
    except (KeyboardInterrupt, EOFError):
        console.print("\n[dim]Goodbye.[/dim]")
        return
    console.print("\n[bold]Goodbye.[/bold] Beacon wishes the patient the best on their journey.")

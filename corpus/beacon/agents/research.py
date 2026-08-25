from __future__ import annotations

import json
from typing import Generator

import anthropic

from agents.eligibility import bulk_parse_and_strip
from beacon_logging import get_logger
from config import RESEARCH_MODEL
from llm import cached_system, cached_tools
from models import PatientProfile
from prompts import RESEARCH_SYSTEM
from tools import RESEARCH_TOOLS
from translations import LANGUAGE_DIRECTIVE
from trials_api import search_trials_api, _flatten_and_rank
from _console import console

_logger = get_logger("agents.research")

_MAX_TRIALS_FOR_LLM = 15

# Fields with no synthesis value once eligibility is parsed; stripping them
# shrinks the tool-result payload significantly (nearest_sites alone is ~250 tokens/trial).
_STRIP_BEFORE_LLM = {
    "summary",       # LLM writes its own plain-language summary
    "conditions",    # patient already knows their disease
    "keywords",
    "min_age", "max_age", "sex", "healthy_volunteers",  # in parsed_criteria after bulk parse
    "std_ages",
    "eligibility",   # raw text; replaced by parsed_criteria for top-5
}


_PHASE_PRIORITY: dict[str, int] = {
    "PHASE4": 1,
    "PHASE3": 2,
    "PHASE2": 3,
    "PHASE1": 4,
    "EARLY_PHASE1": 5,
    "NA": 6,
}


def _phase_rank(trial: dict) -> int:
    """Lower = higher priority. Phase 4 > Phase 3 > ... > EAP > Observational."""
    study_type = trial.get("study_type", "")
    if study_type == "EXPANDED_ACCESS":
        return 7
    if study_type == "OBSERVATIONAL":
        return 8
    phase_str = trial.get("phase", "N/A")
    phases = [p.strip() for p in phase_str.replace(" ", "").split(",") if p.strip()]
    return min((_PHASE_PRIORITY.get(p, 6) for p in phases), default=6)


def _rank_and_slim(trials: list[dict]) -> list[dict]:
    """Sort by phase priority then distance, cap at _MAX_TRIALS_FOR_LLM, strip bloat."""
    ranked = sorted(
        trials,
        key=lambda t: (_phase_rank(t), t.get("closest_site_miles") or float("inf")),
    )
    slimmed = []
    for t in ranked[:_MAX_TRIALS_FOR_LLM]:
        t = {k: v for k, v in t.items() if k not in _STRIP_BEFORE_LLM}
        if "nearest_sites" in t:
            t["nearest_sites"] = t["nearest_sites"][:3]
        if "interventions" in t:
            t["interventions"] = [
                {"type": iv.get("type", ""), "name": iv.get("name", "")}
                for iv in t["interventions"]
            ]
        slimmed.append(t)
    return slimmed


def run_research_agent(client: anthropic.Anthropic, profile: PatientProfile) -> str:
    messages: list[anthropic.types.MessageParam] = [
        {
            "role": "user",
            "content": (
                f"Find clinical trials for this patient:\n\n{profile.summary()}\n\n"
                "Search within the specified radius and rank results by distance."
            ),
        }
    ]

    while True:
        response = client.messages.create(
            model=RESEARCH_MODEL,
            max_tokens=3000,
            system=cached_system(RESEARCH_SYSTEM),
            tools=cached_tools(RESEARCH_TOOLS),
            messages=messages,
        )

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            return next(
                (b.text for b in response.content if b.type == "text"),
                "No analysis produced.",
            )

        tool_results: list[anthropic.types.ToolResultBlockParam] = []
        for block in response.content:
            if block.type != "tool_use" or block.name != "search_clinical_trials":
                continue
            args = block.input
            radius = args.get("radius_miles", profile.radius_miles)
            study_type = args.get("study_type", "INTERVENTIONAL")
            # Enforce patient's phase preference; don't rely on LLM to repeat it.
            # Phase filters only apply to INTERVENTIONAL searches.
            phases = (profile.phases or None) if study_type == "INTERVENTIONAL" else None
            status_msg = (
                f"[cyan]Searching:[/cyan] '[bold]{args['condition']}[/bold]' | "
                f"radius=[bold]{radius}[/bold] mi | "
                f"type=[bold]{study_type}[/bold] | "
                f"phases=[bold]{phases or 'all'}[/bold]"
            )
            try:
                with console.status(status_msg, spinner="dots"):
                    studies = search_trials_api(
                        condition=args["condition"],
                        lat=args["lat"],
                        lon=args["lon"],
                        radius_miles=radius,
                        phases=phases,
                        study_type=study_type,
                    )
                    ranked = _flatten_and_rank(studies, profile.lat, profile.lon)
                    ranked = bulk_parse_and_strip(client, ranked, profile)
                console.print(f"  [green]✓[/green] {len(ranked)} trial(s) found.")
                content = json.dumps(_rank_and_slim(ranked))
                is_error = False
            except Exception as exc:
                console.print(f"[red bold]API error:[/red bold] {exc}")
                content = f"API request failed: {exc}. The ClinicalTrials.gov endpoint may be temporarily unavailable."
                is_error = True
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": content,
                "is_error": is_error,
            })

        messages.append({"role": "user", "content": tool_results})


def stream_research_agent(
    client: anthropic.Anthropic,
    profile: PatientProfile,
) -> Generator[tuple, None, None]:
    """
    Stream the research agent for a given patient profile.

    Yields:
      ("token", str)   — partial text chunk
      ("done", str)    — research complete; the full analysis text (may be empty)
    """
    messages: list[anthropic.types.MessageParam] = [{
        "role": "user",
        "content": (
            f"Find clinical trials for this patient:\n\n{profile.summary()}\n\n"
            "Search within the specified radius and rank results by distance."
        ),
    }]

    while True:
        stream_text = ""
        with client.messages.stream(
            model=RESEARCH_MODEL,
            max_tokens=3000,
            system=cached_system(LANGUAGE_DIRECTIVE[profile.lang] + RESEARCH_SYSTEM),
            tools=cached_tools(RESEARCH_TOOLS),
            messages=messages,
        ) as stream:
            for chunk in stream.text_stream:
                stream_text += chunk
                yield ("token", chunk)
            rresponse = stream.get_final_message()

        messages.append({"role": "assistant", "content": rresponse.content})

        if rresponse.stop_reason == "end_turn":
            yield ("done", stream_text)
            return

        tool_results: list[anthropic.types.ToolResultBlockParam] = []
        for block in rresponse.content:
            if block.type != "tool_use" or block.name != "search_clinical_trials":
                continue
            args = block.input
            radius = args.get("radius_miles", profile.radius_miles)
            study_type = args.get("study_type", "INTERVENTIONAL")
            # Enforce patient's phase preference; don't rely on LLM to repeat it.
            # Phase filters only apply to INTERVENTIONAL searches.
            phases = (profile.phases or None) if study_type == "INTERVENTIONAL" else None
            type_label = {"INTERVENTIONAL": "clinical trials", "EXPANDED_ACCESS": "expanded access programs", "OBSERVATIONAL": "observational studies"}.get(study_type, study_type.lower())
            yield ("status", f"Searching ClinicalTrials.gov for **{args['condition']}** ({type_label}, {radius} mi radius)…")
            try:
                studies = search_trials_api(
                    condition=args["condition"],
                    lat=args["lat"],
                    lon=args["lon"],
                    radius_miles=radius,
                    phases=phases,
                    study_type=study_type,
                )
                ranked = _flatten_and_rank(studies, profile.lat, profile.lon)
                n = len(ranked)
                yield ("status", f"Found **{n}** {type_label} — checking eligibility for the {min(5, n)} closest…")
                ranked = bulk_parse_and_strip(client, ranked, profile)
                yield ("status", "Eligibility analysis complete — generating your report…")
                content = json.dumps(_rank_and_slim(ranked))
                is_error = False
            except Exception as exc:
                content = f"API request failed: {exc}. The ClinicalTrials.gov endpoint may be temporarily unavailable."
                is_error = True
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": content,
                "is_error": is_error,
            })
        messages.append({"role": "user", "content": tool_results})

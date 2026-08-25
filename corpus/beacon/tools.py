from __future__ import annotations

import json
from pathlib import Path

import anthropic

_DATA = Path(__file__).parent / "data" / "tools"


def _load(name: str) -> dict:
    return json.loads((_DATA / f"{name}.json").read_text())


SUBMIT_PROFILE_TOOL: anthropic.types.ToolParam = {
    "name": "submit_profile",
    "description": (
        "Call this when you have collected all required information. "
        "Standardize the disease name to its full medical term."
    ),
    "input_schema": _load("submit_profile"),
}

IDENTIFY_DISEASE_TOOL: anthropic.types.ToolParam = {
    "name": "identify_disease",
    "description": (
        "Call this as soon as you have identified the patient's disease — "
        "either from a direct statement or from symptom description. "
        "The response tells you which benchmark scores to collect for that disease. "
        "Call this before asking any disease-specific questions."
    ),
    "input_schema": _load("identify_disease"),
}

SEARCH_TRIALS_TOOL: anthropic.types.ToolParam = {
    "name": "search_clinical_trials",
    "description": (
        "Search ClinicalTrials.gov for studies within a geographic radius. "
        "Results are pre-ranked by distance from the patient's location. "
        "Call multiple times with different parameters (synonyms, broader radius, "
        "different phases) if initial results are sparse. "
        "Use study_type='EXPANDED_ACCESS' to search for Expanded Access Programs (EAP / compassionate use). "
        "Use study_type='OBSERVATIONAL' to search for observational studies (no experimental treatment assigned)."
    ),
    "input_schema": _load("search_trials"),
}

PARSE_CRITERIA_BULK_TOOL: anthropic.types.ToolParam = {
    "name": "parse_criteria_bulk",
    "description": (
        "Parse raw eligibility criteria text for multiple trials in one call. "
        "For each trial, extract every inclusion and exclusion criterion. "
        "Produce a structured constraint where possible (numeric ranges, enums, comparisons); "
        "set constraint to null for vague, subjective, or compound criteria."
    ),
    "input_schema": _load("parse_criteria_bulk"),
}

PARSE_CRITERIA_TOOL: anthropic.types.ToolParam = {
    "name": "parse_criteria",
    "description": (
        "Parse raw eligibility criteria text into structured criterion objects. "
        "For each criterion, extract a canonical key, inclusion/exclusion type, "
        "and a structured constraint where possible (numeric ranges, enums, comparisons). "
        "Set constraint to null for vague, subjective, or compound criteria that cannot "
        "be expressed as a single structured comparison."
    ),
    "input_schema": _load("parse_criteria"),
}

ASSESS_ELIGIBILITY_TOOL: anthropic.types.ToolParam = {
    "name": "assess_eligibility",
    "description": (
        "Assess whether a patient meets eligibility criteria that cannot be evaluated "
        "deterministically. Only called for criteria where a structured constraint is "
        "unavailable or patient data is missing. "
        "Use verdict 'unknown' when patient data is insufficient — never assume 'pass'. "
        "Confidence is 'medium' or 'low' only; 'high' is reserved for deterministic evaluation."
    ),
    "input_schema": _load("assess_eligibility"),
}

INTAKE_TOOLS: list[anthropic.types.ToolParam] = [SUBMIT_PROFILE_TOOL, IDENTIFY_DISEASE_TOOL]
RESEARCH_TOOLS: list[anthropic.types.ToolParam] = [SEARCH_TRIALS_TOOL]
ELIGIBILITY_TOOLS: list[anthropic.types.ToolParam] = [PARSE_CRITERIA_TOOL, ASSESS_ELIGIBILITY_TOOL]

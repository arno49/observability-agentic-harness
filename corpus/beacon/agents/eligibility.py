from __future__ import annotations

import json
import operator as _op
from pathlib import Path
from typing import Generator

import anthropic

from beacon_logging import get_logger
from config import ELIGIBILITY_MODEL
from models import (
    CriterionAssessment,
    CriterionVerdict,
    EligibilityCriterion,
    ParsedConstraint,
    PatientProfile,
    TrialEligibilityReport,
)
from tools import ASSESS_ELIGIBILITY_TOOL, PARSE_CRITERIA_TOOL, PARSE_CRITERIA_BULK_TOOL

_logger = get_logger("agents.eligibility")

_KEY_MAP: dict[str, str] = json.loads(
    (Path(__file__).parent.parent / "data" / "criterion_keys.json").read_text()
)

_PARSE_SYSTEM = """\
You are a clinical trial eligibility parser. Given raw eligibility criteria text, \
extract every inclusion and exclusion criterion as a structured object.

For each criterion:
- key: a snake_case canonical name that identifies the patient attribute being tested \
  (e.g. age_years, ecog_status, prior_systemic_therapy_lines, egfr_ml_min)
- type: "inclusion" or "exclusion"
- description: a concise plain-English restatement of the requirement the patient must satisfy
- raw_criteria: the verbatim criterion text from the source
- constraint: a structured comparison if the criterion can be expressed as one; null otherwise

Canonical key names — always use these exact strings for the corresponding criteria:
  Any "time since symptom/disease/weakness/condition onset", "disease duration", \
  "duration of symptoms" → key: "symptom_onset_months"  (value in months)
  Any "time since diagnosis", "diagnosed within" → key: "diagnosis_months"  (value in months)
  Age → key: "age_years"  (value in years)
When the trial states a threshold in years for a _months key, keep the value in months \
(e.g. "onset within 2 years" → value: 24, unit: "months").

Express constraints as the condition the patient must meet to qualify:
  "Age 18-75" → {operator: "between", value: [18, 75]}
  "No prior systemic therapy" → {operator: "==", value: 0}
  "ECOG 0 or 1" → {operator: "in", value: [0, 1]}
  "eGFR >= 60 mL/min" → {operator: ">=", value: 60, unit: "mL/min"}
  "Adequate hepatic function per investigator" → null

Set constraint to null for any criterion that is vague, subjective, compound, or \
cannot be expressed as a single comparison against a known patient field.
"""

_ASSESS_SYSTEM = """\
You are a clinical trial eligibility assessor. Given a list of eligibility criteria \
that could not be evaluated deterministically, assess each one against the provided \
patient profile.

Rules:
1. If patient data is missing for a criterion → verdict must be "unknown", never "pass"
2. Confidence is "medium" if the criterion is clear but data is incomplete; \
   "low" if the criterion itself is ambiguous
3. For exclusion criteria: if patient data matches the exclusion condition → verdict is "fail"
4. List every criterion key you could not assess in missing_data_keys
5. Be conservative — when in doubt, use "unknown"
"""


def _resolve_patient_value(
    key: str,
    patient: PatientProfile,
    platform_data: dict | None,
) -> tuple[object, bool]:
    mapped = _KEY_MAP.get(key)
    if mapped is None:
        return None, False
    prefix, field = mapped.split(".", 1)
    if prefix == "patient":
        val = getattr(patient, field, None)
        return val, val is not None
    if prefix == "platform":
        if platform_data is None:
            return None, False
        val = platform_data.get(field)
        return val, val is not None
    return None, False


_OPERATORS = {
    "<=":     _op.le,
    ">=":     _op.ge,
    "==":     _op.eq,
    "!=":     _op.ne,
    "in":     lambda pv, v: pv in v,
    "not_in": lambda pv, v: pv not in v,
    "between": lambda pv, v: v[0] <= pv <= v[1],
}

_MONTHS_KEYS = {"symptom_onset_months", "diagnosis_months"}


def _normalize_to_patient_units(
    key: str, value: object, unit: str | None
) -> tuple[object, str | None]:
    """Convert constraint value to the same unit as the patient field (always months for time keys)."""
    if key in _MONTHS_KEYS and unit == "years":
        if isinstance(value, list):
            return [int(v * 12) for v in value], "months"
        return int(value * 12), "months"
    return value, unit


def _evaluate_deterministic(
    criterion: EligibilityCriterion,
    patient_value: object,
) -> CriterionAssessment:
    c = criterion.constraint
    norm_value, norm_unit = _normalize_to_patient_units(c.key, c.value, c.unit)
    fn = _OPERATORS.get(c.operator)
    try:
        passes = fn(patient_value, norm_value)
    except (TypeError, ValueError):
        passes = False

    verdict = CriterionVerdict.PASS if passes else CriterionVerdict.FAIL
    unit_str = f" {norm_unit}" if norm_unit else ""
    reason = (
        f"Requires {c.operator} {norm_value}{unit_str}; patient value: {patient_value}"
    )
    return CriterionAssessment(
        criterion=criterion,
        verdict=verdict,
        reason=reason,
        patient_value=str(patient_value),
        confidence="high",
    )


def _parse_criteria(client: anthropic.Anthropic, eligibility_text: str) -> list[EligibilityCriterion]:
    if not eligibility_text.strip():
        return []

    response = client.messages.create(
        model=ELIGIBILITY_MODEL,
        max_tokens=4096,
        system=_PARSE_SYSTEM,
        tools=[PARSE_CRITERIA_TOOL],
        tool_choice={"type": "tool", "name": "parse_criteria"},
        messages=[{"role": "user", "content": eligibility_text}],
    )

    tool_use = next((b for b in response.content if b.type == "tool_use"), None)
    if tool_use is None:
        _logger.warning("parse_criteria tool not called", extra={"data": {}})
        return []

    raw_criteria: list[dict] = tool_use.input.get("criteria", [])
    result = []
    for rc in raw_criteria:
        raw_constraint = rc.get("constraint")
        constraint = None
        if raw_constraint:
            constraint = ParsedConstraint(
                key=raw_constraint["key"],
                operator=raw_constraint["operator"],
                value=raw_constraint["value"],
                unit=raw_constraint.get("unit"),
            )
        result.append(EligibilityCriterion(
            key=rc["key"],
            type=rc["type"],
            description=rc["description"],
            raw_criteria=rc["raw_criteria"],
            constraint=constraint,
        ))

    _logger.info(
        "Parsed eligibility criteria",
        extra={"data": {"count": len(result)}},
    )
    return result


def _assess_llm(
    client: anthropic.Anthropic,
    criteria: list[EligibilityCriterion],
    patient: PatientProfile,
    platform_data: dict | None,
) -> list[CriterionAssessment]:
    if not criteria:
        return []

    patient_context = {
        "age_years": patient.age,
        "symptom_onset_months": patient.onset_months,
        "diagnosis_months": patient.diagnosis_months,
        "disease": patient.disease,
    }
    if platform_data:
        patient_context["platform_data"] = platform_data

    criteria_payload = [
        {"key": c.key, "type": c.type, "description": c.description, "raw_criteria": c.raw_criteria}
        for c in criteria
    ]

    user_content = (
        f"Patient profile:\n{json.dumps(patient_context, indent=2)}\n\n"
        f"Criteria to assess:\n{json.dumps(criteria_payload, indent=2)}"
    )

    response = client.messages.create(
        model=ELIGIBILITY_MODEL,
        max_tokens=4096,
        system=_ASSESS_SYSTEM,
        tools=[ASSESS_ELIGIBILITY_TOOL],
        tool_choice={"type": "tool", "name": "assess_eligibility"},
        messages=[{"role": "user", "content": user_content}],
    )

    tool_use = next((b for b in response.content if b.type == "tool_use"), None)
    if tool_use is None:
        _logger.warning("assess_eligibility tool not called", extra={"data": {}})
        return [
            CriterionAssessment(
                criterion=c,
                verdict=CriterionVerdict.UNKNOWN,
                reason="Assessment unavailable",
                patient_value=None,
                confidence="low",
            )
            for c in criteria
        ]

    criterion_by_key = {c.key: c for c in criteria}
    assessments = []
    for a in tool_use.input.get("assessments", []):
        criterion = criterion_by_key.get(a["criterion_key"])
        if criterion is None:
            continue
        assessments.append(CriterionAssessment(
            criterion=criterion,
            verdict=CriterionVerdict(a["verdict"]),
            reason=a["reason"],
            patient_value=a.get("patient_value"),
            confidence=a["confidence"],
        ))

    return assessments


def _compute_overall(assessments: list[CriterionAssessment]) -> CriterionVerdict:
    if any(a.verdict == CriterionVerdict.FAIL for a in assessments):
        return CriterionVerdict.FAIL
    if any(a.verdict == CriterionVerdict.UNKNOWN for a in assessments):
        return CriterionVerdict.UNKNOWN
    return CriterionVerdict.PASS


def run_eligibility_check(
    client: anthropic.Anthropic,
    trial: dict,
    patient: PatientProfile,
    platform_data: dict | None = None,
) -> TrialEligibilityReport:
    nct_id = trial.get("nct_id", "")
    eligibility_text = trial.get("eligibility", "")

    criteria = _parse_criteria(client, eligibility_text)

    deterministic: list[CriterionAssessment] = []
    needs_llm: list[EligibilityCriterion] = []

    for c in criteria:
        if c.constraint is not None:
            patient_value, found = _resolve_patient_value(c.key, patient, platform_data)
            if found:
                deterministic.append(_evaluate_deterministic(c, patient_value))
                continue
        needs_llm.append(c)

    llm_assessments = _assess_llm(client, needs_llm, patient, platform_data)

    all_assessments = deterministic + llm_assessments
    missing_data_keys = [
        a.criterion.key
        for a in llm_assessments
        if a.verdict == CriterionVerdict.UNKNOWN
    ]

    report = TrialEligibilityReport(
        nct_id=nct_id,
        overall_verdict=_compute_overall(all_assessments),
        assessments=all_assessments,
        missing_data_keys=missing_data_keys,
    )

    _logger.info(
        "Eligibility check complete",
        extra={
            "data": {
                "nct_id": nct_id,
                "overall": report.overall_verdict,
                "total": len(all_assessments),
                "deterministic": len(deterministic),
                "llm": len(llm_assessments),
                "missing": missing_data_keys,
            }
        },
    )
    return report


_FIELDS_TO_STRIP_AFTER_PARSE = {"eligibility", "std_ages", "healthy_volunteers"}


def bulk_parse_and_strip(
    client: anthropic.Anthropic,
    trials: list[dict],
    patient: PatientProfile,
    platform_data: dict | None = None,
    top_n: int = 5,
) -> list[dict]:
    """
    One LLM call to parse criteria for top_n trials.
    Applies deterministic assessment (Path A) in code.
    Strips raw eligibility text and redundant fields.
    Research LLM handles Path B (unclear criteria) inline during synthesis.
    """
    to_parse = [t for t in trials[:top_n] if t.get("eligibility", "").strip()]
    rest = trials[top_n:]

    if not to_parse:
        return trials

    payload = [
        {"nct_id": t["nct_id"], "eligibility_text": t["eligibility"]}
        for t in to_parse
    ]
    user_content = (
        f"Parse eligibility criteria for these {len(payload)} trials:\n"
        + json.dumps(payload, indent=2)
    )

    try:
        response = client.messages.create(
            model=ELIGIBILITY_MODEL,
            max_tokens=4096,
            system=_PARSE_SYSTEM,
            tools=[PARSE_CRITERIA_BULK_TOOL],
            tool_choice={"type": "tool", "name": "parse_criteria_bulk"},
            messages=[{"role": "user", "content": user_content}],
        )
        tool_use = next((b for b in response.content if b.type == "tool_use"), None)
        parsed_by_nct: dict[str, list[dict]] = {}
        if tool_use:
            for entry in tool_use.input.get("trials", []):
                parsed_by_nct[entry["nct_id"]] = entry.get("criteria", [])
    except Exception as exc:
        _logger.warning("Bulk parse failed", extra={"data": {"error": str(exc)}})
        parsed_by_nct = {}

    _logger.info(
        "Bulk criteria parse complete",
        extra={"data": {"trials_parsed": len(parsed_by_nct)}},
    )

    for trial in to_parse:
        nct_id = trial["nct_id"]
        raw_criteria = parsed_by_nct.get(nct_id, [])
        criteria: list[EligibilityCriterion] = []
        deterministic_verdicts: list[dict] = []

        for rc in raw_criteria:
            raw_constraint = rc.get("constraint")
            constraint = None
            if raw_constraint:
                constraint = ParsedConstraint(
                    key=raw_constraint["key"],
                    operator=raw_constraint["operator"],
                    value=raw_constraint["value"],
                    unit=raw_constraint.get("unit"),
                )
            c = EligibilityCriterion(
                key=rc["key"],
                type=rc["type"],
                description=rc["description"],
                raw_criteria=rc["raw_criteria"],
                constraint=constraint,
            )
            criteria.append(c)

            if constraint is not None:
                patient_value, found = _resolve_patient_value(c.key, patient, platform_data)
                if found:
                    assessment = _evaluate_deterministic(c, patient_value)
                    deterministic_verdicts.append({
                        "verdict": assessment.verdict.value,
                        "description": c.description,
                        "reason": assessment.reason,
                        "confidence": assessment.confidence,
                        "raw_criteria": c.raw_criteria,
                    })

        trial["parsed_criteria"] = [
            {
                "key": c.key,
                "type": c.type,
                "description": c.description,
                "raw_criteria": c.raw_criteria,
                "constraint": (
                    {
                        "operator": c.constraint.operator,
                        "value": c.constraint.value,
                        "unit": c.constraint.unit,
                    }
                    if c.constraint else None
                ),
            }
            for c in criteria
        ]
        trial["deterministic_verdicts"] = deterministic_verdicts

        for field in _FIELDS_TO_STRIP_AFTER_PARSE:
            trial.pop(field, None)

    return to_parse + rest


def stream_eligibility_check(
    client: anthropic.Anthropic,
    trial: dict,
    patient: PatientProfile,
    platform_data: dict | None = None,
) -> Generator[str, None, None]:
    nct_id = trial.get("nct_id", "")
    yield f"Parsing eligibility criteria for {nct_id}…\n"

    report = run_eligibility_check(client, trial, patient, platform_data)

    verdict_icon = {"pass": "✓", "fail": "✗", "unknown": "!"}
    lines = []
    for a in report.assessments:
        icon = verdict_icon[a.verdict.value]
        lines.append(f"  {icon}  {a.criterion.description} — {a.reason}")

    lines.append("")
    overall_label = {
        CriterionVerdict.PASS:    "Eligible",
        CriterionVerdict.FAIL:    "Not eligible",
        CriterionVerdict.UNKNOWN: "Likely eligible — confirm missing info",
    }[report.overall_verdict]
    lines.append(f"  Overall: {overall_label}")

    if report.missing_data_keys:
        lines.append(f"  Missing information: {', '.join(report.missing_data_keys)}")

    yield "\n".join(lines) + "\n"

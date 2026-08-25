from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Union

import httpx


@dataclass
class PatientProfile:
    disease: str
    age: int
    onset_months: int
    diagnosis_months: int = 0
    benchmarks: dict[str, str] = field(default_factory=dict)
    zip_code: str = ""
    country_code: str = "US"
    lat: float = 0.0
    lon: float = 0.0
    radius_miles: int = 20
    phases: list[str] = field(default_factory=list)
    include_eap: bool = False
    include_observational: bool = False
    lang: str = "en"

    def summary(self) -> str:
        lines = [
            f"Disease: {self.disease}",
            f"Age: {self.age}",
            f"Symptom onset: {self.onset_months} months ago",
            f"Formal diagnosis: {self.diagnosis_months} months ago",
        ]
        if self.benchmarks:
            lines.append("Benchmarks: " + ", ".join(f"{k}={v}" for k, v in self.benchmarks.items()))
        lines.append(
            f"Location: ZIP {self.zip_code}, {self.country_code} "
            f"(lat={self.lat:.4f}, lon={self.lon:.4f})"
        )
        lines.append(f"Search radius: {self.radius_miles} miles")
        if self.phases:
            def _phase_label(p: str) -> str:
                if p == "0":
                    return "Early Phase 1"
                if p == "na":
                    return "Not Applicable"
                return f"Phase {p}"
            labels = [_phase_label(p) for p in self.phases]
            lines.append(f"Phases: {', '.join(labels)}")
        interests = ["Clinical trials"]
        if self.include_observational:
            interests.append("Observational studies")
        if self.include_eap:
            interests.append("Expanded Access Programs (EAP)")
        lines.append(f"Study type interest: {', '.join(interests)}")
        return "\n".join(lines)


class CriterionVerdict(str, Enum):
    PASS    = "pass"
    FAIL    = "fail"
    UNKNOWN = "unknown"


@dataclass
class ParsedConstraint:
    key: str
    operator: str       # "<=", ">=", "==", "!=", "in", "not_in", "between"
    value: Union[int, float, str, list]
    unit: str | None


@dataclass
class EligibilityCriterion:
    key: str
    type: str           # "inclusion" | "exclusion"
    description: str
    raw_criteria: str   # verbatim criterion text preserved for patient transparency
    constraint: ParsedConstraint | None


@dataclass
class CriterionAssessment:
    criterion: EligibilityCriterion
    verdict: CriterionVerdict
    reason: str
    patient_value: str | None
    confidence: str     # "high" (deterministic) | "medium" | "low" (LLM)


@dataclass
class TrialEligibilityReport:
    nct_id: str
    overall_verdict: CriterionVerdict
    assessments: list[CriterionAssessment]
    missing_data_keys: list[str]


def geocode_zip(zip_code: str, country_code: str = "US") -> tuple[float, float]:
    resp = httpx.get(
        "https://nominatim.openstreetmap.org/search",
        params={"postalcode": zip_code, "country": country_code, "format": "json", "limit": 1},
        headers={"User-Agent": "Beacon-ClinicalTrialFinder/1.0"},
        timeout=10,
    )
    resp.raise_for_status()
    results = resp.json()
    if not results:
        raise ValueError(f"Cannot geocode ZIP {zip_code!r} in {country_code!r}")
    return float(results[0]["lat"]), float(results[0]["lon"])


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 3958.8
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    dφ, dλ = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dφ / 2) ** 2 + math.cos(φ1) * math.cos(φ2) * math.sin(dλ / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

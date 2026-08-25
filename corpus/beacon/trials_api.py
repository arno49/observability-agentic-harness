from __future__ import annotations

import time

import httpx

from beacon_logging import get_logger
from config import CTGOV_BASE
from models import haversine_miles
from _console import console

_logger = get_logger("trials_api")


def search_trials_api(
    condition: str,
    lat: float,
    lon: float,
    radius_miles: int = 100,
    phases: list[str] | None = None,
    study_type: str = "INTERVENTIONAL",
) -> list[dict]:
    is_eap = study_type == "EXPANDED_ACCESS"
    is_observational = study_type == "OBSERVATIONAL"
    params: dict[str, str | int] = {
        "query.cond": condition,
        "filter.overallStatus": "AVAILABLE" if is_eap else "RECRUITING",
        "filter.geo": f"distance({lat},{lon},{radius_miles}mi)",
        "pageSize": 1000,
        "format": "json",
    }
    # aggFilters supports comma-separated keys (e.g. "studyType:exp,phase:3 4").
    # RECRUITING status already excludes EAPs, so studyType:int is only needed
    # when no phase filter is applied. studyType:int returns all phases including N/A.
    # Observational studies use studyType:obs; phases don't apply to them.
    #
    # Case matrix:
    #   EAP only                  → studyType:exp
    #   EAP + specific phases     → studyType:exp,phase:X Y  (combine both filters)
    #   EAP + all phases          → studyType:exp  (no phase filter needed)
    #   Interventional, specific  → phase:X Y
    #   Interventional, all/NA    → studyType:int  (returns NA trials too)
    if is_eap:
        numbered = [p for p in (phases or []) if p != "na"]
        if numbered:
            params["aggFilters"] = "studyType:exp,phase:" + " ".join(numbered)
        else:
            params["aggFilters"] = "studyType:exp"
    elif is_observational:
        params["aggFilters"] = "studyType:obs"
    elif phases:
        # Exclude "na" from the phase filter — N/A trials have no phase value to match on;
        # they appear naturally when no phase filter is applied (studyType:int branch).
        numbered = [p for p in phases if p != "na"]
        if numbered:
            params["aggFilters"] = "phase:" + " ".join(numbered)
        else:
            params["aggFilters"] = "studyType:int"
    else:
        params["aggFilters"] = "studyType:int"

    _logger.info(
        "ClinicalTrials.gov API request",
        extra={"data": {"endpoint": CTGOV_BASE, "params": dict(params)}},
    )

    all_studies: list[dict] = []
    while True:
        for attempt in range(3):
            try:
                resp = httpx.get(CTGOV_BASE, params=params, timeout=30)
                resp.raise_for_status()
                body = resp.json()
                break
            except httpx.HTTPError as exc:
                if attempt == 2:
                    raise
                wait = 2 ** attempt
                console.print(f"[yellow]API warning:[/yellow] {exc} — retrying in {wait}s (attempt {attempt + 1}/3)…")
                time.sleep(wait)
        page_studies = body.get("studies", [])
        all_studies.extend(page_studies)
        next_token = body.get("nextPageToken")
        _logger.debug(
            "ClinicalTrials.gov API page received",
            extra={"data": {"page_count": len(page_studies), "has_next_page": bool(next_token)}},
        )
        if not next_token:
            break
        params["pageToken"] = next_token

    _logger.info(
        "ClinicalTrials.gov API response complete",
        extra={"data": {"total_studies": len(all_studies)}},
    )
    return all_studies


def _flatten_and_rank(studies: list[dict], patient_lat: float, patient_lon: float) -> list[dict]:
    result = []
    for study in studies:
        proto = study.get("protocolSection", {})
        id_mod = proto.get("identificationModule", {})
        desc_mod = proto.get("descriptionModule", {})
        elig_mod = proto.get("eligibilityModule", {})
        contacts_mod = proto.get("contactsLocationsModule", {})
        sponsor_mod = proto.get("sponsorCollaboratorsModule", {})
        design_mod = proto.get("designModule", {})
        conditions_mod = proto.get("conditionsModule", {})
        arms_mod = proto.get("armsInterventionsModule", {})

        central_contacts = contacts_mod.get("centralContacts", [])
        central_phone = next((c.get("phone", "") for c in central_contacts if c.get("phone")), "")
        central_email = next((c.get("email", "") for c in central_contacts if c.get("email")), "")

        officials = contacts_mod.get("overallOfficials", [])
        pi = next(
            (o.get("name", "") for o in officials if o.get("role") == "PRINCIPAL_INVESTIGATOR"),
            officials[0].get("name", "") if officials else "",
        )

        sites_with_dist: list[tuple[float, dict]] = []
        for loc in contacts_mod.get("locations", []):
            geo = loc.get("geoPoint", {})
            if geo.get("lat") and geo.get("lon"):
                d = haversine_miles(patient_lat, patient_lon, geo["lat"], geo["lon"])
                loc_contacts = loc.get("contacts", [])
                loc_phone = next((c.get("phone", "") for c in loc_contacts if c.get("phone")), "")
                loc_email = next((c.get("email", "") for c in loc_contacts if c.get("email")), "")
                sites_with_dist.append((d, {
                    "label": (
                        f"{loc.get('facility', '').strip()} — "
                        f"{loc.get('city', '')}, "
                        f"{loc.get('state', loc.get('country', ''))} "
                        f"({d:.0f} mi)"
                    ),
                    "facility": loc.get("facility", "").strip(),
                    "city": loc.get("city", ""),
                    "state": loc.get("state", loc.get("country", "")),
                    "distance_miles": round(d, 1),
                    "phone": loc_phone or central_phone,
                    "email": loc_email or central_email,
                }))
        sites_with_dist.sort(key=lambda x: x[0])

        closest_dist = sites_with_dist[0][0] if sites_with_dist else None
        result.append({
            "nct_id": id_mod.get("nctId", ""),
            "title": id_mod.get("briefTitle", ""),
            "phase": ", ".join(design_mod.get("phases", [])) or "N/A",
            "sponsor": sponsor_mod.get("leadSponsor", {}).get("name", ""),
            "principal_investigator": pi,
            "contact_phone": central_phone,
            "contact_email": central_email,
            "summary": desc_mod.get("briefSummary", ""),
            "eligibility": elig_mod.get("eligibilityCriteria", ""),
            "min_age": elig_mod.get("minimumAge", ""),
            "max_age": elig_mod.get("maximumAge", ""),
            "sex": elig_mod.get("sex", "ALL"),
            "healthy_volunteers": elig_mod.get("healthyVolunteers", ""),
            "std_ages": elig_mod.get("stdAges", []),
            "study_type": design_mod.get("studyType", ""),
            "enrollment": design_mod.get("enrollmentInfo", {}).get("count"),
            "conditions": conditions_mod.get("conditions", []),
            "keywords": conditions_mod.get("keywords", []),
            "interventions": [
                {
                    "type": iv.get("type", ""),
                    "name": iv.get("name", ""),
                    "description": iv.get("description", ""),
                }
                for iv in arms_mod.get("interventions", [])
            ],
            "closest_site_miles": round(closest_dist, 1) if closest_dist is not None else None,
            "nearest_sites": [info for _, info in sites_with_dist[:5]],
        })

    result.sort(key=lambda x: x["closest_site_miles"] if x["closest_site_miles"] is not None else float("inf"))
    return result

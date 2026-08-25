from __future__ import annotations

import datetime
import json
from dataclasses import asdict
from typing import Generator

import anthropic
from rich.panel import Panel
from rich.text import Text

from beacon_logging import get_logger
from config import INTAKE_MODEL
from llm import cached_system, cached_tools
from models import PatientProfile, geocode_zip
from prompts import INTAKE_SYSTEM, lookup_disease_profile
from tools import INTAKE_TOOLS
from translations import LANGUAGE_DIRECTIVE
from _console import console

_logger = get_logger("agents.intake")


def _months_from_date(date_str: str) -> int:
    """Convert YYYY-MM string to elapsed months from today. Returns 0 on parse failure."""
    try:
        year, month = int(date_str[:4]), int(date_str[5:7])
        today = datetime.date.today()
        return (today.year - year) * 12 + (today.month - month)
    except (ValueError, IndexError):
        return 0


def _resolve_months(data: dict, date_key: str, months_key: str) -> int:
    """Prefer date string for exact computation; fall back to LLM-supplied integer."""
    if data.get(date_key):
        return _months_from_date(data[date_key])
    return data.get(months_key) or 0


def run_intake_agent(client: anthropic.Anthropic) -> PatientProfile:
    today = datetime.date.today().strftime("%B %d, %Y")

    console.print()
    console.print(Panel(
        Text("Beacon — Rare Disease Clinical Trial Finder", justify="center", style="bold cyan"),
        border_style="cyan",
        padding=(1, 4),
    ))

    messages: list[anthropic.types.MessageParam] = [
        {"role": "user", "content": "Please begin."}
    ]

    while True:
        response = client.messages.create(
            model=INTAKE_MODEL,
            max_tokens=1024,
            system=cached_system(f"Today's date is {today}.\n\n" + INTAKE_SYSTEM),
            tools=cached_tools(INTAKE_TOOLS),
            messages=messages,
        )

        text = next((b.text for b in response.content if b.type == "text"), "")
        if text:
            console.print(f"\n[bold cyan]Beacon:[/bold cyan] {text}")

        identify_block = next(
            (b for b in response.content if b.type == "tool_use" and b.name == "identify_disease"),
            None,
        )
        submit_block = next(
            (b for b in response.content if b.type == "tool_use" and b.name == "submit_profile"),
            None,
        )

        if identify_block:
            disease = lookup_disease_profile(identify_block.input["standardized_name"])
            tool_result = json.dumps({
                "benchmarks_to_collect": disease["benchmarks"] if disease else [],
                "message": (
                    f"Collect these benchmarks for {disease['full_name']}"
                    if disease else "Disease not in registry — skip benchmark questions."
                ),
            })
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": [{
                "type": "tool_result",
                "tool_use_id": identify_block.id,
                "content": tool_result,
            }]})
            continue

        if submit_block:
            data = submit_block.input
            try:
                with console.status("[cyan]Geocoding location…[/cyan]", spinner="dots"):
                    lat, lon = geocode_zip(data["zip_code"], data.get("country_code", "US"))
            except Exception as exc:
                console.print(f"[yellow]Warning:[/yellow] Geocoding failed ({exc}) — coordinates set to 0,0.")
                lat, lon = 0.0, 0.0
            profile = PatientProfile(
                disease=data["disease"],
                age=data["age"],
                onset_months=_resolve_months(data, "onset_date", "onset_months"),
                diagnosis_months=_resolve_months(data, "diagnosis_date", "diagnosis_months"),
                benchmarks=data.get("benchmarks") or {},
                zip_code=data["zip_code"],
                country_code=data.get("country_code", "US"),
                lat=lat,
                lon=lon,
                radius_miles=data.get("radius_miles", 20),
                phases=data.get("phases") or [],
                include_eap=data.get("include_eap", False),
                include_observational=data.get("include_observational", False),
            )
            _logger.info(
                "Patient intake complete (CLI)",
                extra={"data": {"intake_summary": asdict(profile)}},
            )
            return profile

        messages.append({"role": "assistant", "content": response.content})
        user_input = input("\nYou: ").strip() or "(no response)"
        messages.append({"role": "user", "content": user_input})


def intake_greeting(client: anthropic.Anthropic, lang: str = "en") -> tuple[str, list]:
    """Run the opening intake turn (blocking). Returns (greeting_text, initial_messages)."""
    today = datetime.date.today().strftime("%B %d, %Y")
    system = f"Today's date is {today}.\n\n" + LANGUAGE_DIRECTIVE[lang] + INTAKE_SYSTEM
    messages: list[anthropic.types.MessageParam] = [{"role": "user", "content": "Please begin."}]
    response = client.messages.create(
        model=INTAKE_MODEL,
        max_tokens=1024,
        system=cached_system(system),
        tools=cached_tools(INTAKE_TOOLS),
        messages=messages,
    )
    text = next((b.text for b in response.content if b.type == "text"), "")
    return text, messages + [{"role": "assistant", "content": response.content}]


def stream_intake_turn(
    client: anthropic.Anthropic,
    messages: list[anthropic.types.MessageParam],
    lang: str = "en",
) -> Generator[tuple, None, None]:
    """
    Stream one user turn of the intake conversation.

    Yields:
      ("token", str)                              — partial text chunk
      ("reset_stream",)                           — identify_disease handled; clear token buffer
      ("text", str, list)                         — model responded with text; updated messages
      ("profile", PatientProfile, list)           — profile submitted; updated messages
    """
    today = datetime.date.today().strftime("%B %d, %Y")
    system = f"Today's date is {today}.\n\n" + LANGUAGE_DIRECTIVE[lang] + INTAKE_SYSTEM
    new_msgs = list(messages)

    while True:
        intake_text = ""
        with client.messages.stream(
            model=INTAKE_MODEL,
            max_tokens=1024,
            system=cached_system(system),
            tools=cached_tools(INTAKE_TOOLS),
            messages=new_msgs,
        ) as stream:
            for chunk in stream.text_stream:
                intake_text += chunk
                yield ("token", chunk)
            response = stream.get_final_message()

        intake_text = intake_text or next(
            (b.text for b in response.content if b.type == "text"), ""
        )

        identify_block = next(
            (b for b in response.content if b.type == "tool_use" and b.name == "identify_disease"),
            None,
        )
        submit_block = next(
            (b for b in response.content if b.type == "tool_use" and b.name == "submit_profile"),
            None,
        )

        if identify_block:
            disease = lookup_disease_profile(identify_block.input["standardized_name"])
            tool_result = json.dumps({
                "benchmarks_to_collect": disease["benchmarks"] if disease else [],
                "message": (
                    f"Collect these benchmarks for {disease['full_name']}"
                    if disease else "Disease not in registry — skip benchmark questions."
                ),
            })
            new_msgs = new_msgs + [
                {"role": "assistant", "content": response.content},
                {"role": "user", "content": [{
                    "type": "tool_result",
                    "tool_use_id": identify_block.id,
                    "content": tool_result,
                }]},
            ]
            yield ("reset_stream",)
            continue

        new_msgs = new_msgs + [{"role": "assistant", "content": response.content}]

        if submit_block:
            data = submit_block.input
            try:
                lat, lon = geocode_zip(data["zip_code"], data.get("country_code", "US"))
            except Exception:
                lat, lon = 0.0, 0.0
            profile = PatientProfile(
                disease=data["disease"],
                age=data["age"],
                onset_months=_resolve_months(data, "onset_date", "onset_months"),
                diagnosis_months=_resolve_months(data, "diagnosis_date", "diagnosis_months"),
                benchmarks=data.get("benchmarks") or {},
                zip_code=data["zip_code"],
                country_code=data.get("country_code", "US"),
                lat=lat,
                lon=lon,
                radius_miles=data.get("radius_miles", 20),
                phases=data.get("phases") or [],
                include_eap=data.get("include_eap", False),
                include_observational=data.get("include_observational", False),
                lang=lang,
            )
            yield ("profile", profile, new_msgs)
            return

        yield ("text", intake_text, new_msgs)
        return

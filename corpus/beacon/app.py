from __future__ import annotations

import dataclasses
import re
from typing import Generator

import anthropic
import gradio as gr
from beacon_logging import get_logger
from dotenv import load_dotenv

from agents.intake import intake_greeting, stream_intake_turn
from agents.research import stream_research_agent
from models import PatientProfile
from translations import LANGUAGES, UI

load_dotenv()

_logger = get_logger("app")

_VERDICT_STYLE = {
    "✓": "background:#22c55e;color:#fff;padding:2px 10px;border-radius:12px;font-weight:700;",
    "✗": "background:#ef4444;color:#fff;padding:2px 10px;border-radius:12px;font-weight:700;",
    "!": "background:#eab308;color:#fff;padding:2px 10px;border-radius:12px;font-weight:700;",
}

_VERDICT_RE = re.compile(r"(?m)^(\s*)(✓|✗|!)\s")


def _colorize(text: str) -> str:
    def _replace(m: re.Match) -> str:
        symbol = m.group(2)
        style = _VERDICT_STYLE[symbol]
        return f'{m.group(1)}<span style="{style}">{symbol}</span> '
    return _VERDICT_RE.sub(_replace, text)


def initialize(lang: str = "en"):
    client = anthropic.Anthropic()
    text, msgs = intake_greeting(client, lang)
    chat = [{"role": "assistant", "content": text}]
    return chat, msgs, None, "intake"


def respond(
    user_msg: str,
    chat_history: list,
    intake_msgs: list,
    profile: PatientProfile | None,
    phase: str,
    lang: str,
) -> Generator:
    if not user_msg.strip() or phase == "done":
        yield chat_history, intake_msgs, profile, phase, gr.update(), gr.update()
        return

    t = UI[lang]
    client = anthropic.Anthropic()

    chat_history = chat_history + [{"role": "user", "content": user_msg}]
    new_intake_msgs = intake_msgs + [{"role": "user", "content": user_msg}]
    yield chat_history, intake_msgs, profile, phase, gr.update(value=""), gr.update()

    intake_text = ""
    for event in stream_intake_turn(client, new_intake_msgs, lang):
        if event[0] == "token":
            intake_text += event[1]
            yield (
                chat_history + [{"role": "assistant", "content": intake_text}],
                intake_msgs, profile, phase, gr.update(), gr.update(),
            )
        elif event[0] == "reset_stream":
            intake_text = ""
        elif event[0] == "text":
            _, full_text, updated_msgs = event
            chat_history = chat_history + [{"role": "assistant", "content": full_text}]
            yield (
                chat_history, updated_msgs, profile, "intake",
                gr.update(interactive=True), gr.update(),
            )
            return
        elif event[0] == "profile":
            _, new_profile, updated_msgs = event
            _logger.info(
                "Patient intake complete (web)",
                extra={"data": {"intake_summary": dataclasses.asdict(new_profile)}},
            )
            if intake_text:
                chat_history = chat_history + [{"role": "assistant", "content": intake_text}]
            chat_history = chat_history + [{"role": "assistant", "content": t["status_searching"]}]
            yield (
                chat_history, updated_msgs, new_profile, "researching",
                gr.update(interactive=False, placeholder=t["searching"]),
                gr.update(visible=False),
            )

            stream_text = ""
            for rev in stream_research_agent(client, new_profile):
                if rev[0] == "token":
                    stream_text += rev[1]
                    yield (
                        chat_history + [{"role": "assistant", "content": _colorize(stream_text)}],
                        updated_msgs, new_profile, "researching",
                        gr.update(interactive=False, placeholder=t["searching"]),
                        gr.update(visible=False),
                    )
                elif rev[0] == "status":
                    yield (
                        chat_history + [{"role": "assistant", "content": rev[1]}],
                        updated_msgs, new_profile, "researching",
                        gr.update(interactive=False, placeholder=t["searching"]),
                        gr.update(visible=False),
                    )
                elif rev[0] == "done":
                    analysis = _colorize(rev[1] or t["no_analysis"])
                    chat_history = chat_history + [{"role": "assistant", "content": analysis}]
                    yield (
                        chat_history, updated_msgs, new_profile, "done",
                        gr.update(interactive=False, placeholder=t["search_complete"]),
                        gr.update(visible=True),
                    )
            return


def change_language(lang: str):
    t = UI[lang]
    chat, msgs, _, phase = initialize(lang)
    return (
        chat, msgs, None, phase,
        gr.update(value=t["heading"]),
        gr.update(placeholder=t["placeholder"], interactive=True),
        gr.update(value=t["send"]),
        gr.update(value=t["new_search"], visible=False),
        lang,
    )


with gr.Blocks(title=UI["en"]["page_title"]) as demo:
    heading_md = gr.Markdown(UI["en"]["heading"])

    with gr.Row():
        gr.Markdown("")  # spacer
        lang_dropdown = gr.Dropdown(
            choices=[(label, code) for code, label in LANGUAGES.items()],
            value="en",
            show_label=False,
            scale=1,
            min_width=140,
            container=False,
        )

    chatbot = gr.Chatbot(height=550, show_label=False, sanitize_html=False)
    with gr.Row():
        msg_box = gr.Textbox(
            placeholder=UI["en"]["placeholder"],
            show_label=False,
            scale=9,
            autofocus=True,
        )
        send_btn = gr.Button(UI["en"]["send"], scale=1, variant="primary")
    new_search_btn = gr.Button(UI["en"]["new_search"], visible=False, variant="secondary")

    # State
    intake_msgs_state = gr.State([])
    profile_state = gr.State(None)
    phase_state = gr.State("intake")
    lang_state = gr.State("en")

    respond_inputs = [msg_box, chatbot, intake_msgs_state, profile_state, phase_state, lang_state]
    respond_outputs = [chatbot, intake_msgs_state, profile_state, phase_state, msg_box, new_search_btn]

    demo.load(
        lambda: initialize("en"),
        outputs=[chatbot, intake_msgs_state, profile_state, phase_state],
    )

    msg_box.submit(respond, respond_inputs, respond_outputs)
    send_btn.click(respond, respond_inputs, respond_outputs)

    new_search_btn.click(
        initialize,
        inputs=[lang_state],
        outputs=[chatbot, intake_msgs_state, profile_state, phase_state],
    ).then(
        lambda lang: (
            gr.update(interactive=True, placeholder=UI[lang]["placeholder"]),
            gr.update(visible=False),
        ),
        inputs=[lang_state],
        outputs=[msg_box, new_search_btn],
    )

    lang_dropdown.change(
        change_language,
        inputs=[lang_dropdown],
        outputs=[
            chatbot, intake_msgs_state, profile_state, phase_state,
            heading_md, msg_box, send_btn, new_search_btn,
            lang_state,
        ],
    )


if __name__ == "__main__":
    demo.launch()

import anthropic
import oah_telemetry

client = anthropic.Anthropic()


def answer(question: str) -> str:
    oah_telemetry.emit("gen_ai.request.start")
    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=300,
        messages=[{"role": "user", "content": question}],
    )
    oah_telemetry.emit("gen_ai.request.end")
    return response.content[0].text

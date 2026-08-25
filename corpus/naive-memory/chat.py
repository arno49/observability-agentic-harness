import anthropic

client = anthropic.Anthropic()

history = []

while True:
    user_message = {
        "role": "user",
        "content": input("User: ")
    }

    if user_message["content"] == "quit":
        break
    history.append(user_message)
    message = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=1000,
        messages=history
    )
    
    response = message.content[0].text
    history.append({"role": "assistant", "content": response})

    print(response)
    print(f'History: {history}')

from groq import Groq
client = Groq(api_key="")
# client = Groq()  # ключ берётся из переменной GROQ_API_KEY
history = []

SYSTEM = "Ты Джарвис, ироничный ассистент. Отвечай коротко, 1-2 предложения, без markdown."


def ask_ai(question):
    history.append({"role": "user", "content": question})
    resp = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        max_tokens=300,
        messages=[{"role": "system", "content": SYSTEM}] + history[-10:],
    )
    answer = resp.choices[0].message.content
    history.append({"role": "assistant", "content": answer})
    return answer

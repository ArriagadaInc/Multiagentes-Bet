
import os
from dotenv import load_dotenv
load_dotenv()
from openai import OpenAI

def test_simple_search():
    client = OpenAI(timeout=60)
    prompt = "Busca quién ganó el partido de ayer entre Universidad de Chile y Palestino en la Copa Libertadores."
    
    print(f"Prompt: {prompt}")
    
    response = client.responses.create(
        model="gpt-4.1",
        input=prompt,
        tools=[{"type": "web_search"}]
    )
    
    print("\n--- RESPONSE (check tmp/test_web_simple_res.txt) ---")
    with open("tmp/test_web_simple_res.txt", "w", encoding="utf-8") as f:
        f.write("OUTPUT_TEXT:\n")
        f.write(getattr(response, "output_text", "") or "")
        f.write("\n\nRAW_RESPONSE:\n")
        f.write(str(response))

if __name__ == "__main__":
    test_simple_search()

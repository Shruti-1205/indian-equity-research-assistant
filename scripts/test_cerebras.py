"""Direct Cerebras API smoke test — tries each available model with and without
JSON mode. Surfaces the full error body so we can see what the server is complaining about.
"""
import os
import json
from dotenv import load_dotenv

load_dotenv()

CEREBRAS_API_KEY = os.getenv("CEREBRAS_API_KEY", "")
if not CEREBRAS_API_KEY:
    print("❌ CEREBRAS_API_KEY not found in .env")
    raise SystemExit(1)

print(f"Key: ...{CEREBRAS_API_KEY[-6:]}")

from openai import OpenAI
client = OpenAI(
    base_url="https://api.cerebras.ai/v1",
    api_key=CEREBRAS_API_KEY,
)

# Discover models first
print("\n── Listing models ──")
try:
    for m in client.models.list().data:
        print(f"  {m.id}")
except Exception as e:
    print(f"  ✗ {type(e).__name__}: {e}")

candidates = ["gpt-oss-120b", "qwen-3-235b-a22b-instruct-2507", "llama3.1-8b", "zai-glm-4.7"]

for model in candidates:
    for json_mode in (False, True):
        label = f"{model} (json_mode={json_mode})"
        print(f"\n── Testing {label} ──")
        kwargs = {
            "model": model,
            "messages": [
                {"role": "system", "content": "Reply with exactly {\"ok\": true}"},
                {"role": "user", "content": "respond"},
            ],
            "max_tokens": 30,
            "temperature": 0,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        try:
            r = client.chat.completions.create(**kwargs)
            print(f"  ✓ {r.choices[0].message.content!r}")
            print(f"    tokens: in={r.usage.prompt_tokens}  out={r.usage.completion_tokens}")
        except Exception as e:
            # Print as much detail as possible
            msg = str(e)
            body = getattr(e, "response", None)
            if body is not None:
                try:
                    msg += f" | body: {body.text[:300]}"
                except Exception:
                    pass
            print(f"  ✗ {type(e).__name__}: {msg[:400]}")

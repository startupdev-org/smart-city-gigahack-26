import httpx

r = httpx.post(
    "http://localhost:11434/api/chat",
    json={
        "model": "hermes3:8b",
        "stream": False,
        "options": {"num_ctx": 4096, "temperature": 0.1},
        "messages": [
            {
                "role": "user",
                "content": 'Return ONLY JSON: {"status":"supported","answer":"ok","sources":[],"confidence":"high","language":"ro"}',
            }
        ],
    },
    timeout=300,
)
print("status", r.status_code)
print(r.text[:800])

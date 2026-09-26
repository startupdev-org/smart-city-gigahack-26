import httpx

r = httpx.post(
    "http://localhost:11434/api/chat",
    json={
        "model": "qwen3:8b",
        "stream": False,
        "options": {"num_ctx": 2048, "temperature": 0.1},
        "messages": [
            {"role": "user", "content": 'Return ONLY JSON: {"ok": true, "status": "supported"}'}
        ],
    },
    timeout=300,
)
print("status", r.status_code)
print(r.text[:500])

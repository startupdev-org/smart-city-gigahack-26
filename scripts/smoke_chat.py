import json
import sys
from pathlib import Path

import httpx

sys.stdout.reconfigure(encoding="utf-8")

base = os.getenv("NEXT_PUBLIC_API_URL")
out = []
print("health", httpx.get(f"{base}/api/health", timeout=30).json())

questions = [
    "Ce acte sunt necesare pentru autorizatia de construire?",
    "Care este termenul pentru autorizatia de construire?",
    "Care este amenda pentru parcare ilegala in Chisinau?",
]

for q in questions:
    print("\n===", q)
    r = httpx.post(
        f"{base}/api/chat",
        json={"question": q, "top_k": 5},
        timeout=300,
    )
    print("status_code", r.status_code)
    data = r.json()
    out.append({"q": q, **data})
    print("status:", data.get("status"))
    ans = (data.get("answer") or "")[:500]
    print("answer:", ans)
    print("sources:", len(data.get("sources") or []))
    for s in (data.get("sources") or [])[:3]:
        print(" -", s.get("document"), "p=", s.get("page"))
    if data.get("next_action"):
        print("next:", data["next_action"])

Path(__file__).with_name("smoke_chat_results.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
)
print("\nWrote smoke_chat_results.json")

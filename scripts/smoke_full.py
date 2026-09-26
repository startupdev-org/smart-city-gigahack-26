import json
import sys
from pathlib import Path

import httpx

sys.stdout.reconfigure(encoding="utf-8")
base = "http://127.0.0.1:8000"
out = {"root": httpx.get(f"{base}/").json()}

# auth
r = httpx.post(
    f"{base}/api/auth/login",
    json={"email": "admin@civic.ai", "password": "admin123"},
    timeout=30,
)
out["login"] = {"status": r.status_code, "body": r.json() if r.status_code < 500 else r.text}
token = r.json().get("access_token") if r.status_code == 200 else None

if token:
    h = {"Authorization": f"Bearer {token}"}
    out["stats"] = httpx.get(f"{base}/api/admin/stats", headers=h, timeout=30).json()
    out["cost"] = httpx.get(f"{base}/api/admin/cost", headers=h, timeout=30).json()

# chat conflict question
r = httpx.post(
    f"{base}/api/chat",
    json={"question": "Care este termenul pentru autorizatia de construire?", "top_k": 5},
    timeout=300,
)
out["chat_term"] = {"status_code": r.status_code, "data": r.json() if r.headers.get("content-type","").startswith("application/json") else r.text[:500]}

Path(__file__).with_name("smoke_full_results.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(json.dumps({
    "root_phase": out["root"].get("phase"),
    "login": out["login"]["status"],
    "pgvector": (out.get("stats") or {}).get("pgvector"),
    "docs": (out.get("stats") or {}).get("documents"),
    "chat_status": (out.get("chat_term") or {}).get("data", {}).get("status") if isinstance((out.get("chat_term") or {}).get("data"), dict) else None,
}, ensure_ascii=False, indent=2))

$ErrorActionPreference = "Stop"

$py = @'
import json
import os
import sys
import time
import uuid
import urllib.request
import urllib.error

def extract_response_text(data):
    output = data.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if isinstance(content, list):
                for child in content:
                    if not isinstance(child, dict):
                        continue
                    if isinstance(child.get("text"), str):
                        return child["text"]
                    if child.get("type") == "output_text" and isinstance(child.get("text"), str):
                        return child["text"]

    output_text = data.get("output_text")
    if isinstance(output_text, str):
        return output_text

    return None

api_url = os.environ["AI_API_URL"].rstrip("/") + "/responses"
api_key = os.environ["AI_API_KEY"]
model = os.environ.get("AI_MODEL", "gpt-5-mini")
client_request_id = str(uuid.uuid4())

payload = {
    "model": model,
    "input": "Reply with exactly this JSON and nothing else: {\"ok\": true}",
    "text": {
        "format": {
            "type": "json_schema",
            "name": "ai_ping",
            "strict": True,
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "ok": {"type": "boolean"}
                },
                "required": ["ok"]
            }
        }
    }
}

data = json.dumps(payload).encode("utf-8")
req = urllib.request.Request(api_url, data=data, method="POST")
req.add_header("Authorization", f"Bearer {api_key}")
req.add_header("Content-Type", "application/json")
req.add_header("X-Client-Request-Id", client_request_id)

started = time.time()

try:
    with urllib.request.urlopen(req, timeout=75) as resp:
        body = resp.read().decode("utf-8")
        parsed = json.loads(body)
        result = {
            "ok": True,
            "elapsed_seconds": round(time.time() - started, 2),
            "client_request_id": client_request_id,
            "model": model,
            "response_id": parsed.get("id"),
            "response_text": extract_response_text(parsed),
        }
        print(json.dumps(result, indent=2))
except urllib.error.HTTPError as exc:
    body = exc.read().decode("utf-8", "replace")
    print(json.dumps({
        "ok": False,
        "elapsed_seconds": round(time.time() - started, 2),
        "client_request_id": client_request_id,
        "status_code": exc.code,
        "error": body
    }, indent=2))
    sys.exit(1)
except Exception as exc:
    print(json.dumps({
        "ok": False,
        "elapsed_seconds": round(time.time() - started, 2),
        "client_request_id": client_request_id,
        "error_type": type(exc).__name__,
        "error": str(exc)
    }, indent=2))
    sys.exit(1)
'@

$py | docker compose exec -T backend python -
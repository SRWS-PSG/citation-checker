from __future__ import annotations

import json
import re
import sys
import traceback
from http.server import BaseHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from refaudit.budget import TimeBudget
from refaudit.web import check_reference_payload

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
MAX_REF_LENGTH = 2000
MAX_EMAIL_LENGTH = 320
WEB_PAUSE_SEC = 0.1


def build_json_response(status: int, payload: dict) -> tuple[int, bytes]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return status, body


def validate_payload(payload: dict) -> tuple[str, str]:
    ref = (payload.get("ref") or "").strip()
    email = (payload.get("email") or "").strip()

    if not ref:
        raise ValueError("reference text is required")
    if len(ref) > MAX_REF_LENGTH:
        raise ValueError("reference text must be 2000 characters or fewer")
    if not email:
        raise ValueError("email is required")
    if len(email) > MAX_EMAIL_LENGTH or not EMAIL_RE.match(email):
        raise ValueError("email format is invalid")
    return ref, email


WEB_BUDGET_SEC = 55.0  # Vercel maxDuration=60s, keep 5s buffer


def handle_check(payload: dict) -> tuple[int, dict]:
    ref, email = validate_payload(payload)
    budget = TimeBudget(total_seconds=WEB_BUDGET_SEC)
    result = check_reference_payload(ref, email=email, pause_sec=WEB_PAUSE_SEC, budget=budget)
    return 200, {"ok": True, "result": result}


class handler(BaseHTTPRequestHandler):
    def _write_json(self, status: int, payload: dict) -> None:
        status_code, body = build_json_response(status, payload)
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Allow", "POST, OPTIONS")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def do_GET(self) -> None:
        self._write_json(405, {"ok": False, "error": "method_not_allowed"})

    def do_POST(self) -> None:
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0

        raw_body = self.rfile.read(content_length)
        try:
            payload = json.loads(raw_body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._write_json(400, {"ok": False, "error": "invalid_json"})
            return

        try:
            status, response = handle_check(payload)
            self._write_json(status, response)
        except ValueError as exc:
            self._write_json(400, {"ok": False, "error": str(exc)})
        except Exception:
            traceback.print_exc()
            self._write_json(500, {"ok": False, "error": "internal_error"})

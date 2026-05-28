from __future__ import annotations

import json
import sys
import traceback
from http.server import BaseHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from refaudit.parser import split_references

# 生コピペ（行番号付きPDF全体など）を想定し、照合用 (api/check.py) より大きく取る。
MAX_TEXT_LENGTH = 50_000


def build_json_response(status: int, payload: dict) -> tuple[int, bytes]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return status, body


def validate_payload(payload: dict) -> str:
    text = payload.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text is required")
    if len(text) > MAX_TEXT_LENGTH:
        raise ValueError("text must be 50000 characters or fewer")
    return text


def handle_clean(payload: dict) -> tuple[int, dict]:
    text = validate_payload(payload)
    refs = split_references(text)
    return 200, {"ok": True, "refs": refs}


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
            status, response = handle_clean(payload)
            self._write_json(status, response)
        except ValueError as exc:
            self._write_json(400, {"ok": False, "error": str(exc)})
        except Exception:
            traceback.print_exc()
            self._write_json(500, {"ok": False, "error": "internal_error"})

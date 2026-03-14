from __future__ import annotations

import json
import sys
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PUBLIC = ROOT / "public"
for item in (ROOT, SRC):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from api.check import build_json_response, handle_check


class LocalHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PUBLIC), **kwargs)

    def do_POST(self) -> None:
        if self.path != "/api/check":
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return

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
            self._write_json(500, {"ok": False, "error": "internal_error"})

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _write_json(self, status: int, payload: dict) -> None:
        status_code, body = build_json_response(status, payload)
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    host = "127.0.0.1"
    port = 3100
    with ThreadingHTTPServer((host, port), LocalHandler) as server:
        print(f"local web server running at http://{host}:{port}")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print()
            print("stopped")


if __name__ == "__main__":
    main()

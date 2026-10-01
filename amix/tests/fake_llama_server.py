"""Test double for a loopback OpenAI-compatible server. Not a product runtime."""
from __future__ import annotations

import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def main() -> int:
    argv_path = os.environ.get("FAKE_LLAMA_ARGV")
    if argv_path:
        Path(argv_path).write_text("\n".join(sys.argv), encoding="utf-8")
    if "--version" in sys.argv:
        print("llama.cpp test 0.0.0")
        return 0
    host = _value("--host")
    port = int(_value("--port"))
    model = _value("-m")
    if host != "127.0.0.1":
        print("refusing non-loopback host", file=sys.stderr)
        return 2
    name = Path(model).name
    if "crash" in name:
        print("failed to allocate model", file=sys.stderr)
        return 1
    if "hang" in name:
        time.sleep(30)
        return 0
    if "bind" in name:
        print("address already in use", file=sys.stderr)
        return 1

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path.split("?", 1)[0] != "/v1/models":
                self.send_error(404)
                return
            body = json.dumps({"data": [{"id": _value("--alias")}], "nonce": os.getpid()}).encode("utf-8")
            self._send(body)

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            if "invalid-json" in name:
                body = json.dumps({"choices": [{"message": {"content": "not-json"}}]}).encode("utf-8")
            else:
                body = json.dumps({"choices": [{"message": {"content": json.dumps({"ok": True})}}]}).encode("utf-8")
            marker = os.environ.get("FAKE_LLAMA_BODY")
            if marker:
                Path(marker).write_bytes(raw)
            self._send(body)

        def _send(self, body: bytes) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args) -> None:
            return

    server = ThreadingHTTPServer((host, port), Handler)
    server.serve_forever()
    return 0


def _value(flag: str) -> str:
    index = sys.argv.index(flag)
    return sys.argv[index + 1]


if __name__ == "__main__":
    raise SystemExit(main())

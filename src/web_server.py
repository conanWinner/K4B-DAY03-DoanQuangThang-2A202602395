"""UI local cho bài lab ReAct. Chỉ lắng nghe loopback theo mặc định."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import argparse
import json
from pathlib import Path
from threading import Lock
from uuid import uuid4

from app import run_react_agent
from mcp_server import MCPFarmServer
from prompts import REACT_AGENT_SYSTEM_PROMPT
from providers import ProviderError, get_llm_provider
from schedule_confirmation import schedule_confirmer

ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT / "web"
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
}
SESSIONS = {}
SESSIONS_LOCK = Lock()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False) + "\n").encode("utf-8")


class LabHandler(BaseHTTPRequestHandler):
    server_version = "CoffeeLabUI/1.0"

    def log_message(self, format, *args):
        print(f"[UI] {self.address_string()} - {format % args}")

    def send_json(self, status, value):
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in STATIC_FILES:
            filename, content_type = STATIC_FILES[self.path]
            body = (WEB_DIR / filename).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/api/config":
            try:
                provider = get_llm_provider()
                provider_info = {"name": type(provider).__name__, "model": provider.model_name,
                                 "mode": "mock" if provider.is_mock else "live"}
            except ProviderError as exc:
                provider_info = {"name": "Chưa sẵn sàng", "model": "—", "mode": "error",
                                 "error": str(exc)}
            self.send_json(200, {"provider": provider_info,
                "system_prompt": REACT_AGENT_SYSTEM_PROMPT,
                "tools": MCPFarmServer().list_tools()})
            return
        self.send_error(404)

    def do_POST(self):
        if self.path != "/api/chat":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 32_768:
                raise ValueError("Kích thước yêu cầu không hợp lệ.")
            payload = json.loads(self.rfile.read(length))
            message = payload.get("message", "").strip()
            prompt = payload.get("system_prompt", "").strip()
            session_id = payload.get("session_id") or str(uuid4())
            allow_schedule = payload.get("allow_schedule") is True
            if not message or len(message) > 8_000:
                raise ValueError("Câu hỏi phải có từ 1 đến 8.000 ký tự.")
            if not prompt or len(prompt) > 16_000:
                raise ValueError("System prompt phải có từ 1 đến 16.000 ký tự.")
            if not isinstance(session_id, str) or len(session_id) > 100:
                raise ValueError("Session ID không hợp lệ.")
            provider = get_llm_provider()
        except (ValueError, TypeError, json.JSONDecodeError, ProviderError) as exc:
            self.send_json(400, {"error": str(exc)})
            return

        with SESSIONS_LOCK:
            session = SESSIONS.setdefault(session_id, {"history": [], "lock": Lock()})
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()

        def stream(event):
            try:
                self.wfile.write(json_bytes({"event": "trace", "data": event}))
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass

        try:
            self.wfile.write(json_bytes({"event": "session", "session_id": session_id}))
            self.wfile.flush()
            # Một session xử lý tuần tự để lịch sử hội thoại không xen kẽ.
            with session["lock"]:
                trace = run_react_agent(
                    message, provider, MCPFarmServer(), history=session["history"],
                    confirm_schedule=schedule_confirmer(message, allow_schedule, session['history']),
                    system_prompt=prompt, on_event=stream,
                )
            final = next((item.get("output", "") for item in reversed(trace)
                          if item["action_type"] in ("FINAL_ANSWER", "ERROR", "ITERATION_LIMIT")), "")
            self.wfile.write(json_bytes({"event": "done", "answer": final, "trace": trace}))
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as exc:
            self.wfile.write(json_bytes({"event": "error",
                "message": f"Yêu cầu thất bại ({type(exc).__name__})."}))
            self.wfile.flush()


def main():
    parser = argparse.ArgumentParser(description="UI local cho trợ lý cà phê")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), LabHandler)
    print(f"UI: http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nĐã dừng UI.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

import json
import mimetypes
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_ROOT = PROJECT_ROOT / "frontend"
SRC_DIR = PROJECT_ROOT / "src"
UPLOAD_DIR = PROJECT_ROOT / ".tmp_uploads"
sys.path.insert(0, str(SRC_DIR))

from ai_interview.interview_service import analyze_resume, evaluate_answer, generate_questions  # noqa: E402
from ai_interview.mcp_client import MCPClient  # noqa: E402
from ai_interview.rag_service import (  # noqa: E402
    ALL_KNOWLEDGE_BASES,
    TOOLS_ONLY,
    delete_conversation,
    get_conversation,
    list_conversations,
    list_knowledge_bases,
    mcp_chat_stream_events,
    rag_chat,
    rag_chat_stream_events,
    save_mcp_exchange,
    upload_knowledge_file,
)
from ai_interview.tools import server as mcp_server  # noqa: E402


class ApiHandler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def _send_sse_headers(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _write_sse(self, event: str, payload: dict) -> None:
        body = f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")
        self.wfile.write(body)
        self.wfile.flush()

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8")) if raw else {}

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0") or 0)
        return self.rfile.read(length)

    def do_OPTIONS(self) -> None:
        self._send_json(204, {})

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/health":
            self._send_json(200, {"status": "ok"})
            return
        if path == "/api/rag/knowledge-bases":
            self._send_json(200, {"items": list_knowledge_bases()})
            return
        if path == "/api/conversations":
            query = parse_qs(parsed.query)
            self._send_json(200, {"items": list_conversations(query.get("type", [""])[0])})
            return
        if path.startswith("/api/conversations/"):
            conversation_id = path.rsplit("/", 1)[-1]
            try:
                self._send_json(200, get_conversation(conversation_id))
            except Exception as exc:
                self._send_json(400, {"detail": str(exc)})
            return
        self._send_json(404, {"detail": "Not found"})

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path.startswith("/api/conversations/"):
            conversation_id = path.rsplit("/", 1)[-1]
            try:
                self._send_json(200, delete_conversation(conversation_id))
            except Exception as exc:
                self._send_json(400, {"detail": str(exc)})
            return
        self._send_json(404, {"detail": "Not found"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path == "/api/interview/from-text":
                payload = self._read_json()
                position = payload["position"]
                analysis = analyze_resume(payload["resume_text"])
                questions = generate_questions(position, analysis["summary"])["questions"]
                self._send_json(
                    200,
                    {"position": position, "resume_analysis": analysis, "questions": questions},
                )
                return

            if path == "/api/interview/upload":
                query = parse_qs(parsed.query)
                position = query.get("position", [""])[0]
                filename = query.get("filename", ["resume.pdf"])[0]
                data = self._read_body()
                if not data:
                    raise ValueError("上传文件不能为空。")

                suffix = Path(filename).suffix or ".pdf"
                UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
                tmp_path = UPLOAD_DIR / f"{uuid.uuid4().hex}{suffix}"
                tmp_path.write_bytes(data)
                try:
                    analysis = analyze_resume(str(tmp_path))
                    questions = generate_questions(position, analysis["summary"])["questions"]
                finally:
                    tmp_path.unlink(missing_ok=True)
                self._send_json(
                    200,
                    {"position": position, "resume_analysis": analysis, "questions": questions},
                )
                return

            if path == "/api/evaluate":
                payload = self._read_json()
                self._send_json(200, evaluate_answer(payload["question"], payload.get("answer", "")))
                return

            if path == "/api/questions":
                payload = self._read_json()
                self._send_json(200, generate_questions(payload["position"], payload["resume_summary"]))
                return

            if path == "/api/rag/knowledge-bases":
                query = parse_qs(parsed.query)
                filename = query.get("filename", ["knowledge.txt"])[0]
                name = query.get("name", [""])[0]
                self._send_json(200, upload_knowledge_file(filename, self._read_body(), name))
                return

            if path == "/api/rag/chat":
                payload = self._read_json()
                self._send_json(
                    200,
                    rag_chat(
                        knowledge_base_id=payload["knowledge_base_id"],
                        message=payload["message"],
                        conversation_id=payload.get("conversation_id", ""),
                    ),
                )
                return

            if path == "/api/mcp/chat":
                payload = self._read_json()
                client = MCPClient(mcp_server)
                result = client.chat_with_tools_detail(payload["message"])
                self._send_json(
                    200,
                    save_mcp_exchange(
                        payload["message"],
                        result["answer"],
                        payload.get("conversation_id", ""),
                        result.get("tools_used", []),
                    ),
                )
                return

            if path == "/api/assistant/chat":
                payload = self._read_json()
                knowledge_base_id = payload.get("knowledge_base_id", "") or ALL_KNOWLEDGE_BASES
                if knowledge_base_id == TOOLS_ONLY:
                    client = MCPClient(mcp_server)
                    result = client.chat_with_tools_detail(payload["message"])
                    self._send_json(
                        200,
                        save_mcp_exchange(
                            payload["message"],
                            result["answer"],
                            payload.get("conversation_id", ""),
                            result.get("tools_used", []),
                        ),
                    )
                    return

                self._send_json(
                    200,
                    rag_chat(
                        knowledge_base_id=knowledge_base_id,
                        message=payload["message"],
                        conversation_id=payload.get("conversation_id", ""),
                        conversation_type="assistant",
                    ),
                )
                return

            if path == "/api/assistant/chat/stream":
                payload = self._read_json()
                self._send_sse_headers()
                try:
                    knowledge_base_id = payload.get("knowledge_base_id", "") or ALL_KNOWLEDGE_BASES
                    if knowledge_base_id == TOOLS_ONLY:
                        events = mcp_chat_stream_events(payload["message"], payload.get("conversation_id", ""))
                    else:
                        events = rag_chat_stream_events(
                            knowledge_base_id=knowledge_base_id,
                            message=payload["message"],
                            conversation_id=payload.get("conversation_id", ""),
                            conversation_type="assistant",
                        )
                    for item in events:
                        self._write_sse(item["event"], item["data"])
                except Exception as exc:
                    self._write_sse("error", {"detail": str(exc)})
                return

            self._send_json(404, {"detail": "Not found"})
        except Exception as exc:
            self._send_json(400, {"detail": str(exc)})


class FrontendHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        route = parsed.path
        if route == "/":
            route = "/index.html"
        target = (FRONTEND_ROOT / route.lstrip("/")).resolve()
        if not str(target).startswith(str(FRONTEND_ROOT.resolve())):
            self.send_error(403)
            return
        if not target.exists() or not target.is_file():
            self.send_error(404)
            return

        body = target.read_bytes()
        mime_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if target.suffix in {".html", ".css", ".js"}:
            mime_type += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", mime_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve(server: ThreadingHTTPServer, label: str) -> None:
    print(f"{label} listening on http://{server.server_address[0]}:{server.server_address[1]}", flush=True)
    server.serve_forever()


def main() -> None:
    api = ThreadingHTTPServer(("127.0.0.1", 8000), ApiHandler)
    frontend = ThreadingHTTPServer(("127.0.0.1", 5173), FrontendHandler)
    threading.Thread(target=serve, args=(api, "API"), daemon=True).start()
    serve(frontend, "Frontend")


if __name__ == "__main__":
    main()

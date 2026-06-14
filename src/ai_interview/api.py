import json
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .interview_service import analyze_resume, evaluate_answer, generate_questions
from .mcp_client import MCPClient
from .rag_service import (
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
from .tools import server as mcp_server

APP_ROOT = Path(__file__).resolve().parents[2]
UPLOAD_DIR = APP_ROOT / ".tmp_uploads"

app = FastAPI(title="AI Interview API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ResumeTextRequest(BaseModel):
    position: str = Field(..., min_length=1)
    resume_text: str = Field(..., min_length=1)


class QuestionRequest(BaseModel):
    position: str = Field(..., min_length=1)
    resume_summary: str = Field(..., min_length=1)


class EvaluationRequest(BaseModel):
    question: str = Field(..., min_length=1)
    answer: str = ""


class InterviewStartResponse(BaseModel):
    position: str
    resume_analysis: Dict[str, Any]
    questions: list[str]


class RagChatRequest(BaseModel):
    knowledge_base_id: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1)
    conversation_id: str = ""


class McpChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    conversation_id: str = ""


class AssistantChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    conversation_id: str = ""
    knowledge_base_id: str = ""


def _safe_error(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


def _sse(event: str, data: Dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.get("/api/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


# 文本简历分析出题
@app.post("/api/interview/from-text", response_model=InterviewStartResponse)
def start_interview_from_text(payload: ResumeTextRequest) -> Dict[str, Any]:
    try:
        analysis = analyze_resume(payload.resume_text)
        questions = generate_questions(payload.position, analysis["summary"])["questions"]
    except Exception as exc:
        raise _safe_error(exc) from exc
    return {
        "position": payload.position,
        "resume_analysis": analysis,
        "questions": questions,
    }


# 文件简历分析出题
@app.post("/api/interview/upload", response_model=InterviewStartResponse)
async def start_interview_from_upload(
        request: Request,
        position: str = Query(..., min_length=1),
        filename: str = Query("resume.pdf"),
) -> Dict[str, Any]:
    data = await request.body()
    if not data:
        raise HTTPException(status_code=400, detail="上传文件不能为空。")

    suffix = Path(filename).suffix or ".pdf"
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = UPLOAD_DIR / f"{uuid.uuid4().hex}{suffix}"
    tmp_path.write_bytes(data)

    try:
        analysis = analyze_resume(str(tmp_path))
        questions = generate_questions(position, analysis["summary"])["questions"]
    except Exception as exc:
        raise _safe_error(exc) from exc
    finally:
        tmp_path.unlink(missing_ok=True)

    return {
        "position": position,
        "resume_analysis": analysis,
        "questions": questions,
    }


# 单独出题
@app.post("/api/questions")
def create_questions(payload: QuestionRequest) -> Dict[str, Any]:
    try:
        return generate_questions(payload.position, payload.resume_summary)
    except Exception as exc:
        raise _safe_error(exc) from exc


# 单题评估
@app.post("/api/evaluate")
def evaluate(payload: EvaluationRequest) -> Dict[str, Any]:
    try:
        return evaluate_answer(payload.question, payload.answer)
    except Exception as exc:
        raise _safe_error(exc) from exc


# 知识库列表
@app.get("/api/rag/knowledge-bases")
def knowledge_bases() -> Dict[str, Any]:
    return {"items": list_knowledge_bases()}


# 上传知识库
@app.post("/api/rag/knowledge-bases")
async def create_knowledge_base(
        request: Request,
        filename: str = Query(..., min_length=1),
        name: str = Query(""),
) -> Dict[str, Any]:
    data = await request.body()
    try:
        return upload_knowledge_file(filename=filename, data=data, knowledge_base_name=name)
    except Exception as exc:
        raise _safe_error(exc) from exc


# 会话列表
@app.get("/api/conversations")
def conversations(type: str = Query("")) -> Dict[str, Any]:
    return {"items": list_conversations(type)}


# 会话详情
@app.get("/api/conversations/{conversation_id}")
def conversation_detail(conversation_id: str) -> Dict[str, Any]:
    try:
        return get_conversation(conversation_id)
    except Exception as exc:
        raise _safe_error(exc) from exc


# 删除会话
@app.delete("/api/conversations/{conversation_id}")
def remove_conversation(conversation_id: str) -> Dict[str, Any]:
    try:
        return delete_conversation(conversation_id)
    except Exception as exc:
        raise _safe_error(exc) from exc


#  纯 rag 知识库检索聊天
@app.post("/api/rag/chat")
def chat_with_rag(payload: RagChatRequest) -> Dict[str, Any]:
    try:
        return rag_chat(
            knowledge_base_id=payload.knowledge_base_id,
            message=payload.message,
            conversation_id=payload.conversation_id,
        )
    except Exception as exc:
        raise _safe_error(exc) from exc


# 纯 mcp 工具调用聊天
@app.post("/api/mcp/chat")
def chat_with_mcp(payload: McpChatRequest) -> Dict[str, Any]:
    try:
        client = MCPClient(mcp_server)
        result = client.chat_with_tools_detail(payload.message)
        return save_mcp_exchange(
            payload.message,
            result["answer"],
            payload.conversation_id,
            result.get("tools_used", []),
        )
    except Exception as exc:
        raise _safe_error(exc) from exc


# RAG+MCP融合聊天
@app.post("/api/assistant/chat")
def chat_with_assistant(payload: AssistantChatRequest) -> Dict[str, Any]:
    try:
        if payload.knowledge_base_id == TOOLS_ONLY:
            client = MCPClient(mcp_server)
            result = client.chat_with_tools_detail(payload.message)
            return save_mcp_exchange(
                payload.message,
                result["answer"],
                payload.conversation_id,
                result.get("tools_used", []),
            )

        return rag_chat(
            knowledge_base_id=payload.knowledge_base_id or ALL_KNOWLEDGE_BASES,
            message=payload.message,
            conversation_id=payload.conversation_id,
            conversation_type="assistant",
        )
    except Exception as exc:
        raise _safe_error(exc) from exc

# RAG+MCP流式输出聊天（默认）
@app.post("/api/assistant/chat/stream")
def stream_chat_with_assistant(payload: AssistantChatRequest) -> StreamingResponse:
    def event_stream():
        try:
            if payload.knowledge_base_id == TOOLS_ONLY:
                events = mcp_chat_stream_events(payload.message, payload.conversation_id)
            else:
                events = rag_chat_stream_events(
                    knowledge_base_id=payload.knowledge_base_id or ALL_KNOWLEDGE_BASES,
                    message=payload.message,
                    conversation_id=payload.conversation_id,
                    conversation_type="assistant",
                )
            for item in events:
                yield _sse(item["event"], item["data"])
        except Exception as exc:
            yield _sse("error", {"detail": str(exc)})

    return StreamingResponse(event_stream(), media_type="text/event-stream")

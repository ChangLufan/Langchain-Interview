import json
import os
import re
import time
import uuid
from pathlib import Path
from threading import RLock
from typing import Any, Dict, Iterator, List, Optional, Tuple

from .config import get_app_config
from .embedding_service import embed_texts
from .llm import HumanMessage, build_prompt, llm, normalize_content, require_llm_ready
from .postgres_store import (
    delete_conversation as delete_db_conversation,
    get_conversation as get_db_conversation,
    list_conversations as list_db_conversations,
    save_conversation_exchange as save_db_conversation_exchange,
    save_knowledge_base,
    search_chunks,
    search_chunks_across_knowledge_bases,
)
from .resume_loader import clean_resume_text, load_resume_text

APP_ROOT = Path(__file__).resolve().parents[2]
RAG_DIR = APP_ROOT / ".rag_data"
LOCAL_OBJECT_DIR = RAG_DIR / "objects"
STATE_PATH = RAG_DIR / "state.json"
MAX_CONTEXT_CHARS = 4800
MAX_HISTORY_TURNS = 8
ALL_KNOWLEDGE_BASES = "__all__"
TOOLS_ONLY = "__tools__"
KNOWLEDGE_BASE_SCAN_THRESHOLD = 5

_LOCK = RLock()


def _now_ms() -> int:
    return int(time.time() * 1000)


def _empty_state() -> Dict[str, Any]:
    return {"knowledge_bases": []}


def _load_state() -> Dict[str, Any]:
    RAG_DIR.mkdir(parents=True, exist_ok=True)
    if not STATE_PATH.exists():
        return _empty_state()
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return _empty_state()
    data.setdefault("knowledge_bases", [])
    data["conversations"] = []
    return data


def _save_state(state: Dict[str, Any]) -> None:
    RAG_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = STATE_PATH.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(STATE_PATH)


def _safe_name(filename: str) -> str:
    name = Path(filename or "knowledge.txt").name
    name = re.sub(r"[^\w.\-\u4e00-\u9fff]+", "_", name, flags=re.UNICODE)
    return name or "knowledge.txt"


def _decode_text(data: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="ignore")


def _extract_text(path: Path, data: bytes) -> str:
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md", ".csv", ".json", ".html", ".htm"}:
        return clean_resume_text(_decode_text(data))
    try:
        parsed_text, _ = load_resume_text(str(path))
        return parsed_text
    except Exception:
        fallback = clean_resume_text(_decode_text(data))
        if fallback:
            return fallback
        raise


def _chunk_text(text: str, size: int = 900, overlap: int = 160) -> List[str]:
    normalized = clean_resume_text(text)
    if not normalized:
        return []

    chunks: List[str] = []
    start = 0
    while start < len(normalized):
        end = min(len(normalized), start + size)
        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(normalized):
            break
        start = max(0, end - overlap)
    return chunks


def _oss_config() -> Dict[str, str]:
    config = get_app_config().get("alioss", {})
    return {
        "endpoint": os.getenv("ALIYUN_OSS_ENDPOINT") or os.getenv("OSS_ENDPOINT") or str(config.get("endpoint", "")),
        "bucket": os.getenv("ALIYUN_OSS_BUCKET")
        or os.getenv("OSS_BUCKET_NAME")
        or str(config.get("bucket-name", "")),
        "access_key_id": os.getenv("ALIYUN_OSS_ACCESS_KEY_ID")
        or os.getenv("OSS_ACCESS_KEY_ID")
        or str(config.get("access-key-id", "")),
        "access_key_secret": os.getenv("ALIYUN_OSS_ACCESS_KEY_SECRET")
        or os.getenv("OSS_ACCESS_KEY_SECRET")
        or str(config.get("access-key-secret", "")),
        "prefix": os.getenv("ALIYUN_OSS_PREFIX")
        or os.getenv("OSS_PREFIX")
        or str(config.get("prefix", "easy-langent/rag")),
    }


def _store_object(local_path: Path, object_key: str) -> Dict[str, Any]:
    config = _oss_config()
    if all(config[key] for key in ("endpoint", "bucket", "access_key_id", "access_key_secret")):
        try:
            import oss2  # type: ignore

            auth = oss2.Auth(config["access_key_id"], config["access_key_secret"])
            bucket = oss2.Bucket(auth, config["endpoint"], config["bucket"])
            bucket.put_object_from_file(object_key, str(local_path))
            return {
                "storage": "oss",
                "bucket": config["bucket"],
                "endpoint": config["endpoint"],
                "object_key": object_key,
                "uri": f"oss://{config['bucket']}/{object_key}",
            }
        except Exception as exc:
            storage_error = str(exc)
    else:
        storage_error = "未配置阿里云 OSS 环境变量，已使用本地对象存储模拟。"

    target = LOCAL_OBJECT_DIR / object_key
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(local_path.read_bytes())
    return {
        "storage": "local",
        "object_key": object_key,
        "uri": str(target),
        "note": storage_error,
    }


def upload_knowledge_file(filename: str, data: bytes, knowledge_base_name: str = "") -> Dict[str, Any]:
    if not data:
        raise ValueError("上传文件不能为空。")

    safe_filename = _safe_name(filename)
    knowledge_base_id = uuid.uuid4().hex
    tmp_dir = RAG_DIR / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = tmp_dir / f"{knowledge_base_id}_{safe_filename}"
    tmp_path.write_bytes(data)

    try:
        text = _extract_text(tmp_path, data)
        chunks = _chunk_text(text)
        if not chunks:
            raise ValueError("文件中没有可用于问答的文本内容。")

        prefix = _oss_config()["prefix"].strip("/")
        object_key = f"{prefix}/{knowledge_base_id}/{safe_filename}" if prefix else f"{knowledge_base_id}/{safe_filename}"
        object_info = _store_object(tmp_path, object_key)

        created_at = _now_ms()
        kb = {
            "id": knowledge_base_id,
            "name": knowledge_base_name.strip() or Path(safe_filename).stem or "未命名知识库",
            "filename": safe_filename,
            "created_at": created_at,
            "updated_at": created_at,
            "chunk_count": len(chunks),
            "object": object_info,
            "chunks": [
                {
                    "id": f"{knowledge_base_id}-{index + 1}",
                    "index": index + 1,
                    "text": chunk,
                    "source_name": safe_filename,
                }
                for index, chunk in enumerate(chunks)
            ],
        }
        kb["database"] = _persist_vectors_to_postgres(kb)

        with _LOCK:
            state = _load_state()
            state["knowledge_bases"].insert(0, kb)
            _save_state(state)

        return _public_kb(kb)
    finally:
        tmp_path.unlink(missing_ok=True)


def _public_kb(kb: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": kb["id"],
        "name": kb["name"],
        "filename": kb["filename"],
        "created_at": kb["created_at"],
        "updated_at": kb["updated_at"],
        "chunk_count": kb["chunk_count"],
        "object": kb.get("object", {}),
        "database": kb.get("database", {}),
    }


def _persist_vectors_to_postgres(kb: Dict[str, Any]) -> Dict[str, Any]:
    try:
        texts = [chunk["text"] for chunk in kb.get("chunks", [])]
        embeddings = embed_texts(texts)
        save_knowledge_base(kb, embeddings)
        return {
            "stored": True,
            "chunk_count": len(embeddings),
            "model": str(get_app_config().get("embedding", {}).get("model") or "text-embedding-v4"),
        }
    except Exception as exc:
        return {
            "stored": False,
            "error": str(exc),
        }


def list_knowledge_bases() -> List[Dict[str, Any]]:
    with _LOCK:
        return [_public_kb(kb) for kb in _load_state()["knowledge_bases"]]


def _tokens(text: str) -> List[str]:
    lowered = text.lower()
    latin = re.findall(r"[a-z0-9_]{2,}", lowered)
    chinese = re.findall(r"[\u4e00-\u9fff]", lowered)
    phrases = re.findall(r"[\u4e00-\u9fff]{2,}", lowered)
    bigrams: List[str] = []
    for phrase in phrases:
        bigrams.extend(phrase[index : index + 2] for index in range(max(0, len(phrase) - 1)))
    return list(dict.fromkeys(latin + chinese + bigrams))


def _score_chunk(query_tokens: List[str], text: str) -> float:
    lowered = text.lower()
    score = 0.0
    for token in query_tokens:
        count = lowered.count(token)
        if not count:
            continue
        weight = 2.5 if len(token) > 1 else 0.6
        score += count * weight
    return score


def _find_kb(state: Dict[str, Any], knowledge_base_id: str) -> Dict[str, Any]:
    for kb in state["knowledge_bases"]:
        if kb["id"] == knowledge_base_id:
            return kb
    raise ValueError("知识库不存在，请先上传文件。")


def _attach_kb(source: Dict[str, Any], kb: Dict[str, Any]) -> Dict[str, Any]:
    enriched = dict(source)
    enriched["knowledge_base_id"] = enriched.get("knowledge_base_id") or kb["id"]
    enriched["knowledge_base_name"] = kb["name"]
    return enriched


def _match_kb_by_name(question: str, knowledge_bases: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    normalized_question = re.sub(r"\s+", "", question).lower()
    if not normalized_question:
        return None

    candidates: List[Tuple[int, Dict[str, Any]]] = []
    for kb in knowledge_bases:
        name = str(kb.get("name", "")).strip()
        filename = str(kb.get("filename", "")).strip()
        aliases = {name, Path(filename).stem, filename}
        for alias in aliases:
            normalized_alias = re.sub(r"\s+", "", alias).lower()
            if len(normalized_alias) >= 2 and normalized_alias in normalized_question:
                candidates.append((len(normalized_alias), kb))
                break
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _retrieve(kb: Dict[str, Any], question: str, limit: int = 5) -> List[Dict[str, Any]]:
    try:
        query_embedding = embed_texts([question])[0]
        db_results = search_chunks(kb["id"], query_embedding, limit)
        if db_results:
            return [_attach_kb(source, kb) for source in db_results]
    except Exception:
        pass

    query_tokens = _tokens(question)
    ranked: List[Tuple[float, Dict[str, Any]]] = []
    for chunk in kb.get("chunks", []):
        score = _score_chunk(query_tokens, chunk["text"])
        if score > 0:
            ranked.append((score, chunk))

    if not ranked:
        ranked = [(0.0, chunk) for chunk in kb.get("chunks", [])[:limit]]

    ranked.sort(key=lambda item: item[0], reverse=True)
    return [
        {
            "id": chunk["id"],
            "knowledge_base_id": kb["id"],
            "knowledge_base_name": kb["name"],
            "index": chunk["index"],
            "source_name": chunk["source_name"],
            "text": chunk["text"],
            "score": round(score, 2),
        }
        for score, chunk in ranked[:limit]
    ]


def _retrieve_all(knowledge_bases: List[Dict[str, Any]], question: str, limit: int = 5) -> List[Dict[str, Any]]:
    if not knowledge_bases:
        return []

    kb_map = {kb["id"]: kb for kb in knowledge_bases}
    try:
        query_embedding = embed_texts([question])[0]
        db_results = search_chunks_across_knowledge_bases(list(kb_map.keys()), query_embedding, limit)
        if db_results:
            return [_attach_kb(source, kb_map[source["knowledge_base_id"]]) for source in db_results]
    except Exception:
        pass

    query_tokens = _tokens(question)
    ranked: List[Tuple[float, Dict[str, Any], Dict[str, Any]]] = []
    for kb in knowledge_bases:
        for chunk in kb.get("chunks", []):
            score = _score_chunk(query_tokens, chunk["text"])
            if score > 0:
                ranked.append((score, kb, chunk))

    if not ranked:
        for kb in knowledge_bases:
            for chunk in kb.get("chunks", [])[:limit]:
                ranked.append((0.0, kb, chunk))

    ranked.sort(key=lambda item: item[0], reverse=True)
    return [
        {
            "id": chunk["id"],
            "knowledge_base_id": kb["id"],
            "knowledge_base_name": kb["name"],
            "index": chunk["index"],
            "source_name": chunk["source_name"],
            "text": chunk["text"],
            "score": round(score, 2),
        }
        for score, kb, chunk in ranked[:limit]
    ]


def _create_conversation(conversation_type: str, title: str, knowledge_base_id: str = "") -> Dict[str, Any]:
    now = _now_ms()
    return {
        "id": uuid.uuid4().hex,
        "type": conversation_type,
        "title": title[:40] or "新会话",
        "knowledge_base_id": knowledge_base_id,
        "created_at": now,
        "updated_at": now,
        "messages": [],
    }


def _find_or_create_conversation(
    state: Dict[str, Any],
    conversation_id: str,
    conversation_type: str,
    title: str,
    knowledge_base_id: str = "",
) -> Dict[str, Any]:
    if conversation_id:
        for conversation in state["conversations"]:
            if conversation["id"] == conversation_id:
                return conversation
    conversation = _create_conversation(conversation_type, title, knowledge_base_id)
    state["conversations"].insert(0, conversation)
    return conversation


def list_conversations(conversation_type: str = "") -> List[Dict[str, Any]]:
    return list_db_conversations(conversation_type)


def get_conversation(conversation_id: str) -> Dict[str, Any]:
    return get_db_conversation(conversation_id)


def delete_conversation(conversation_id: str) -> Dict[str, Any]:
    return delete_db_conversation(conversation_id)


def _format_history(messages: List[Dict[str, str]]) -> str:
    recent = messages[-MAX_HISTORY_TURNS * 2 :]
    lines = []
    for item in recent:
        role = "用户" if item.get("role") == "user" else "助手"
        lines.append(f"{role}: {item.get('content', '')}")
    return "\n".join(lines)


def _format_context_parts(sources: List[Dict[str, Any]]) -> List[str]:
    context_parts = []
    used_chars = 0
    for index, source in enumerate(sources, start=1):
        text = source["text"]
        remaining = MAX_CONTEXT_CHARS - used_chars
        if remaining <= 0:
            break
        clipped = text[:remaining]
        used_chars += len(clipped)
        kb_name = source.get("knowledge_base_name") or "知识库"
        context_parts.append(f"[{index}] 来源：{kb_name} / {source['source_name']}，片段 {source['index']}\n{clipped}")
    return context_parts


def _answer_with_llm(question: str, history: List[Dict[str, str]], sources: List[Dict[str, Any]]) -> str:
    context_parts = _format_context_parts(sources)
    prompt = build_prompt(
        [
            (
                "system",
                (
                    "你是企业内部知识库问答助手。请只基于给定知识库片段和历史会话回答。"
                    "如果材料不足，请明确说明缺少哪些信息。回答要简洁，并在关键结论后标注引用编号，如 [1]。"
                ),
            ),
            (
                "human",
                "历史会话：\n{history}\n\n知识库片段：\n{context}\n\n用户问题：{question}",
            ),
        ]
    )
    response = llm.invoke(
        prompt.format_messages(
            history=_format_history(history),
            context="\n\n".join(context_parts),
            question=question,
        ),
        extra_body={"enable_thinking": False},
    )
    return normalize_content(response.content).strip()


def _stream_answer_with_llm(
    question: str,
    history: List[Dict[str, str]],
    sources: List[Dict[str, Any]],
) -> Iterator[str]:
    context_parts = _format_context_parts(sources)
    prompt = build_prompt(
        [
            (
                "system",
                (
                    "你是企业内部知识库问答助手。请只基于给定知识库片段和历史会话回答。"
                    "如果材料不足，请明确说明缺少哪些信息。回答要简洁，并在关键结论后标注引用编号，如 [1]。"
                ),
            ),
            (
                "human",
                "历史会话：\n{history}\n\n知识库片段：\n{context}\n\n用户问题：{question}",
            ),
        ]
    )
    for chunk in llm.stream(
        prompt.format_messages(
            history=_format_history(history),
            context="\n\n".join(context_parts),
            question=question,
        ),
        extra_body={"enable_thinking": False},
    ):
        text = normalize_content(getattr(chunk, "content", ""))
        if text:
            yield text


def _answer_with_tools(question: str, history: List[Dict[str, str]], sources: List[Dict[str, Any]]) -> Dict[str, Any]:
    from .mcp_client import MCPClient
    from .tools import server as mcp_server

    message = _build_tool_aware_message(question, history, sources)
    return MCPClient(mcp_server).chat_with_tools_detail(message, tool_selection_message=question)


def _build_tool_aware_message(question: str, history: List[Dict[str, str]], sources: List[Dict[str, Any]]) -> str:
    context = "\n\n".join(_format_context_parts(sources))
    history_text = _format_history(history)
    return (
        "你是企业内部智能问答助手。优先基于给定知识库片段回答；"
        "如果用户问题需要简历分析、出题、评分、岗位提取、回答优化或会话总结等能力，可以调用可用工具。"
        "如果调用了工具，请结合工具结果回答。\n\n"
        f"历史会话：\n{history_text}\n\n"
        f"知识库片段：\n{context}\n\n"
        f"用户问题：{question}"
    )


def _fallback_answer(sources: List[Dict[str, Any]]) -> str:
    if not sources:
        return "没有检索到相关知识库片段。"
    snippets = []
    for index, source in enumerate(sources[:3], start=1):
        text = source["text"].replace("\n", " ")
        snippets.append(f"[{index}] {text[:220]}")
    return "已检索到相关片段，但当前 LLM 未配置或不可用，先返回可参考内容：\n" + "\n".join(snippets)


def _resolve_retrieval_scope(
    state: Dict[str, Any],
    knowledge_base_id: str,
    question: str,
) -> Tuple[str, str, List[Dict[str, Any]], List[Dict[str, Any]]]:
    knowledge_bases = state["knowledge_bases"]
    if not knowledge_bases:
        raise ValueError("暂无可用知识库，请先上传文件或切换到普通问答。")

    if knowledge_base_id and knowledge_base_id != ALL_KNOWLEDGE_BASES:
        kb = _find_kb(state, knowledge_base_id)
        return "single", kb["id"], [kb], _retrieve(kb, question)

    matched_kb = _match_kb_by_name(question, knowledge_bases)
    if matched_kb:
        return "matched", matched_kb["id"], [matched_kb], _retrieve(matched_kb, question)

    if len(knowledge_bases) > KNOWLEDGE_BASE_SCAN_THRESHOLD:
        return "all_name_unmatched", ALL_KNOWLEDGE_BASES, knowledge_bases, _retrieve_all(knowledge_bases, question)

    return "all", ALL_KNOWLEDGE_BASES, knowledge_bases, _retrieve_all(knowledge_bases, question)


def rag_chat(knowledge_base_id: str, message: str, conversation_id: str = "", conversation_type: str = "assistant") -> Dict[str, Any]:
    question = message.strip()
    if not question:
        raise ValueError("问题不能为空。")
    if knowledge_base_id == TOOLS_ONLY:
        raise ValueError("当前模式为普通问答，不能调用知识库检索。")

    with _LOCK:
        state = _load_state()
        route_mode, resolved_knowledge_base_id, scoped_kbs, sources = _resolve_retrieval_scope(
            state,
            knowledge_base_id,
            question,
        )

    history_before: List[Dict[str, str]] = []
    if conversation_id:
        try:
            history_before = list(get_db_conversation(conversation_id).get("messages", []))
        except Exception:
            history_before = []

    try:
        require_llm_ready()
        if HumanMessage is None:
            raise RuntimeError("缺少 langchain_core，无法调用 LLM。")
        answer_payload = _answer_with_tools(question, history_before, sources)
        answer = answer_payload["answer"]
        tools_used = answer_payload.get("tools_used", [])
    except Exception:
        answer = _fallback_answer(sources)
        tools_used = []

    saved_conversation = save_db_conversation_exchange(
        message=question,
        answer=answer,
        conversation_id=conversation_id,
        conversation_type=conversation_type,
        knowledge_base_id=resolved_knowledge_base_id,
        sources=[*sources, *_tool_sources(tools_used)],
    )

    return {
        "conversation_id": saved_conversation["id"],
        "answer": answer,
        "sources": sources,
        "tools_used": tools_used,
        "route": {
            "mode": route_mode,
            "knowledge_base_id": resolved_knowledge_base_id,
            "knowledge_base_names": [kb["name"] for kb in scoped_kbs],
        },
        "history": saved_conversation["messages"],
    }


def rag_chat_stream_events(
    knowledge_base_id: str,
    message: str,
    conversation_id: str = "",
    conversation_type: str = "assistant",
) -> Iterator[Dict[str, Any]]:
    question = message.strip()
    if not question:
        raise ValueError("问题不能为空。")
    if knowledge_base_id == TOOLS_ONLY:
        raise ValueError("当前模式为普通问答，不能调用知识库检索。")

    yield {"event": "meta", "data": {"status": "retrieving"}}
    with _LOCK:
        state = _load_state()
        route_mode, resolved_knowledge_base_id, scoped_kbs, sources = _resolve_retrieval_scope(
            state,
            knowledge_base_id,
            question,
        )

    route = {
        "mode": route_mode,
        "knowledge_base_id": resolved_knowledge_base_id,
        "knowledge_base_names": [kb["name"] for kb in scoped_kbs],
    }
    yield {"event": "sources", "data": {"sources": sources, "route": route}}

    history_before: List[Dict[str, str]] = []
    if conversation_id:
        try:
            history_before = list(get_db_conversation(conversation_id).get("messages", []))
        except Exception:
            history_before = []

    answer_parts: List[str] = []
    tools_used: List[str] = []
    try:
        require_llm_ready()
        if HumanMessage is None:
            raise RuntimeError("缺少 langchain_core，无法调用 LLM。")
        yield {"event": "meta", "data": {"status": "answering"}}
        from .mcp_client import MCPClient
        from .tools import server as mcp_server

        tool_message = _build_tool_aware_message(question, history_before, sources)
        for item in MCPClient(mcp_server).stream_chat_with_tools_events(tool_message, tool_selection_message=question):
            if item["event"] == "tool":
                tool_name = item["data"]["name"]
                if tool_name not in tools_used:
                    tools_used.append(tool_name)
                yield item
            elif item["event"] == "delta":
                text = item["data"].get("text", "")
                answer_parts.append(text)
                yield item
            elif item["event"] == "done":
                tools_used = item["data"].get("tools_used", tools_used)
    except Exception:
        answer = _fallback_answer(sources)
        answer_parts = [answer]
        yield {"event": "delta", "data": {"text": answer}}

    answer = "".join(answer_parts)
    all_sources = [*sources, *_tool_sources(tools_used)]
    saved_conversation = save_db_conversation_exchange(
        message=question,
        answer=answer,
        conversation_id=conversation_id,
        conversation_type=conversation_type,
        knowledge_base_id=resolved_knowledge_base_id,
        sources=all_sources,
    )
    yield {
        "event": "done",
        "data": {
            "conversation_id": saved_conversation["id"],
            "answer": answer,
            "sources": all_sources,
            "tools_used": tools_used,
            "route": route,
            "history": saved_conversation["messages"],
        },
    }


def _text_chunks(text: str, size: int = 28) -> Iterator[str]:
    for index in range(0, len(text), size):
        yield text[index : index + size]


def mcp_chat_stream_events(message: str, conversation_id: str = "") -> Iterator[Dict[str, Any]]:
    from .mcp_client import MCPClient
    from .tools import server as mcp_server

    question = message.strip()
    if not question:
        raise ValueError("问题不能为空。")
    yield {"event": "meta", "data": {"status": "thinking"}}
    history_before: List[Dict[str, str]] = []
    if conversation_id:
        try:
            history_before = list(get_db_conversation(conversation_id).get("messages", []))
        except Exception:
            history_before = []
    if history_before:
        question_for_tools = f"历史会话：\n{_format_history(history_before)}\n\n用户问题：{question}"
    else:
        question_for_tools = question
    answer_parts: List[str] = []
    tools_used: List[str] = []
    for item in MCPClient(mcp_server).stream_chat_with_tools_events(question_for_tools, tool_selection_message=question):
        if item["event"] == "tool":
            tool_name = item["data"]["name"]
            if tool_name not in tools_used:
                tools_used.append(tool_name)
            yield item
        elif item["event"] == "delta":
            text = item["data"].get("text", "")
            answer_parts.append(text)
            yield item
        elif item["event"] == "done":
            tools_used = item["data"].get("tools_used", tools_used)

    answer = "".join(answer_parts)
    conversation = save_mcp_exchange(question, answer, conversation_id, tools_used)
    yield {
        "event": "done",
        "data": {
            "conversation_id": conversation["conversation_id"],
            "answer": answer,
            "sources": [],
            "tools_used": tools_used,
            "history": conversation["history"],
        },
    }


def _tool_sources(tools_used: List[str]) -> List[Dict[str, Any]]:
    return [
        {
            "id": f"tool-{index}-{name}",
            "type": "tool",
            "name": name,
        }
        for index, name in enumerate(tools_used, start=1)
    ]


def save_mcp_exchange(
    message: str,
    answer: str,
    conversation_id: str = "",
    tools_used: List[str] | None = None,
) -> Dict[str, Any]:
    tools_used = tools_used or []
    conversation = save_db_conversation_exchange(
        message=message,
        answer=answer,
        conversation_id=conversation_id,
        conversation_type="assistant",
        knowledge_base_id="",
        sources=_tool_sources(tools_used),
    )
    return {
        "conversation_id": conversation["id"],
        "answer": answer,
        "tools_used": tools_used,
        "history": conversation["messages"],
    }

import json
import os
import re
from typing import Any, Dict, List, Optional

from .config import DEFAULT_BASE_URL, DEFAULT_MODEL

'''
LLM调用配置与处理、Prompt模板构造
'''
LANGCHAIN_IMPORT_ERROR: Optional[ImportError] = None

# Langchain导入
try:
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_openai import ChatOpenAI
except ImportError as exc:
    AIMessage = None
    HumanMessage = None
    ToolMessage = None
    ChatPromptTemplate = None
    ChatOpenAI = None
    LANGCHAIN_IMPORT_ERROR = exc

# 初始化ChatOpenAI客户端
llm = None
if ChatOpenAI is not None:
    llm = ChatOpenAI(
        api_key=os.getenv("AI_BAILIAN_API_KEY"),
        base_url=os.getenv("BASE_URL") or DEFAULT_BASE_URL,
        model=os.getenv("MODEL_NAME") or DEFAULT_MODEL,
        temperature=0.3,
        max_tokens=1000,
    )


# langchain和API判断是否可用
def require_llm_ready() -> None:
    if LANGCHAIN_IMPORT_ERROR is not None or llm is None:
        raise RuntimeError(
            "缺少 LLM 依赖，请先安装 `langchain-core` 和 `langchain-openai`。"
        ) from LANGCHAIN_IMPORT_ERROR
    if not os.getenv("AI_BAILIAN_API_KEY"):
        raise RuntimeError("缺少环境变量 AI_BAILIAN_API_KEY，无法调用 LLM。")


# 构建 Prompt
def build_prompt(messages: List[Any]) -> Any:
    require_llm_ready()
    return ChatPromptTemplate.from_messages(messages)


# 处理 LLM 输出，确保返回字符串
def normalize_content(content: Any) -> str:
    # 字符串直接返回
    if isinstance(content, str):
        return content
    # 列表转为字符串
    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            else:
                parts.append(str(item))
        return "".join(parts)
    return str(content)


# 字符串转为 JSON
def extract_json_object(text: str) -> Dict[str, Any]:
    text = text.strip()
    fenced_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.S)
    candidate = fenced_match.group(1) if fenced_match else text
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"LLM 未返回合法 JSON：{text}")
    return json.loads(candidate[start: end + 1])


# 调用 LLM
def invoke_llm_json(prompt: Any, **kwargs: Any) -> Dict[str, Any]:
    require_llm_ready()
    response = llm.invoke(
        prompt.format_messages(**kwargs),  # 输入 Prompt
        extra_body={"enable_thinking": False},  # 禁用 LLM 思考，防止干扰结构化输出
    )
    return extract_json_object(normalize_content(response.content))

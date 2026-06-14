import json
import re
from typing import Any, Dict, Iterator, List, Optional

from .config import MAX_TOOL_ROUNDS
from .llm import AIMessage, HumanMessage, ToolMessage, build_prompt, llm, normalize_content, require_llm_ready
from .mcp_server import MCPServer

'''
与LLM对话、管理工具调用流程
'''


class MCPClient:
    """与 MCPServer 和 LLM 协作完成工具调用。"""

    def __init__(self, server: MCPServer):
        self.server = server
        self.tools_schema: Optional[List[Dict[str, Any]]] = None

    # 根据用户消息选择工具
    def get_tools_for_llm(self, user_message: str = "") -> List[Dict[str, Any]]:
        return self.server.list_tools(user_message)

    def chat_with_tools_detail(
            self,
            user_message: str,
            tool_selection_message: str = "",
    ) -> Dict[str, Any]:
        result = None
        # 流式响应
        for event in self.stream_chat_with_tools_events(user_message, tool_selection_message):
            if event["event"] == "done":
                result = event["data"]
        if not result:
            raise RuntimeError("工具调用未返回结果。")
        return {
            "answer": result["answer"],
            "tools_used": result.get("tools_used", []),
            "history": result.get("history", []),
        }

    def chat_with_tools(self, user_message: str) -> str:
        return self.chat_with_tools_detail(user_message)["answer"]

    # 流式处理，ReAct循环
    def stream_chat_with_tools_events(
            self,
            user_message: str,
            tool_selection_message: str = "",
    ) -> Iterator[Dict[str, Any]]:
        require_llm_ready()
        if HumanMessage is None or ToolMessage is None or AIMessage is None:
            raise RuntimeError("当前环境缺少 langchain_core，无法执行 MCP 工具调用。")

        print(f"\n用户：{user_message}")
        tools = self.get_tools_for_llm(tool_selection_message or user_message)
        print(f"MCP Client 已加载 {len(tools)} 个工具。")

        tool_names = self._tool_names(tools)
        if len(tool_names) > 1 and self._should_use_planned_chain(tool_names):
            yield from self._stream_planned_tool_chain(user_message, tool_names)
            return

        llm_with_tools = llm.bind_tools(tools, parallel_tool_calls=True)
        messages: List[Any] = [HumanMessage(content=user_message)]
        tools_used: List[str] = []

        # 多轮工具调用循环
        for _ in range(MAX_TOOL_ROUNDS):
            accumulated = None
            streamed_text_parts: List[str] = []
            for chunk in llm_with_tools.stream(messages, extra_body={"enable_thinking": False}):
                accumulated = chunk if accumulated is None else accumulated + chunk
                text = normalize_content(getattr(chunk, "content", ""))
                if text:
                    streamed_text_parts.append(text)
                    yield {"event": "delta", "data": {"text": text}}

            if accumulated is None:
                raise RuntimeError("LLM 未返回任何内容。")

            tool_calls = list(getattr(accumulated, "tool_calls", []) or [])
            if not tool_calls:
                final_answer = "".join(streamed_text_parts).strip() or normalize_content(
                    getattr(accumulated, "content", "")).strip()
                print(f"AI：{final_answer}")
                yield {
                    "event": "done",
                    "data": {
                        "answer": final_answer,
                        "tools_used": tools_used,
                        "history": self._message_history_snapshot(messages, final_answer),
                    },
                }
                return

            print(f"LLM 请求调用工具：{[tool_call['name'] for tool_call in tool_calls]}")
            ai_message = AIMessage(
                content=normalize_content(getattr(accumulated, "content", "")),
                tool_calls=tool_calls,
                invalid_tool_calls=list(getattr(accumulated, "invalid_tool_calls", []) or []),
                response_metadata=dict(getattr(accumulated, "response_metadata", {}) or {}),
                additional_kwargs=dict(getattr(accumulated, "additional_kwargs", {}) or {}),
                id=getattr(accumulated, "id", None),
            )
            messages.append(ai_message)

            # 执行工具调用
            for tool_call in tool_calls:
                tool_name = tool_call["name"]
                arguments = self._normalize_tool_args(tool_call.get("args"))
                if tool_name not in tools_used:
                    tools_used.append(tool_name)
                print(f"  -> 调用 {tool_name}({arguments})")
                result_str = self.server.call_tool(tool_name, arguments)
                print(f"  -> 返回 {result_str[:120]}")
                yield {"event": "tool", "data": {"name": tool_name, "arguments": arguments, "result": result_str}}
                messages.append(ToolMessage(content=result_str, tool_call_id=tool_call["id"]))

        raise RuntimeError(f"超过最大工具调用轮数 {MAX_TOOL_ROUNDS}，请缩小问题范围后重试。")

    # 确定的工具调用链
    def _stream_planned_tool_chain(self, user_message: str, tool_names: List[str]) -> Iterator[Dict[str, Any]]:
        ordered_tools = self._ordered_tool_names(tool_names)  # 工具调用优先级
        context: Dict[str, Any] = {
            "raw_message": user_message,
            "position": self._extract_position_hint(user_message),
            "history_text": user_message,
            "resume_summary": "",
            "summary": "",
            "analysis_summary": "",
            "job_description": user_message,
        }
        tools_used: List[str] = []
        tool_results: List[Dict[str, Any]] = []

        print(f"多工具计划：{ordered_tools}")
        for tool_name in ordered_tools:
            arguments = self._build_planned_tool_args(tool_name, context)
            if tool_name not in tools_used:
                tools_used.append(tool_name)
            print(f"  -> 计划调用 {tool_name}({arguments})")
            result_str = self.server.call_tool(tool_name, arguments)
            print(f"  -> 返回 {result_str[:120]}")
            yield {"event": "tool", "data": {"name": tool_name, "arguments": arguments, "result": result_str}}
            parsed_result = self._parse_tool_result(result_str)
            tool_results.append(
                {
                    "name": tool_name,
                    "arguments": arguments,
                    "result": parsed_result,
                    "raw": result_str,
                }
            )
            self._update_planned_context(tool_name, parsed_result, context, result_str)

        final_prompt = self._build_planned_final_prompt(user_message, tool_results, context)
        final_parts: List[str] = []
        for chunk in llm.stream(final_prompt.format_messages(), extra_body={"enable_thinking": False}):
            text = normalize_content(getattr(chunk, "content", ""))
            if text:
                final_parts.append(text)
                yield {"event": "delta", "data": {"text": text}}

        final_answer = "".join(final_parts).strip()
        if not final_answer:
            final_answer = self._format_planned_summary(tool_results, context)
            if final_answer:
                yield {"event": "delta", "data": {"text": final_answer}}

        yield {
            "event": "done",
            "data": {
                "answer": final_answer,
                "tools_used": tools_used,
                "history": [
                    {"role": "user", "content": user_message},
                    {"role": "assistant", "content": final_answer},
                ],
            },
        }

    @staticmethod
    def _tool_names(tools: List[Dict[str, Any]]) -> List[str]:
        names: List[str] = []
        for schema in tools:
            function = schema.get("function", {})
            name = str(function.get("name", "")).strip()
            if name and name not in names:
                names.append(name)
        return names

    # 工具组合
    @staticmethod
    def _should_use_planned_chain(tool_names: List[str]) -> bool:
        required_pairs = [
            {"summarize_conversation", "generate_questions"},
            {"analyze_resume", "generate_questions"},
            {"extract_job_requirements", "generate_questions"},
        ]
        selected = set(tool_names)
        return any(pair.issubset(selected) for pair in required_pairs)

    # 工具调用优先级排序
    @staticmethod
    def _ordered_tool_names(tool_names: List[str]) -> List[str]:
        priority = {
            "analyze_resume": 10,  # 分析简历
            "summarize_conversation": 20,  # 总结对话
            "extract_job_requirements": 30,  # 提取职位要求
            "evaluate_answer": 40,  # 评价回答
            "improve_interview_answer": 50,  # 改进回答
            "generate_questions": 60,  # 生成问题
        }
        unique_names: List[str] = []
        for name in tool_names:
            if name not in unique_names:
                unique_names.append(name)
        return sorted(unique_names, key=lambda name: priority.get(name, 100))

    # 参数构建
    def _build_planned_tool_args(self, tool_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        raw_message = str(context.get("raw_message", ""))
        if tool_name == "summarize_conversation":
            return {"notes": raw_message[:8000]}
        if tool_name == "analyze_resume":
            return {"resume_text": raw_message[:8000]}
        if tool_name == "extract_job_requirements":
            return {"job_description": raw_message[:8000]}
        if tool_name == "generate_questions":
            position = self._extract_position_hint(raw_message) or str(context.get("position", "")).strip() or "技术面试岗位"
            resume_summary = (
                    str(context.get("analysis_summary") or context.get("summary") or context.get(
                        "resume_summary") or "")
                    .strip()
                    or raw_message[:4000]
            )
            return {
                "position": position,
                "resume_summary": resume_summary,
            }
        if tool_name == "evaluate_answer":
            return {
                "question": self._extract_question_hint(raw_message),
                "answer": self._extract_answer_hint(raw_message),
            }
        if tool_name == "improve_interview_answer":
            return {
                "question": self._extract_question_hint(raw_message),
                "answer": self._extract_answer_hint(raw_message),
            }
        return {}

    # 从文本中提取职位
    @staticmethod
    def _extract_position_hint(text: str) -> str:
        candidates = [
            r"岗位[:：]\s*([^\n，,。]{2,40})",
            r"职位[:：]\s*([^\n，,。]{2,40})",
            r"面试岗位[:：]?\s*([^\n，,。]{2,40})",
            r"岗位是\s*([^\n，,。]{2,40})",
        ]
        for pattern in candidates:
            match = re.search(pattern, text)
            if match:
                return match.group(1).strip()
        return ""

    # 从文本中提取问题
    @staticmethod
    def _extract_question_hint(text: str) -> str:
        match = re.search(r"问题[:：]\s*([^\n]+)", text)
        return match.group(1).strip() if match else text[:500]

    # 从文本中提取答案
    @staticmethod
    def _extract_answer_hint(text: str) -> str:
        match = re.search(r"回答[:：]\s*([^\n]+)", text)
        return match.group(1).strip() if match else ""

    # 解析工具结果
    @staticmethod
    def _parse_tool_result(result_str: str) -> Dict[str, Any]:
        try:
            payload = json.loads(result_str)
            return payload if isinstance(payload, dict) else {"value": payload}
        except Exception:
            return {"text": result_str}

    # 根据工具名更新上下文
    def _update_planned_context(
            self,
            tool_name: str,
            parsed_result: Dict[str, Any],
            context: Dict[str, Any],
            raw_result: str,
    ) -> None:
        if tool_name == "analyze_resume":
            context["analysis_summary"] = str(parsed_result.get("summary", "")).strip()
            context["resume_summary"] = context["analysis_summary"] or context.get("resume_summary", "")
        elif tool_name == "summarize_conversation":
            context["summary"] = str(parsed_result.get("summary", "")).strip()
            context["resume_summary"] = context["summary"] or context.get("resume_summary", "")
        elif tool_name == "extract_job_requirements":
            context["job_requirements"] = parsed_result
            role = str(parsed_result.get("role", "")).strip()
            if role:
                context["position"] = role
        elif tool_name == "generate_questions":
            context["questions"] = parsed_result.get("questions", [])
        elif tool_name == "evaluate_answer":
            context["evaluation"] = parsed_result
        elif tool_name == "improve_interview_answer":
            context["improved_answer"] = str(parsed_result.get("improved_answer", "")).strip()
        context.setdefault("tool_outputs", []).append(
            {
                "name": tool_name,
                "result": parsed_result,
                "raw": raw_result,
            }
        )

    # 构建计划生成的最终提示词
    def _build_planned_final_prompt(
            self,
            user_message: str,
            tool_results: List[Dict[str, Any]],
            context: Dict[str, Any],
    ):
        tool_summary = json.dumps(tool_results, ensure_ascii=False, indent=2)
        system_message = (
            "你是一名中文面试助手。请根据工具输出生成最终回复。"
            "如果已经生成了总结和面试问题，请先总结，再列出问题。"
            "回答要自然、简洁，且不要提及内部推理过程。"
        )
        human_message = (
            f"用户请求：{user_message}\n\n"
            f"可用工具结果：\n{tool_summary}\n\n"
            f"补充上下文：\n{json.dumps(context, ensure_ascii=False, indent=2)}"
        )
        return build_prompt([("system", system_message), ("human", human_message)])

    # 格式化总结与问题
    @staticmethod
    def _format_planned_summary(tool_results: List[Dict[str, Any]], context: Dict[str, Any]) -> str:
        parts: List[str] = []
        summary = str(context.get("summary") or context.get("analysis_summary") or "").strip()
        questions = context.get("questions") or []
        if summary:
            parts.append(f"总结：{summary}")
        if questions:
            parts.append(
                "面试问题：\n" + "\n".join(f"{index + 1}. {question}" for index, question in enumerate(questions[:3])))
        if not parts:
            parts.append("已完成多工具处理。")
        return "\n\n".join(parts)

    # 标准化参数
    @staticmethod
    def _normalize_tool_args(arguments: Any) -> Dict[str, Any]:
        if isinstance(arguments, dict):
            return arguments
        if isinstance(arguments, str) and arguments.strip():
            try:
                payload = json.loads(arguments)
                return payload if isinstance(payload, dict) else {"value": payload}
            except Exception:
                return {"value": arguments}
        return {}

    # 生成消息历史快照
    @staticmethod
    def _message_history_snapshot(messages: List[Any], final_answer: str) -> List[Dict[str, str]]:
        history: List[Dict[str, str]] = []
        for item in messages:
            role = getattr(item, "type", "")
            if role == "human":
                history.append({"role": "user", "content": normalize_content(getattr(item, "content", ""))})
            elif role == "ai":
                history.append({"role": "assistant", "content": normalize_content(getattr(item, "content", ""))})
        if final_answer:
            history.append({"role": "assistant", "content": final_answer})
        return history

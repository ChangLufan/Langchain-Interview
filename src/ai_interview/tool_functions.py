from typing import Any, Dict, List

from .llm import build_prompt, invoke_llm_json

'''
Skill.md-func脚本
'''

# 从JD中提取职位要求
def extract_job_requirements(job_description: str) -> Dict[str, Any]:
    """Extract structured interview requirements from a job description."""
    text = job_description.strip()
    if not text:
        raise ValueError("job_description cannot be empty")

    prompt = build_prompt(
        [
            (
                "system",
                (
                    "You are a recruiting analyst. Extract strict JSON only. "
                    "Schema: {{\"role\": \"...\", \"must_have_skills\": [\"...\"], "
                    "\"nice_to_have_skills\": [\"...\"], \"responsibilities\": [\"...\"], "
                    "\"interview_focus\": [\"...\"]}}."
                ),
            ),
            ("human", "Job description:\n{job_description}"),
        ]
    )
    result = invoke_llm_json(prompt, job_description=text[:6000])
    return {
        "role": str(result.get("role", "")).strip(),
        "must_have_skills": _string_list(result.get("must_have_skills", []), 8),
        "nice_to_have_skills": _string_list(result.get("nice_to_have_skills", []), 8),
        "responsibilities": _string_list(result.get("responsibilities", []), 8),
        "interview_focus": _string_list(result.get("interview_focus", []), 8),
    }


# 针对用户面试回答给出更好的回答版本、缺口和改进建议
def improve_interview_answer(question: str, answer: str) -> Dict[str, Any]:
    """Suggest concise improvements for a candidate answer."""
    if not question.strip():
        raise ValueError("question cannot be empty")
    if not answer.strip():
        return {
            "improved_answer": "",
            "gaps": ["候选人未作答。"],
            "suggestions": ["先补充思路、关键技术点和实际项目细节。"],
        }

    prompt = build_prompt(
        [
            (
                "system",
                (
                    "You are a technical interview coach. Return strict JSON only. "
                    "Schema: {{\"improved_answer\": \"...\", \"gaps\": [\"...\"], "
                    "\"suggestions\": [\"...\"]}}. Keep the improved answer under 220 Chinese chars."
                ),
            ),
            ("human", "Question:\n{question}\n\nCandidate answer:\n{answer}"),
        ]
    )
    result = invoke_llm_json(prompt, question=question.strip(), answer=answer.strip())
    return {
        "improved_answer": str(result.get("improved_answer", "")).strip(),
        "gaps": _string_list(result.get("gaps", []), 5),
        "suggestions": _string_list(result.get("suggestions", []), 5),
    }


# 总结对话内容
def summarize_conversation(notes: str) -> Dict[str, Any]:
    """Summarize interview or assistant conversation notes."""
    text = notes.strip()
    if not text:
        raise ValueError("notes cannot be empty")

    prompt = build_prompt(
        [
            (
                "system",
                (
                    "Summarize the conversation as strict JSON only. "
                    "Schema: {{\"summary\": \"...\", \"decisions\": [\"...\"], "
                    "\"follow_ups\": [\"...\"]}}. Keep the summary concise."
                ),
            ),
            ("human", "Conversation notes:\n{notes}"),
        ]
    )
    result = invoke_llm_json(prompt, notes=text[:8000])
    return {
        "summary": str(result.get("summary", "")).strip(),
        "decisions": _string_list(result.get("decisions", []), 6),
        "follow_ups": _string_list(result.get("follow_ups", []), 6),
    }


# 根据用户回答匹配知识库名称
def match_knowledge_base_name(question: str, knowledge_base_names: List[str] | str) -> Dict[str, Any]:
    """Match a user question to a knowledge base name."""
    names = _normalize_names(knowledge_base_names)
    query = question.strip().lower()
    if not query or not names:
        return {"matched": False, "name": "", "reason": "问题或知识库名称为空。"}

    exact = [name for name in names if name.lower() in query]
    if exact:
        return {"matched": True, "name": exact[0], "reason": "问题中直接提到了知识库名称。"}

    prompt = build_prompt(
        [
            (
                "system",
                (
                    "You are a knowledge-base router. Return strict JSON only. "
                    "Schema: {{\"matched\": true, \"name\": \"...\", \"reason\": \"...\"}}. "
                    "If no name is clearly referenced, set matched=false and name=\"\"."
                ),
            ),
            ("human", "Knowledge base names:\n{names}\n\nQuestion:\n{question}"),
        ]
    )
    result = invoke_llm_json(prompt, names="\n".join(names), question=question.strip())
    matched_name = str(result.get("name", "")).strip()
    return {
        "matched": bool(result.get("matched")) and matched_name in names,
        "name": matched_name if matched_name in names else "",
        "reason": str(result.get("reason", "")).strip(),
    }


def _string_list(value: Any, limit: int) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()][:limit]


def _normalize_names(value: List[str] | str) -> List[str]:
    if isinstance(value, str):
        raw_items = value.replace("，", ",").split(",")
    else:
        raw_items = value
    return [str(item).strip() for item in raw_items if str(item).strip()]

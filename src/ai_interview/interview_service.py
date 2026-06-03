from typing import Any, Dict, List

from .config import MAX_RESUME_CHARS
from .llm import build_prompt, invoke_llm_json
from .resume_loader import load_resume_text


def analyze_resume(resume_text: str) -> Dict[str, Any]:
    """使用 Tika 解析简历文件或直接分析传入的简历文本。"""
    parsed_text, source_meta = load_resume_text(resume_text)
    prompt = build_prompt(
        [
            (
                "system",
                (
                    "你是一名资深技术面试官。请阅读候选人简历，输出严格 JSON。"
                    'JSON 结构必须为 {{"summary": "...", "highlights": ["..."], "risk_flags": ["..."]}}。'
                    "要求：summary 不超过 120 字；highlights 输出 3 到 5 条；"
                    "risk_flags 输出 2 到 5 条，如果信息不足请明确写出风险点。"
                    "除了 JSON 不要输出任何其他内容。"
                ),
            ),
            ("human", "简历文本如下：\n{resume_content}"),
        ]
    )
    result = invoke_llm_json(prompt, resume_content=parsed_text[:MAX_RESUME_CHARS])

    summary = str(result.get("summary", "")).strip()
    highlights = [str(item).strip() for item in result.get("highlights", []) if str(item).strip()]
    risk_flags = [str(item).strip() for item in result.get("risk_flags", []) if str(item).strip()]

    if not summary:
        raise ValueError("LLM 未返回简历摘要。")

    return {
        "summary": summary,
        "highlights": highlights[:5],
        "risk_flags": risk_flags[:5],
        "source_type": source_meta["source_type"],
        "source_name": source_meta["source_name"],
        "content_type": source_meta.get("content_type"),
    }


def generate_questions(position: str, resume_summary: str) -> Dict[str, Any]:
    """调用 LLM 基于岗位和简历摘要生成面试问题。"""
    if not position.strip():
        raise ValueError("岗位名称不能为空。")
    if not resume_summary.strip():
        raise ValueError("简历摘要不能为空。")

    prompt = build_prompt(
        [
            (
                "system",
                (
                    "你是一名技术面试官。请基于岗位和简历摘要生成 3 个层次递进的技术面试问题，"
                    "覆盖项目深度、基础原理和风险追问。输出严格 JSON。"
                    'JSON 结构必须为 {{"questions": ["问题1", "问题2", "问题3"]}}。'
                    "每个问题只写一句话，避免重复。除了 JSON 不要输出其他内容。"
                ),
            ),
            ("human", "岗位：{position}\n简历摘要：{resume_summary}"),
        ]
    )
    result = invoke_llm_json(prompt, position=position.strip(), resume_summary=resume_summary.strip())

    questions: List[str] = []
    for item in result.get("questions", []):
        question = item.get("question") if isinstance(item, dict) else item
        question_text = str(question).strip()
        if question_text:
            questions.append(question_text)

    if not questions:
        raise ValueError("LLM 未返回有效面试问题。")

    return {"questions": questions[:3]}


def evaluate_answer(question: str, answer: str) -> Dict[str, Any]:
    """调用 LLM 评估候选人回答并给出分数与反馈。"""
    if not question.strip():
        raise ValueError("问题不能为空。")
    if not answer.strip():
        return {
            "is_correct": False,
            "score": 0,
            "feedback": "候选人未作答，无法判断其技术掌握情况。",
            "missing_points": ["请至少给出思路、关键技术点和实践细节。"],
        }

    prompt = build_prompt(
        [
            (
                "system",
                (
                    "你是一名严格但公平的技术面试官。请根据问题和回答评估技术正确性、完整性和工程实践深度，"
                    "输出严格 JSON。"
                    'JSON 结构必须为 {{"is_correct": true, "score": 0, "feedback": "...", "missing_points": ["..."]}}。'
                    "评分范围 0 到 100；feedback 不超过 120 字；missing_points 最多 3 条。"
                    "如果答案有明显技术错误，is_correct 必须为 false 且 score 低于 60。"
                    "除了 JSON 不要输出其他内容。"
                ),
            ),
            ("human", "问题：{question}\n回答：{answer}"),
        ]
    )
    result = invoke_llm_json(prompt, question=question.strip(), answer=answer.strip())

    raw_score = result.get("score", 0)
    try:
        score = max(0, min(100, int(float(raw_score))))
    except (TypeError, ValueError):
        score = 0

    missing_points = [str(item).strip() for item in result.get("missing_points", []) if str(item).strip()]
    feedback = str(result.get("feedback", "")).strip() or "未获得有效评语。"
    is_correct = bool(result.get("is_correct", score >= 60))

    return {
        "is_correct": is_correct,
        "score": score,
        "feedback": feedback,
        "missing_points": missing_points[:3],
    }


def conduct_interview(position: str, resume_source: str) -> Dict[str, Any]:
    """生成问题后通过 CLI 获取候选人回答，再逐题评分。"""
    analysis = analyze_resume(resume_source)
    question_payload = generate_questions(position, analysis["summary"])
    questions = question_payload["questions"]

    evaluations: List[Dict[str, Any]] = []
    for index, question in enumerate(questions, start=1):
        print(f"\n问题 {index}: {question}")
        answer = input("候选人回答：").strip()
        evaluation = evaluate_answer(question, answer)
        evaluations.append(
            {
                "question": question,
                "answer": answer,
                "evaluation": evaluation,
            }
        )

    average_score = 0
    if evaluations:
        average_score = round(
            sum(item["evaluation"]["score"] for item in evaluations) / len(evaluations),
            2,
        )

    return {
        "position": position,
        "resume_analysis": analysis,
        "questions": questions,
        "evaluations": evaluations,
        "average_score": average_score,
    }

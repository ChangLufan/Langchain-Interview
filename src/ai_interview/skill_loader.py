import importlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List

import yaml

from .llm import build_prompt, invoke_llm_json, require_llm_ready


@dataclass(frozen=True)
class ToolSkillSummary:
    name: str
    description: str


@dataclass(frozen=True)
class ToolSkill:
    name: str
    description: str
    func: str
    parameters: Dict[str, Any]
    content: str


def _skill_paths(skill_dir: Path) -> List[Path]:
    if not skill_dir.exists():
        return []
    return sorted(skill_dir.glob("*/SKILL.md"))


def _front_matter(path: Path) -> tuple[str, str]:
    content = path.read_text(encoding="utf-8")
    if not content.startswith("---"):
        raise ValueError(f"{path} missing YAML front matter")
    _, front_matter, body = content.split("---", 2)
    return front_matter.strip(), body.strip()


def _summary_from_front_matter(path: Path) -> ToolSkillSummary:
    in_front_matter = False
    name = ""
    description = ""
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line == "---":
            if in_front_matter:
                break
            in_front_matter = True
            continue
        if not in_front_matter:
            continue
        if line.startswith("name:"):
            name = line.split(":", 1)[1].strip().strip("\"'")
        elif line.startswith("description:"):
            description = line.split(":", 1)[1].strip().strip("\"'")
        if name and description:
            return ToolSkillSummary(name=name, description=description)
    if not name:
        raise ValueError(f"{path} missing name")
    return ToolSkillSummary(name=name, description=description)


def list_skill_summaries(skill_dir: Path) -> List[ToolSkillSummary]:
    return [_summary_from_front_matter(path) for path in _skill_paths(skill_dir)]


def load_skill(skill_dir: Path, name: str) -> ToolSkill:
    for path in _skill_paths(skill_dir):
        summary = _summary_from_front_matter(path)
        if summary.name != name:
            continue
        front_matter, body = _front_matter(path)
        data = yaml.safe_load(front_matter) or {}
        parameters = data.get("parameters") or {}
        if not isinstance(parameters, dict):
            raise ValueError(f"{path} parameters must be an object")
        return ToolSkill(
            name=str(data.get("name") or summary.name),
            description=str(data.get("description") or summary.description),
            func=str(data.get("func") or ""),
            parameters=parameters,
            content=body,
        )
    raise ValueError(f"tool skill not found: {name}")


def resolve_func(func_path: str) -> Callable[..., Any]:
    if ":" not in func_path:
        raise ValueError(f"invalid func path: {func_path}")
    module_name, func_name = func_path.split(":", 1)
    module = importlib.import_module(module_name)
    func = getattr(module, func_name)
    if not callable(func):
        raise ValueError(f"func is not callable: {func_path}")
    return func


def select_skill_names(
    user_message: str,
    summaries: List[ToolSkillSummary],
    max_tools: int = 4,
) -> List[str]:
    if not summaries:
        return []

    names = [item.name for item in summaries]
    llm_selected: List[str] = []
    try:
        require_llm_ready()
        prompt = build_prompt(
            [
                (
                    "system",
                    (
                        "You are a tool router. Choose the most useful tools for the user request. "
                        "Only return strict JSON in this shape: {{\"tools\": [\"tool_name\"]}}. "
                        "Use tool names exactly as provided. Return at most {max_tools} tools."
                    ),
                ),
                (
                    "human",
                    "Available tools:\n{tools}\n\nUser request:\n{message}",
                ),
            ]
        )
        payload = invoke_llm_json(
            prompt,
            max_tools=max_tools,
            tools=json.dumps([item.__dict__ for item in summaries], ensure_ascii=False),
            message=user_message,
        )
        llm_selected = [str(item) for item in payload.get("tools", []) if str(item) in names]
    except Exception:
        pass

    lowered = user_message.lower()
    keyword_selected: List[str] = []

    def add_if_available(name: str) -> None:
        if name in names and name not in keyword_selected:
            keyword_selected.append(name)

    if any(marker in lowered for marker in ("简历", "resume", "候选人")):
        add_if_available("analyze_resume")
    if any(marker in lowered for marker in ("生成问题", "出题", "面试问题", "question")):
        add_if_available("generate_questions")
    if any(marker in lowered for marker in ("评分", "评估", "评价", "打分", "evaluate")):
        add_if_available("evaluate_answer")
    if any(marker in lowered for marker in ("岗位", "jd", "招聘", "职责", "要求")):
        add_if_available("extract_job_requirements")
    if any(marker in lowered for marker in ("优化", "改进", "提升", "润色", "更好的回答")):
        add_if_available("improve_interview_answer")
    if any(marker in lowered for marker in ("总结", "摘要", "归纳", "summary")):
        add_if_available("summarize_conversation")
    if any(marker in lowered for marker in ("知识库名称", "匹配知识库", "路由", "选择知识库")):
        add_if_available("match_knowledge_base_name")

    scored: List[tuple[int, str]] = []
    for item in summaries:
        haystack = f"{item.name} {item.description}".lower()
        score = 0
        for token in lowered.replace("_", " ").split():
            if token and token in haystack:
                score += 1
        for marker in ("简历", "resume"):
            if marker in lowered and marker in haystack:
                score += 3
        for marker in ("问题", "出题", "question"):
            if marker in lowered and marker in haystack:
                score += 2
        for marker in ("评估", "评分", "评价", "evaluate"):
            if marker in lowered and marker in haystack:
                score += 3
        for marker in ("优化", "改进", "提升", "improve"):
            if marker in lowered and marker in haystack:
                score += 2
        if score > 0:
            scored.append((score, item.name))

    scored.sort(reverse=True)

    merged: List[str] = []
    for candidate in [*llm_selected, *keyword_selected, *[name for _, name in scored]]:
        if candidate in names and candidate not in merged:
            merged.append(candidate)
        if len(merged) >= max_tools:
            break

    if merged:
        return merged[:max_tools]
    return names[: min(max_tools, len(names))]

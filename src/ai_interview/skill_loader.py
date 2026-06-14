import importlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List

import yaml

from .llm import build_prompt, invoke_llm_json, require_llm_ready

'''
扫描目录、解析 YAML、工具路由
'''


# 技能摘要
@dataclass(frozen=True)
class ToolSkillSummary:
    name: str
    description: str


# 技能详细描述
@dataclass(frozen=True)
class ToolSkill:
    name: str
    description: str
    func: str  # 函数路径
    parameters: Dict[str, Any]  # 调用参数
    content: str  # 提示词主体


# 查找所有SKILL.md
def _skill_paths(skill_dir: Path) -> List[Path]:
    if not skill_dir.exists():
        return []
    return sorted(skill_dir.glob("*/SKILL.md"))


# 分别获取元数据与正文
def _front_matter(path: Path) -> tuple[str, str]:
    content = path.read_text(encoding="utf-8")
    if not content.startswith("---"):
        raise ValueError(f"{path} missing YAML front matter")
    _, front_matter, body = content.split("---", 2)
    return front_matter.strip(), body.strip()


# 提取SKILL.md中的name、description字段内容
def _summary_from_front_matter(path: Path) -> ToolSkillSummary:
    in_front_matter = False  # 提取摘要部分（name、description）标记
    name = ""
    description = ""
    # 逐行解析md文档
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


# 遍历所有SKILL.md
def list_skill_summaries(skill_dir: Path) -> List[ToolSkillSummary]:
    return [_summary_from_front_matter(path) for path in _skill_paths(skill_dir)]


# 根据传入的Skill名获取其完整信息
def load_skill(skill_dir: Path, name: str) -> ToolSkill:
    for path in _skill_paths(skill_dir):
        summary = _summary_from_front_matter(path)  # 提取摘要字段
        if summary.name != name:
            continue
        front_matter, body = _front_matter(path)  # 获取元数据和正文
        data = yaml.safe_load(front_matter) or {}
        parameters = data.get("parameters") or {}
        if not isinstance(parameters, dict):
            raise ValueError(f"{path} parameters must be an object")
        return ToolSkill(  # 构建工具对象
            name=str(data.get("name") or summary.name),
            description=str(data.get("description") or summary.description),
            func=str(data.get("func") or ""),
            parameters=parameters,
            content=body,
        )
    raise ValueError(f"tool skill not found: {name}")


# 动态导入SKILL.md中的函数脚本
def resolve_func(func_path: str) -> Callable[..., Any]:
    if ":" not in func_path:
        raise ValueError(f"invalid func path: {func_path}")
    module_name, func_name = func_path.split(":", 1)
    module = importlib.import_module(module_name)
    func = getattr(module, func_name)
    if not callable(func):
        raise ValueError(f"func is not callable: {func_path}")
    return func


# 技能选择（LLM+关键词匹配）
def select_skill_names(
        user_message: str,  # 用户消息
        summaries: List[ToolSkillSummary],  # 可用技能摘要列表
        max_tools: int = 4,  # 最大返回工具数
) -> List[str]:
    if not summaries:
        return []

    # 根据LLM语义理解选择工具
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

    # 关键词匹配选择工具
    lowered = user_message.lower()  # 用户消息转小写
    keyword_selected: List[str] = []

    def add_if_available(name: str) -> None:
        if name in names and name not in keyword_selected:
            keyword_selected.append(name)

    # TODO（硬编码）
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

    # 不同工具不同得分
    # TODO（硬编码）
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
            merged.append(candidate)  # 三种方式获取到的工具进行去重合并
        if len(merged) >= max_tools:
            break

    if merged:
        return merged[:max_tools]
    return names[: min(max_tools, len(names))]

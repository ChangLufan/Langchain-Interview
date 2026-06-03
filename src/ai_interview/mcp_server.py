import json
from pathlib import Path
from typing import Any, Callable, Dict, List

from .skill_loader import list_skill_summaries, load_skill, resolve_func, select_skill_names


class MCPServer:
    """注册并执行工具函数。"""

    def __init__(self):
        self._tools: Dict[str, Dict[str, Any]] = {}
        self._skill_dir: Path | None = None

    def register_tool(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        func: Callable,
    ) -> None:
        self._tools[name] = {
            "schema": {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": parameters,
                },
            },
            "func": func,
        }

    def register_skill_directory(self, skill_dir: Path) -> None:
        self._skill_dir = skill_dir

    def list_tool_summaries(self) -> List[Dict[str, str]]:
        summaries = [
            {
                "name": info["schema"]["function"]["name"],
                "description": info["schema"]["function"]["description"],
            }
            for info in self._tools.values()
        ]
        if self._skill_dir:
            for item in list_skill_summaries(self._skill_dir):
                if not any(existing["name"] == item.name for existing in summaries):
                    summaries.append({"name": item.name, "description": item.description})
        return summaries

    def _load_skill_tool(self, name: str) -> None:
        if name in self._tools or not self._skill_dir:
            return
        skill = load_skill(self._skill_dir, name)
        self.register_tool(
            name=skill.name,
            description=skill.description,
            parameters=skill.parameters,
            func=resolve_func(skill.func),
        )

    def list_tools(self, user_message: str = "") -> List[Dict[str, Any]]:
        if self._skill_dir:
            summaries = list_skill_summaries(self._skill_dir)
            selected_names = select_skill_names(user_message, summaries) if user_message else [item.name for item in summaries]
            for name in selected_names:
                self._load_skill_tool(name)
            return [self._tools[name]["schema"] for name in selected_names if name in self._tools]
        return [info["schema"] for info in self._tools.values()]

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> str:
        self._load_skill_tool(name)
        if name not in self._tools:
            return f"错误：未找到工具 {name}"
        try:
            result = self._tools[name]["func"](**arguments)
            return json.dumps(result, ensure_ascii=False) if isinstance(result, dict) else str(result)
        except Exception as exc:
            return f"执行工具 {name} 时出错：{exc}"

import os
import re
from pathlib import Path
from typing import Any, Dict

import yaml
from dotenv import load_dotenv

load_dotenv()

APP_ROOT = Path(__file__).resolve().parents[2]
APP_CONFIG_PATH = APP_ROOT / "config" / "application.yml"
DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen3.6-flash-2026-04-16"
MAX_TOOL_ROUNDS = 8
MAX_RESUME_CHARS = 6000
RESUME_EXTENSIONS = {".pdf", ".doc", ".docx", ".rtf", ".txt", ".md", ".html", ".htm"}


def _resolve_env_placeholders(value: Any) -> Any:
    if not isinstance(value, str):
        return value

    pattern = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::([^}]*))?\}")

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        default = match.group(2) or ""
        return os.getenv(name, default)

    return pattern.sub(replace, value)


def _resolve_config(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _resolve_config(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_config(item) for item in value]
    return _resolve_env_placeholders(value)


def get_app_config() -> Dict[str, Any]:
    if not APP_CONFIG_PATH.exists():
        return {}
    with APP_CONFIG_PATH.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return _resolve_config(data)

import os
import re
from pathlib import Path
from typing import Any, Dict

import yaml
from dotenv import load_dotenv

'''
加载yaml配置、加载系统环境变量
'''
load_dotenv()

APP_ROOT = Path(__file__).resolve().parents[2]
APP_CONFIG_PATH = APP_ROOT / "config" / "application.yml"
DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen3.6-flash-2026-04-16"
MAX_TOOL_ROUNDS = 8
MAX_RESUME_CHARS = 6000
RESUME_EXTENSIONS = {".pdf", ".doc", ".docx", ".rtf", ".txt", ".md", ".html", ".htm"}


# 替换环境变量占位符
def _resolve_env_placeholders(value: Any) -> Any:
    if not isinstance(value, str):
        return value

    # 正则表达式模式用于匹配纯变量名和带默认值的变量
    pattern = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::([^}]*))?\}")

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)  # 变量名
        default = match.group(2) or ""  # 默认值
        return os.getenv(name, default)  # 获取环境变量的值

    return pattern.sub(replace, value)  # 匹配替换


# 针对不同类型配置进行解析获取值
def _resolve_config(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _resolve_config(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_config(item) for item in value]
    return _resolve_env_placeholders(value)


# 加载yaml配置
def get_app_config() -> Dict[str, Any]:
    if not APP_CONFIG_PATH.exists():
        return {}
    with APP_CONFIG_PATH.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return _resolve_config(data)

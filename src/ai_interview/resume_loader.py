import re
from pathlib import Path
from typing import Any, Dict, Tuple

from .config import RESUME_EXTENSIONS


def looks_like_resume_path(value: str) -> bool:
    normalized = value.strip().strip("\"'")
    path = Path(normalized)
    if path.suffix.lower() in RESUME_EXTENSIONS:
        return True
    if "\n" in normalized or len(normalized) > 260:
        return False
    return bool(
        re.match(r"^[A-Za-z]:\\", normalized)
        or normalized.startswith(("./", "../", ".\\", "..\\", "/", "\\"))
    )


def import_tika_parser():
    try:
        from tika import parser
    except ImportError as exc:
        raise RuntimeError(
            "未安装 tika。请先执行 `pip install tika`，并确保本机可用 Java 或可访问 Tika Server。"
        ) from exc
    return parser


def clean_resume_text(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def load_resume_text(resume_source: str) -> Tuple[str, Dict[str, Any]]:
    raw_value = (resume_source or "").strip()
    if not raw_value:
        raise ValueError("简历内容不能为空。")

    normalized_value = raw_value.strip("\"'")
    path = Path(normalized_value).expanduser()

    if path.exists() and path.is_file():
        parser = import_tika_parser()
        try:
            parsed = parser.from_file(str(path.resolve()))
        except Exception as exc:
            raise RuntimeError(f"Tika 解析简历失败：{exc}") from exc

        content = clean_resume_text((parsed or {}).get("content", "") or "")
        if not content:
            raise ValueError(f"Tika 未能从简历文件中解析出文本：{path}")

        metadata = (parsed or {}).get("metadata", {}) or {}
        return content, {
            "source_type": "file",
            "source_name": path.name,
            "content_type": metadata.get("Content-Type"),
        }

    if looks_like_resume_path(normalized_value):
        raise FileNotFoundError(f"简历文件不存在：{normalized_value}")

    return clean_resume_text(raw_value), {
        "source_type": "text",
        "source_name": "inline_text",
        "content_type": "text/plain",
    }

import os
from typing import List

from openai import OpenAI

from .config import DEFAULT_BASE_URL, get_app_config


def _embedding_model() -> str:
    return str(get_app_config().get("embedding", {}).get("model") or "text-embedding-v4")


def _embedding_batch_size() -> int:
    raw_value = get_app_config().get("embedding", {}).get("batch-size") or 10
    try:
        return max(1, min(10, int(raw_value)))
    except (TypeError, ValueError):
        return 10


def embed_texts(texts: List[str]) -> List[List[float]]:
    clean_texts = [text.strip() for text in texts if text.strip()]
    if not clean_texts:
        return []

    api_key = os.getenv("AI_BAILIAN_API_KEY")
    if not api_key:
        raise RuntimeError("缺少环境变量 AI_BAILIAN_API_KEY，无法调用 text-embedding-v4 生成向量。")

    client = OpenAI(
        api_key=api_key,
        base_url=os.getenv("BASE_URL") or DEFAULT_BASE_URL,
    )
    model = _embedding_model()
    batch_size = _embedding_batch_size()
    embeddings: List[List[float]] = []
    for start in range(0, len(clean_texts), batch_size):
        batch = clean_texts[start : start + batch_size]
        response = client.embeddings.create(
            model=model,
            input=batch,
        )
        ordered = sorted(response.data, key=lambda item: item.index)
        embeddings.extend(list(item.embedding) for item in ordered)
    return embeddings

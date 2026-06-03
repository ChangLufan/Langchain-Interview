import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ai_interview.rag_service import _load_state, _persist_vectors_to_postgres, _save_state  # noqa: E402


def main() -> None:
    state = _load_state()
    results = []
    for knowledge_base in state.get("knowledge_bases", []):
        result = _persist_vectors_to_postgres(knowledge_base)
        knowledge_base["database"] = result
        results.append(
            {
                "id": knowledge_base.get("id"),
                "name": knowledge_base.get("name"),
                "stored": result.get("stored"),
                "chunk_count": result.get("chunk_count"),
                "error": result.get("error"),
            }
        )
    _save_state(state)
    print(json.dumps({"items": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

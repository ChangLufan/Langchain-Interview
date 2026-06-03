import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
STATE_PATH = PROJECT_ROOT / ".rag_data" / "state.json"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ai_interview.postgres_store import save_conversation_snapshot  # noqa: E402


def main() -> None:
    if not STATE_PATH.exists():
        print(json.dumps({"migrated": 0}, ensure_ascii=False))
        return

    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    conversations = state.get("conversations", [])
    migrated = []
    for conversation in conversations:
        saved = save_conversation_snapshot(conversation)
        migrated.append({"id": saved["id"], "message_count": len(saved.get("messages", []))})

    state["conversations"] = []
    tmp_path = STATE_PATH.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(STATE_PATH)
    print(json.dumps({"migrated": len(migrated), "items": migrated}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

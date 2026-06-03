from pathlib import Path
import sys
PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ai_interview import (  # noqa: E402,F401
    MCPClient,
    MCPServer,
    analyze_resume,
    conduct_interview,
    create_server,
    evaluate_answer,
    generate_questions,
    server,
)
from ai_interview.cli import main  # noqa: E402


if __name__ == "__main__":
    main()

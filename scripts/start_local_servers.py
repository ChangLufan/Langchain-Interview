import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_ROOT = PROJECT_ROOT / "frontend"
LOG_DIR = PROJECT_ROOT / "logs"
PYTHON = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"


def clean_env() -> dict[str, str]:
    env: dict[str, str] = {}
    seen: set[str] = set()
    for key, value in os.environ.items():
        lower_key = key.lower()
        if lower_key in seen:
            continue
        seen.add(lower_key)
        env[key] = value

    cert = subprocess.check_output(
        [str(PYTHON), "-c", "import certifi; print(certifi.where())"],
        cwd=PROJECT_ROOT,
        text=True,
    ).strip()
    env["SSL_CERT_FILE"] = cert
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def start(name: str, args: list[str], cwd: Path, env: dict[str, str]) -> subprocess.Popen:
    LOG_DIR.mkdir(exist_ok=True)
    stdout = (LOG_DIR / f"{name}.out.log").open("ab")
    stderr = (LOG_DIR / f"{name}.err.log").open("ab")
    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
    return subprocess.Popen(
        args,
        cwd=cwd,
        env=env,
        stdout=stdout,
        stderr=stderr,
        stdin=subprocess.DEVNULL,
        creationflags=creationflags,
    )


def main() -> None:
    env = clean_env()
    api = start(
        "api",
        [str(PYTHON), "scripts/simple_api_server.py"],
        PROJECT_ROOT,
        env,
    )
    frontend = start(
        "frontend",
        [str(PYTHON), "-m", "http.server", "5173", "--bind", "127.0.0.1"],
        FRONTEND_ROOT,
        env,
    )
    (LOG_DIR / "local_server_pids.txt").write_text(
        f"api={api.pid}\nfrontend={frontend.pid}\n",
        encoding="utf-8",
    )
    print(f"api={api.pid}")
    print(f"frontend={frontend.pid}")


if __name__ == "__main__":
    main()

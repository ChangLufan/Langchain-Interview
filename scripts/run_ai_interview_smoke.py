import contextlib
import io
import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from ai_interview.interview_service import analyze_resume, generate_questions  # noqa: E402
from ai_interview.mcp_client import MCPClient  # noqa: E402
from ai_interview.resume_loader import load_resume_text  # noqa: E402
from ai_interview.tools import server  # noqa: E402

PYTHON_EXE = Path(r"F:\PythonProject\pythonProject\.venv\Scripts\python.exe")
RESUME_PATH = "src/interview/interview.pdf"
POSITION = "AI 应用开发工程师（实习）"

ANSWERS = [
    (
        "我会先用 Apache Tika 解析 PDF、Word 等多格式简历，抽取文本后做控制字符、异常换行、空白符和嵌入元素噪声清洗。"
        "进入 LLM 前会限制输入长度，保留教育背景、项目经历、技术栈和求职意向等关键信息。"
        "Prompt 上要求模型只输出固定 JSON，包括 summary、highlights 和 risk_flags；服务层再做 JSON 提取、字段校验、异常兜底和错误提示，保证下游出题模块拿到稳定结构。"
    ),
    (
        "在 RAG 知识库里，我会先按语义段落或标题层级做文档分块，设置合理 chunk size 和 overlap，避免切断关键上下文。"
        "每个块生成向量后存入 pgvector，并用 HNSW 索引提升近邻检索性能。查询阶段会向量化用户问题，召回 TopK 片段，"
        "再结合相似度阈值、元数据过滤和必要的重排序减少无关片段。工程上还要控制上下文长度，避免把低相关内容塞进模型导致 Token 浪费和幻觉。"
    ),
    (
        "Redis Stream 适合把耗时任务从同步请求链路里解耦。接口收到简历分析或向量化请求后，只写入任务消息并返回 taskId；"
        "消费者组异步执行 LLM 调用或 embedding 计算，完成后把状态和结果写回数据库或缓存。这样核心接口不用等待十几秒的推理过程，可以快速响应。"
        "落地时我会处理消息确认、失败重试、幂等键、死信队列和任务状态一致性，避免重复消费或任务丢失。"
    ),
]


def run_mcp_test() -> dict:
    prompt = (
        f"请调用工具分析候选人简历 {RESUME_PATH}，岗位是 {POSITION}。"
        "请先分析简历，再生成 3 个技术面试问题，最后给出简短总结。"
    )
    client = MCPClient(server)
    stdout = io.StringIO()
    result = {"prompt": prompt}
    with contextlib.redirect_stdout(stdout):
        try:
            answer = client.chat_with_tools(prompt)
            result.update({"ok": True, "answer": answer})
        except Exception as exc:
            result.update({"ok": False, "error_type": type(exc).__name__, "error": str(exc)})
    result["stdout"] = stdout.getvalue()
    return result


def run_interactive_test() -> dict:
    stdin_text = "\n".join([*["2", POSITION, RESUME_PATH], *ANSWERS]) + "\n"
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    proc = subprocess.run(
        [str(PYTHON_EXE), "AI_interview.py"],
        input=stdin_text,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        cwd=PROJECT_ROOT,
        env=env,
        timeout=240,
    )
    return {
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "stdin_answers": ANSWERS,
    }


def main() -> None:
    parsed_text, meta = load_resume_text(RESUME_PATH)
    analysis = analyze_resume(RESUME_PATH)
    questions = generate_questions(POSITION, analysis["summary"])["questions"]
    result = {
        "environment": {
            "python": str(PYTHON_EXE),
            "resume_path": RESUME_PATH,
            "position": POSITION,
            "api_key_present": bool(os.getenv("AI_BAILIAN_API_KEY")),
        },
        "resume_parse": {
            "metadata": meta,
            "text_length": len(parsed_text),
            "preview": parsed_text[:800],
        },
        "service_smoke": {
            "analysis": analysis,
            "questions": questions,
        },
        "mcp": run_mcp_test(),
        "interactive": run_interactive_test(),
    }
    (PROJECT_ROOT / "ai_interview_smoke_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("result_file=ai_interview_smoke_result.json")


if __name__ == "__main__":
    main()

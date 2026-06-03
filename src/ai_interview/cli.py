import json

from .interview_service import conduct_interview
from .mcp_client import MCPClient
from .tools import server


def main() -> None:
    print("AI 面试官 Demo")
    mode = input("选择模式：1) MCP 对话 2) 交互式面试，默认 2：").strip() or "2"

    if mode == "1":
        client = MCPClient(server)
        prompt = input("请输入你的问题：").strip()
        if prompt:
            client.chat_with_tools(prompt)
    else:
        position = input("请输入岗位名称，默认 Python 开发工程师：").strip() or "Python 开发工程师"
        resume_source = input("请输入简历文件路径，或直接粘贴简历文本：").strip()
        report = conduct_interview(position, resume_source)
        print("\n面试结果：")
        print(json.dumps(report, ensure_ascii=False, indent=2))

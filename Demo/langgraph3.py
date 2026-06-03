#!/usr/bin/env python3
"""
DeepAgents + DeepSeek 自定义 Skills 完整示例
支持 Windows / macOS / Linux 跨平台
"""

import asyncio
import os
from pathlib import Path
from langchain_openai import ChatOpenAI
from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend

# ============================================================
# 配置区域 - 请根据你的实际情况修改
# ============================================================

# DeepSeek API 配置
# 官方 API
API_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"
API_KEY = os.getenv("AI_BAILIAN_API_KEY")  # 从环境变量获取API密钥

current_root = Path(__file__).parent.resolve()

# 3. skills 目录
skills_dir = current_root / "skill"

# 4. 初始化 Backend（文件系统模式）
backend = FilesystemBackend(
    root_dir=str(current_root),
    virtual_mode=True  # 使用虚拟模式加载技能
)

# 5. 初始化 DeepSeek 模型
deepseek_model = ChatOpenAI(
    api_key=API_KEY,
    base_url=API_BASE,
    model="qwen3.6-flash-2026-04-16",
    temperature=0.3
)

# 6. 创建 DeepAgent（新版 API 正确方式）
agent = create_deep_agent(
    name="ReimbursementAgent",
    model=deepseek_model,
    backend=backend,
    skills=["reimbursement"],
    debug=True
)


def print_teaching_demo(result: dict):
    print("\n" + "=" * 90)
    print("🎓 教学演示：Agent 执行全流程解析")
    print("=" * 90)

    # 1. 打印完整消息历史
    print("\n" + "-" * 90)
    print("💬 1. 完整消息交互链")
    print("-" * 90)

    messages = result.get("messages", [])
    for i, msg in enumerate(messages, 1):
        msg_type = msg.__class__.__name__

        # 角色判断
        if msg_type == "HumanMessage":
            role = "👤 用户"
            box_color = "🟦"
        elif msg_type == "AIMessage":
            role = "🤖 AI 模型"
            box_color = "🟩"
        elif msg_type == "ToolMessage":
            role = "🔧 工具"
            box_color = "🟨"
        else:
            role = "❓ 未知"
            box_color = "⬜"

        print(f"\n{box_color} 【第 {i} 轮】 {role} ({msg_type}) {box_color}")

        # 打印内容
        if msg.content:
            print(f"\n   内容：")
            for line in msg.content.split('\n'):
                print(f"   {line}")

        # 打印 AI 的工具调用
        if msg_type == "AIMessage" and hasattr(msg, 'tool_calls') and msg.tool_calls:
            print(f"\n   🛠️  模型思考：需要调用工具")
            for tc in msg.tool_calls:
                print(f"      → 调用工具：{tc['name']}")
                print(f"      → 输入参数：{tc['args']}")

    # 2. 打印最终结果
    print("\n" + "=" * 90)
    print("✅ 2. 最终结果")
    print("=" * 90)
    print(f"\n{result['messages'][-1].content}")
    print("\n" + "=" * 90)


async def main():
    user_input = """
    帮我整理这些消费：
    1. 3月25号 打车 35元
    2. 3月27号 午餐 68.5元
    3. 3月28号 买文具 120元
    """
    print("===== 整理结果 =====")

    # 这里用 .ainvoke()，输入格式是 LangGraph 标准的 messages 列表
    result = await agent.ainvoke({
        "messages": [("user", user_input)]
    })

    # 输出最后一条消息（AI 的回复）
    print_teaching_demo(result)


if __name__ == "__main__":
    asyncio.run(main())

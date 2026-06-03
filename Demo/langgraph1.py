from typing import TypedDict

import langchain
import langgraph
import openai
import importlib
from dotenv import load_dotenv
import os

from langchain_openai import ChatOpenAI
from langgraph.constants import START, END
from langgraph.graph import StateGraph

# load_dotenv()
# print(langchain.__version__)
# print(importlib.metadata.version('langgraph'))
# print(openai.__version__)
API_KEY = os.getenv("AI_BAILIAN_API_KEY")
BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
llm = ChatOpenAI(model_name="qwen3.6-flash-2026-04-16",
                 temperature=0.9,
                 openai_api_base=BASE_URL,
                 openai_api_key=API_KEY,
                 max_tokens=2000
                 )


# 定义节点
class WorkflowState(TypedDict, total=False):
    user_role: str
    original_prompt: str
    simple_prompt: str


def generate(State: WorkflowState):
    prompt = f"给{State['user_role']}写一段AI学习建议"
    result = llm.invoke(prompt)
    return {"original_prompt": result.content}


def simplify(State: WorkflowState):
    prompt = f"请将{State['original_prompt']}进行精简"
    result = llm.invoke(prompt)
    return {"simple_prompt": result.content}


# 创建工作流
Workflow = StateGraph(WorkflowState)
Workflow.add_node("generate", generate)
Workflow.add_node("simplify", simplify)
Workflow.add_edge(START, "generate")
Workflow.add_edge("generate", "simplify")
Workflow.add_edge("simplify", END)
app = Workflow.compile()

response1 = app.invoke({"user_role": "学生"})
print("原始:" + response1["original_prompt"])
print("精简:" + response1["simple_prompt"])

message = [
    {"role": "system", "content": "你是一个AI助手"},
    {"role": "user", "content": "请给我一个langchain学习建议"}
]
response2 = llm.invoke(message)
print(response2.content)

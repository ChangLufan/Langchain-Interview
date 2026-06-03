import os
from typing import TypedDict, NotRequired

from langchain_core.prompts import PromptTemplate
from langchain_openai import ChatOpenAI
from langgraph.constants import END, START
from langgraph.graph import StateGraph

API_KEY = os.getenv("AI_BAILIAN_API_KEY")
BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
llm = ChatOpenAI(model_name="qwen3.6-flash-2026-04-16",
                 temperature=0.9,
                 openai_api_base=BASE_URL,
                 openai_api_key=API_KEY,
                 max_tokens=2000
                 )


# 状态
class TaskState(TypedDict):
    user_query: str
    tool_result: NotRequired[str]
    final_answer: NotRequired[str]
    process: NotRequired[str]


# 节点函数
def parse_query(state: TaskState):
    print("==========节点1===========")
    prompt = PromptTemplate(
        input_variables=["query"],
        template="请分析用户问题并提取关键信息，输出格式为JSON，简要回答：用户想了解什么？\n问题：{query}"
    )
    chain = prompt | llm
    result = chain.invoke({"query": state["user_query"]})
    # print(state)
    query = state["user_query"]
    update = {
        "tool_result": f"已解决问题：{query}",
        "process": 30
    }
    print(f"解析结果{update}")
    return update


def call_tool(state: TaskState):
    print("==========节点2===========")
    # print(state)
    prompt = PromptTemplate(
        input_variables=["query", "parsed_info"],
        template="基于用户问题：{query}\n和解析信息：{parsed_info}\n请提供详细的工具使用方案。"
    )
    chain = prompt | llm
    result = chain.invoke({"query": state["user_query"],
                           "parsed_info": state["tool_result"]})
    update = {
        "tool_result": result,
        "process": 60
    }
    print(f"工具结果:{update}")
    return update


def generate_answer(state: TaskState):
    print("==========节点3===========")
    prompt = PromptTemplate(
        input_variables=["query", "tool_result"],
        template="基于用户问题：{query}\n和工具结果：{tool_result}\n请生成最终答案。"
    )
    chain = prompt | llm
    # print(state)
    answer = chain.invoke({"query": state["user_query"],
                           "tool_result": state["tool_result"]})
    update = {
        "final_answer": answer,
        "process": 100
    }
    print(f"解决方案:{answer}")
    return update


# 构建Graph
builder = StateGraph(TaskState)
builder.add_node("parse_query", parse_query)
builder.add_node("call_tool", call_tool)
builder.add_node("generate_answer", generate_answer)

builder.add_edge(START, "parse_query")
builder.add_edge("parse_query", "call_tool")
builder.add_edge("call_tool", "generate_answer")
builder.add_edge("generate_answer", END)

graph = builder.compile()

init_state = TaskState(user_query="langgraph和langchain的区别是什么？")
final_answer = graph.invoke(init_state)
print("==========最终结果===========")
print(final_answer['final_answer'])

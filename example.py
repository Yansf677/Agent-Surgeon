from __future__ import annotations

import json
import random
import time

import httpx
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.prompts import ChatPromptTemplate
from openai import OpenAI

from surgeon import AutoGenTraceBridge, DeadLoopError, LangChainTraceHandler, LoopGuard, export_html_report, patch_openai_client, surgeon


class DemoLangChainModel(BaseChatModel):
    model_name: str = "demo-langchain-model"
    scripted_response: str = "Search competitors, estimate upside, then summarize risk."

    @property
    def _llm_type(self) -> str:
        return "demo-langchain-model"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        joined = "\n".join(getattr(message, "content", "") for message in messages)
        reply = self.scripted_response + "\nObserved prompt:\n" + joined[:120]
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=reply))])


@surgeon.trace(metadata={"lane": "classic_decorator"})
def analyze_task(user_goal: str) -> dict:
    time.sleep(0.08)
    return {"goal": user_goal, "intent": "compare tools and produce a recommendation", "risk": "medium"}


@surgeon.trace(metadata={"lane": "classic_decorator"})
def plan_steps(context: dict) -> list:
    time.sleep(0.12)
    return ["search market context", "estimate ROI", "fetch internal notes", "draft final recommendation"]


@surgeon.trace(category="tool", framework="python")
def fake_search_tool(query: str) -> dict:
    time.sleep(0.09)
    return {"top_hit": "Competitor bundle launched last week", "confidence": 0.82, "query": query}


@surgeon.trace(category="tool", framework="python")
def fake_calculator_tool(numbers: list) -> dict:
    time.sleep(0.04)
    return {"inputs": numbers, "projected_uplift_pct": sum(numbers) / len(numbers)}


@surgeon.trace(category="tool", framework="python")
def fake_db_lookup_tool(key: str) -> dict:
    time.sleep(0.02)
    raise RuntimeError("database timeout while reading key={}".format(key))


@surgeon.trace(category="dispatcher", framework="python")
def call_tool(name: str, payload):
    if name == "search":
        return fake_search_tool(payload)
    if name == "calculator":
        return fake_calculator_tool(payload)
    if name == "db_lookup":
        return fake_db_lookup_tool(payload)
    raise ValueError("unknown tool: {}".format(name))


@surgeon.trace(category="recovery", framework="python")
def recover_from_error(step: str, error_message: str) -> dict:
    time.sleep(0.03)
    return {"step": step, "fallback": "continue with partial context", "note": error_message}


@surgeon.trace(category="safety", framework="agent_surgeon")
def simulate_loop_guard() -> dict:
    guard = LoopGuard(max_repeats=3)
    repeated_payload = {"thought": "ask the same pricing question again", "tool": "crm_lookup"}
    last_state = None
    for _ in range(5):
        last_state = guard.observe("planner_retry", repeated_payload)
        time.sleep(0.01)
    return last_state or {}


def _mock_openai_handler(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content.decode("utf-8"))
    if request.url.path.endswith("/chat/completions"):
        message = body.get("messages", [{}])[-1].get("content", "")
        payload = {
            "id": "chatcmpl-mock-001",
            "object": "chat.completion",
            "created": 1710000000,
            "model": body.get("model", "gpt-4o-mini"),
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "Use the bundle test and keep a human on the approval step. Prompt was: {}".format(message)}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 131, "completion_tokens": 29, "total_tokens": 160},
        }
        return httpx.Response(200, json=payload)
    return httpx.Response(404, json={"error": {"message": "mock route missing"}})


def simulate_openai_sdk_call(user_goal: str) -> str:
    client = OpenAI(api_key="demo-key", base_url="https://api.openai.com/v1", http_client=httpx.Client(transport=httpx.MockTransport(_mock_openai_handler)))
    patcher = patch_openai_client(client, recorder=surgeon)
    try:
        response = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "system", "content": "You are a growth copilot."}, {"role": "user", "content": user_goal}])
        return response.choices[0].message.content or ""
    finally:
        patcher.unpatch()


def simulate_langchain_call(user_goal: str) -> str:
    handler = LangChainTraceHandler(recorder=surgeon)
    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are a growth strategist that explains tradeoffs clearly."),
        ("human", "Goal: {goal}"),
    ])
    model = DemoLangChainModel()
    chain = prompt | model
    result = chain.invoke({"goal": user_goal}, config={"callbacks": [handler], "run_name": "growth_research_chain"})
    if isinstance(result, AIMessage):
        return result.content
    return str(result)


def simulate_autogen_bridge(user_goal: str) -> None:
    bridge = AutoGenTraceBridge(recorder=surgeon)
    conversation = bridge.on_conversation_start("planner+critic duo", user_goal, run_id="ag-conv-001")
    bridge.on_message("assistant", "I will draft a plan and then ask the tool runner.", parent_run_id=conversation)
    tool_run = bridge.on_tool_start("sql_runner", {"query": "SELECT uplift_estimate FROM experiments"}, run_id="ag-tool-001", parent_run_id=conversation)
    time.sleep(0.03)
    bridge.on_tool_end(tool_run, {"uplift_estimate": 17.4, "sample_size": 932})
    bridge.on_message("critic", "Numbers look good, but confidence is moderate.", parent_run_id=conversation)
    bridge.on_conversation_end(conversation, {"summary": "AutoGen bridge wrapped with critique."})


@surgeon.trace(name="agent_run", metadata={"product": "Agent-Surgeon"})
def run_agent(user_goal: str) -> dict:
    with surgeon.span("bootstrap:web_replay", framework="agent_surgeon", metadata={"goal": "prepare a screenshot-grade replay"}) as bootstrap:
        bootstrap.set_result({"ui": "web", "style": "glassmorphism + editorial"})

    context = analyze_task(user_goal)
    steps = plan_steps(context)
    search_result = call_tool("search", "best option for: {}".format(context["goal"]))
    calc_result = call_tool("calculator", [12, 18, 21, random.randint(15, 25)])

    try:
        notes_result = call_tool("db_lookup", "pricing-playbook")
    except RuntimeError as exc:
        notes_result = recover_from_error("fetch internal notes", str(exc))

    try:
        simulate_loop_guard()
    except DeadLoopError as exc:
        with surgeon.span("loop_guard:fallback", category="safety", framework="agent_surgeon", metadata=exc.details) as guard_fallback:
            time.sleep(0.02)
            guard_fallback.set_result({"action": "abort repeated hop", "reason": str(exc)})

    langchain_result = simulate_langchain_call(user_goal)
    openai_result = simulate_openai_sdk_call(user_goal)
    simulate_autogen_bridge(user_goal)

    with surgeon.span("synthesis:final_answer", framework="agent_surgeon", metadata={"steps": steps}) as synthesis:
        time.sleep(0.06)
        final_answer = "Recommend the bundle launch, but flag missing internal notes for manual review."
        synthesis.set_result({"final_answer": final_answer, "confidence": "high", "langchain": langchain_result[:120], "openai": openai_result[:120]})

    return {
        "steps": steps,
        "search": search_result,
        "calculator": calc_result,
        "notes": notes_result,
        "langchain": langchain_result,
        "openai_sdk": openai_result,
        "final_answer": final_answer,
    }


def main() -> None:
    surgeon.store.reset()
    result = run_agent("Find the highest-conviction growth experiment for next week")
    report_path = export_html_report()
    print()
    print("=== Agent Result ===")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print()
    print("Trace saved to .surgeon/trace.json")
    print("Web replay exported to {}".format(report_path))
    print("Replay it with: surgeon-view")
    print("Open the screenshot-grade UI with: surgeon-web --open")


if __name__ == "__main__":
    main()

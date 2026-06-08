from __future__ import annotations

import json
import random
import time

from surgeon import AutoGenTraceBridge, DeadLoopError, LangChainTraceHandler, LoopGuard, OpenAIAgentsTracer, export_html_report, surgeon


@surgeon.trace(metadata={"lane": "classic_decorator"})
def analyze_task(user_goal: str) -> dict:
    time.sleep(0.08)
    return {
        "goal": user_goal,
        "intent": "compare tools and produce a recommendation",
        "risk": "medium",
    }


@surgeon.trace(metadata={"lane": "classic_decorator"})
def plan_steps(context: dict) -> list:
    time.sleep(0.12)
    return [
        "search market context",
        "estimate ROI",
        "fetch internal notes",
        "draft final recommendation",
    ]


@surgeon.trace(category="tool", framework="python")
def fake_search_tool(query: str) -> dict:
    time.sleep(0.09)
    return {
        "top_hit": "Competitor bundle launched last week",
        "confidence": 0.82,
        "query": query,
    }


@surgeon.trace(category="tool", framework="python")
def fake_calculator_tool(numbers: list) -> dict:
    time.sleep(0.04)
    return {
        "inputs": numbers,
        "projected_uplift_pct": sum(numbers) / len(numbers),
    }


@surgeon.trace(category="tool", framework="python")
def fake_db_lookup_tool(key: str) -> dict:
    time.sleep(0.02)
    raise RuntimeError(f"database timeout while reading key={key}")


@surgeon.trace(category="dispatcher", framework="python")
def call_tool(name: str, payload):
    if name == "search":
        return fake_search_tool(payload)
    if name == "calculator":
        return fake_calculator_tool(payload)
    if name == "db_lookup":
        return fake_db_lookup_tool(payload)
    raise ValueError(f"unknown tool: {name}")


@surgeon.trace(category="recovery", framework="python")
def recover_from_error(step: str, error_message: str) -> dict:
    time.sleep(0.03)
    return {
        "step": step,
        "fallback": "continue with partial context",
        "note": error_message,
    }


@surgeon.trace(category="safety", framework="agent_surgeon")
def simulate_loop_guard() -> dict:
    guard = LoopGuard(max_repeats=3)
    repeated_payload = {"thought": "ask the same pricing question again", "tool": "crm_lookup"}
    last_state = None
    for _ in range(5):
        last_state = guard.observe("planner_retry", repeated_payload)
        time.sleep(0.01)
    return last_state or {}


def simulate_langchain_hooks(user_goal: str) -> None:
    handler = LangChainTraceHandler(recorder=surgeon)
    chain_run = "lc-chain-001"
    llm_run = "lc-llm-001"
    tool_run = "lc-tool-001"
    handler.on_chain_start({"name": "growth_research_chain", "id": ["demo", "growth_research_chain"]}, {"goal": user_goal}, run_id=chain_run)
    handler.on_llm_start({"name": "gpt-4.1-mini"}, [f"Draft a short search plan for: {user_goal}"], run_id=llm_run, parent_run_id=chain_run)
    time.sleep(0.05)
    handler.on_llm_end({"text": "Search competitors, estimate upside, then summarize risk.", "usage": {"input_tokens": 142, "output_tokens": 38, "total_tokens": 180}}, run_id=llm_run)
    handler.on_tool_start({"name": "web_search"}, "competitor bundle launch", run_id=tool_run, parent_run_id=chain_run)
    time.sleep(0.03)
    handler.on_tool_end({"top_hit": "Launch detected", "score": 0.91}, run_id=tool_run)
    handler.on_chain_end({"summary": "LangChain branch completed."}, run_id=chain_run)


def simulate_openai_agents_hooks(user_goal: str) -> None:
    tracer = OpenAIAgentsTracer(recorder=surgeon)
    agent_run = tracer.on_agent_start("growth_captain", {"goal": user_goal}, run_id="oa-agent-001")
    llm_run = tracer.on_llm_start("gpt-4.1", [{"role": "user", "content": user_goal}], run_id="oa-llm-001", parent_run_id=agent_run)
    time.sleep(0.04)
    tracer.on_llm_end(llm_run, "Need competitor signal plus ROI estimate.", usage={"input_tokens": 168, "output_tokens": 31, "total_tokens": 199})
    tool_run = tracer.on_tool_start("crm_lookup", {"segment": "high intent"}, run_id="oa-tool-001", parent_run_id=agent_run)
    time.sleep(0.02)
    tracer.on_tool_end(tool_run, {"segment_size": 1842, "confidence": 0.74})
    tracer.on_agent_end(agent_run, {"final": "Run the bundle experiment with manual guardrails."})


def simulate_autogen_hooks(user_goal: str) -> None:
    bridge = AutoGenTraceBridge(recorder=surgeon)
    conversation = bridge.on_conversation_start("planner+critic duo", user_goal, run_id="ag-conv-001")
    bridge.on_message("assistant", "I will draft a plan and then ask the tool runner.", parent_run_id=conversation)
    tool_run = bridge.on_tool_start("sql_runner", {"query": "SELECT uplift_estimate FROM experiments"}, run_id="ag-tool-001", parent_run_id=conversation)
    time.sleep(0.03)
    bridge.on_tool_end(tool_run, {"uplift_estimate": 17.4, "sample_size": 932})
    bridge.on_message("critic", "Numbers look good, but confidence is moderate.", parent_run_id=conversation)
    bridge.on_conversation_end(conversation, {"summary": "AutoGen branch wrapped with critique."})


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

    simulate_langchain_hooks(user_goal)
    simulate_openai_agents_hooks(user_goal)
    simulate_autogen_hooks(user_goal)

    with surgeon.span("synthesis:final_answer", framework="agent_surgeon", metadata={"steps": steps}) as synthesis:
        time.sleep(0.06)
        final_answer = "Recommend the bundle launch, but flag missing internal notes for manual review."
        synthesis.set_result({"final_answer": final_answer, "confidence": "high"})

    return {
        "steps": steps,
        "search": search_result,
        "calculator": calc_result,
        "notes": notes_result,
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
    print(f"Web replay exported to {report_path}")
    print("Replay it with: surgeon-view")
    print("Open the screenshot-grade UI with: surgeon-web --open")


if __name__ == "__main__":
    main()

"""Agent assembly and invocation.

Built on ``langchain.agents.create_agent`` (LangChain 1.x), which compiles a
LangGraph state machine: model -> tool calls -> model -> ... until the model
answers without requesting a tool. The graph, not a prompt, enforces the loop
bound, which is why an iteration cap here is a real guarantee rather than a
suggestion to the model.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from hwval.agent.llm import get_chat_model, llm_status
from hwval.agent.prompts import SYSTEM_PROMPT
from hwval.agent.tools import ALL_TOOLS
from hwval.config import get_settings

log = logging.getLogger(__name__)


@dataclass
class AgentRun:
    question: str
    answer: str
    tool_calls: list[dict] = field(default_factory=list)
    elapsed_s: float = 0.0
    provider: str = ""

    def as_dict(self) -> dict:
        return {
            "question": self.question,
            "answer": self.answer,
            "tool_calls": self.tool_calls,
            "elapsed_s": round(self.elapsed_s, 2),
            "provider": self.provider,
        }


def build_agent(tools: list | None = None, model: Any | None = None):
    """Compile the agent graph. Kept separate from ``ask`` so the Streamlit app
    and the MCP server can hold one compiled graph across many questions."""
    from langchain.agents import create_agent

    return create_agent(
        model=model or get_chat_model(),
        tools=tools or ALL_TOOLS,
        system_prompt=SYSTEM_PROMPT,
    )


def _extract(messages: list[Any]) -> tuple[str, list[dict]]:
    answer, calls = "", []
    for m in messages:
        if isinstance(m, AIMessage):
            for tc in getattr(m, "tool_calls", []) or []:
                calls.append({"name": tc.get("name"), "args": tc.get("args", {})})
            if isinstance(m.content, str) and m.content.strip():
                answer = m.content
        elif isinstance(m, ToolMessage):
            for c in calls:
                if c.get("result") is None and c["name"] == (m.name or c["name"]):
                    c["result"] = str(m.content)[:800]
                    break
    return answer, calls


def ask(question: str, agent: Any | None = None, history: list | None = None) -> AgentRun:
    """Run one question through the agent and return the answer plus the tool
    trace (the trace is what makes the run reviewable after the fact)."""
    s = get_settings()
    agent = agent or build_agent()
    messages: list[Any] = list(history or [])
    if not messages:
        messages.append(SystemMessage(content=SYSTEM_PROMPT))
    messages.append(HumanMessage(content=question))

    t0 = time.perf_counter()
    result = agent.invoke(
        {"messages": messages},
        config={"recursion_limit": max(4, s.agent_max_iterations * 2)},
    )
    elapsed = time.perf_counter() - t0
    answer, calls = _extract(result.get("messages", []))
    return AgentRun(
        question=question,
        answer=answer or "(no answer produced)",
        tool_calls=calls,
        elapsed_s=elapsed,
        provider=llm_status()["provider"],
    )


DEMO_QUESTIONS = [
    "What is the yield by PVT corner, and which corner is worst?",
    "Find the 5 most anomalous test runs and explain what failed in each.",
    "Which parameter drives most of the failures? Plot the Pareto.",
    "Run the database maintenance plan and tell me what needs attention.",
    "Generate a test plan for the S32K344 covering supply-droop robustness.",
    "Build the full validation report as HTML.",
]

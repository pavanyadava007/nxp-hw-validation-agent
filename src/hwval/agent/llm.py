"""Provider-agnostic chat-model factory, plus an offline deterministic fallback.

Why this exists
---------------
A portfolio project that only runs when someone pays for an API key is a
portfolio project nobody runs. ``get_chat_model()`` resolves, in order:

    explicit setting  ->  first provider whose API key is present  ->  RuleBasedChatModel

``RuleBasedChatModel`` is a real ``BaseChatModel`` implementation that supports
``bind_tools`` and emits genuine ``tool_calls``, so the *same* LangChain agent
graph executes with or without an LLM. It routes on keywords instead of
reasoning: worse answers, identical plumbing, zero cost, fully deterministic —
which also makes it the model the CI test-suite runs against.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Iterable, Sequence

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool

from hwval.config import available_llm_keys, get_settings

log = logging.getLogger(__name__)

DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-5",
    "openai": "gpt-4o-mini",
    "groq": "llama-3.3-70b-versatile",
    "google": "gemini-2.0-flash",
    "ollama": "llama3.2",
}

# tool name -> regexes that select it, most specific first
ROUTING_RULES: list[tuple[str, str]] = [
    ("generate_test_plan", r"\btest[- ]?plan\b|\bwrite a plan\b|\btest cases?\b"),
    ("run_db_maintenance", r"\bmaintenance\b|\bvacuum\b|\bbloat\b|\bindex(es)?\b|\bhousekeep"),
    ("check_db_integrity", r"\bintegrity\b|\bconsistenc|\borphan"),
    ("detect_anomalies", r"\banomal|\boutlier|\bfailure mode|\bpredict|\bdrift\b|\bsuspicious"),
    ("build_report", r"\breport\b|\bsummar(y|ise|ize) the (validation|campaign)"),
    ("create_plot", r"\bplot\b|\bchart\b|\bdiagram\b|\bfigure\b|\bgraph\b|\bvisuali"),
    ("get_yield_summary", r"\byield\b|\bpass rate\b|\bcpk\b|\bhow many (runs|duts)"),
    ("describe_schema", r"\bschema\b|\btables?\b|\bcolumns?\b"),
    ("query_measurements", r".*"),  # catch-all
]


# --------------------------------------------------------------------------
# offline model
# --------------------------------------------------------------------------
class RuleBasedChatModel(BaseChatModel):
    """Deterministic stand-in for an LLM.

    It implements exactly the surface the agent loop needs: ``bind_tools`` and a
    ``_generate`` that either emits one tool call (first turn) or a final answer
    that renders the tool output (after a ``ToolMessage``).
    """

    bound_tools: list[Any] = []
    max_preview_chars: int = 4000

    @property
    def _llm_type(self) -> str:
        return "rule-based-offline"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> "RuleBasedChatModel":
        clone = self.__class__(bound_tools=list(tools), max_preview_chars=self.max_preview_chars)
        return clone

    # -- helpers ---------------------------------------------------------
    def _tool_names(self) -> set[str]:
        names = set()
        for t in self.bound_tools:
            if isinstance(t, BaseTool):
                names.add(t.name)
            elif isinstance(t, dict):
                names.add(t.get("name", ""))
            else:
                names.add(getattr(t, "__name__", ""))
        return {n for n in names if n}

    @staticmethod
    def _last_human(messages: Iterable[BaseMessage]) -> str:
        text = ""
        for m in messages:
            if isinstance(m, HumanMessage):
                text = m.content if isinstance(m.content, str) else str(m.content)
        return text

    def _route(self, question: str) -> tuple[str, dict]:
        available = self._tool_names()
        q = question.lower()
        for name, pattern in ROUTING_RULES:
            if name in available and re.search(pattern, q):
                return name, self._extract_args(name, question)
        # nothing matched a bound tool: pick any tool so the graph still runs
        fallback = sorted(available)[0] if available else ""
        return fallback, self._extract_args(fallback, question)

    @staticmethod
    def _extract_args(tool_name: str, question: str) -> dict:
        q = question.lower()
        run_id = re.search(r"\brun[ _#]?(\d+)", q)
        param = re.search(
            r"\b(vdd_core_v|vdd_io_v|icc_ma|tj_c|clk_mhz|jitter_ps|leak_ua|voh_v)\b", q
        )
        if tool_name == "create_plot":
            args: dict[str, Any] = {"kind": "timeseries" if run_id else "corner_boxplot"}
            if run_id:
                args["run_id"] = int(run_id.group(1))
            if param:
                args["param_name"] = param.group(1).upper()
            return args
        if tool_name == "detect_anomalies":
            return {"run_id": int(run_id.group(1))} if run_id else {"top_n": 10}
        if tool_name == "build_report":
            return {"fmt": "md"}
        if tool_name == "generate_test_plan":
            m = re.search(r"for (?:the )?([A-Za-z0-9._-]+)", question)
            return {
                "product": m.group(1) if m else "S32K344",
                "requirements": question,
            }
        if tool_name == "run_db_maintenance":
            return {"dry_run": True}
        if tool_name == "query_measurements":
            return {"question": question}
        return {}

    # -- BaseChatModel API ------------------------------------------------
    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        tool_outputs = [m for m in messages if isinstance(m, ToolMessage)]
        if tool_outputs:
            body = "\n\n".join(
                f"### {m.name or 'tool'}\n{str(m.content)[: self.max_preview_chars]}"
                for m in tool_outputs
            )
            answer = (
                "Offline planner (no LLM key configured) — results from the tools "
                f"that were executed:\n\n{body}"
            )
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content=answer))])

        question = self._last_human(messages)
        name, args = self._route(question)
        if not name:
            return ChatResult(
                generations=[
                    ChatGeneration(message=AIMessage(content="No tools are bound to this agent."))
                ]
            )
        msg = AIMessage(
            content="",
            tool_calls=[{"name": name, "args": args, "id": f"call_{abs(hash(question)) % 10**8}"}],
        )
        return ChatResult(generations=[ChatGeneration(message=msg)])


# --------------------------------------------------------------------------
# factory
# --------------------------------------------------------------------------
def resolve_provider() -> str:
    s = get_settings()
    if s.llm_provider and s.llm_provider != "auto":
        return s.llm_provider
    keys = available_llm_keys()
    for provider in ("anthropic", "openai", "groq", "google", "ollama"):
        if keys.get(provider):
            return provider
    return "rulebased"


def get_chat_model(provider: str | None = None, **overrides: Any) -> BaseChatModel:
    s = get_settings()
    provider = provider or resolve_provider()
    model_name = overrides.pop("model", None) or s.llm_model or DEFAULT_MODELS.get(provider, "")
    common = {
        "temperature": overrides.pop("temperature", s.llm_temperature),
        "max_tokens": overrides.pop("max_tokens", s.llm_max_tokens),
    }

    try:
        if provider == "anthropic":
            from langchain_anthropic import ChatAnthropic

            return ChatAnthropic(model=model_name, **common, **overrides)
        if provider == "openai":
            from langchain_openai import ChatOpenAI

            return ChatOpenAI(model=model_name, **common, **overrides)
        if provider == "groq":
            from langchain_groq import ChatGroq

            return ChatGroq(model=model_name, **common, **overrides)
        if provider == "google":
            from langchain_google_genai import ChatGoogleGenerativeAI

            return ChatGoogleGenerativeAI(model=model_name, temperature=common["temperature"])
        if provider == "ollama":
            from langchain_ollama import ChatOllama

            return ChatOllama(model=model_name, temperature=common["temperature"])
    except ImportError as exc:
        log.warning("provider %s unavailable (%s) — falling back to offline planner", provider, exc)
    except Exception as exc:  # pragma: no cover - credential/runtime issues
        log.warning("provider %s failed to initialise (%s) — offline planner", provider, exc)

    return RuleBasedChatModel()


def llm_status() -> dict:
    provider = resolve_provider()
    return {
        "provider": provider,
        "model": get_settings().llm_model or DEFAULT_MODELS.get(provider, "rule-based"),
        "keys_present": {k: v for k, v in available_llm_keys().items() if v},
        "offline_fallback": provider == "rulebased",
    }


def to_json(obj: Any, limit: int = 6000) -> str:
    """Compact JSON serialisation used by every tool's return value.

    Tools return strings, not objects: the model reads them, so they must be
    stable, compact and truncated — a 40 kB tool result is how agents blow their
    context window.
    """
    txt = json.dumps(obj, default=str, ensure_ascii=False, indent=2)
    if len(txt) > limit:
        txt = txt[:limit] + f"\n... [truncated, {len(txt)} chars total]"
    return txt

import asyncio
import json
import os
import re
from datetime import date, timedelta
from typing import Any, Dict, Optional, TypedDict

from icecream import ic

from langchain_core.prompts import ChatPromptTemplate
from langchain_litellm import ChatLiteLLM
from langgraph.graph import END, StateGraph

from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.types import ReadResourceResult

from shared.database import get_checkpointer, get_user_profile
from shared.security import decrypt_secret

MCP_URL = os.environ.get("GARMIN_MCP_URL", "http://garmin-mcp:8000/sse")
LITELLM_API_BASE = os.environ.get("LITELLM_API_BASE")
LITELLM_API_KEY = os.environ.get("LITELLM_API_KEY")
LITELLM_MODEL = os.environ.get("LITELLM_MODEL")

DEFAULT_REPORT_DAYS = 7
MAX_REPORT_DAYS = 90


class CoachState(TypedDict, total=False):
    user_id: str
    input: str
    profile: Dict[str, Any]
    garmin_auth: Dict[str, str]
    coach_prompt: str
    weekly_report: Dict[str, Any]
    report_days: int
    days_ago: int
    response: str
    error: str


def parse_report_command(user_input: str) -> tuple[str, Optional[int], Optional[int], bool]:
    stripped = user_input.strip()
    match = re.match(
        r"^/report(?:\s+(\d+))?(?:\s+(\d+))?\s*(.*)$",
        stripped,
        re.IGNORECASE,
    )
    if not match:
        return user_input, None, None, False

    days = int(match.group(1)) if match.group(1) else DEFAULT_REPORT_DAYS
    days_ago = int(match.group(2)) if match.group(2) else 0
    prompt_input = match.group(3).strip()
    return prompt_input, days, days_ago, True


def _sanitize_profile(profile: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "goals": profile.get("goals") or "",
        "injuries": profile.get("injuries") or "",
    }


def _normalize_mcp_result(result: Any) -> Dict[str, Any]:
    if isinstance(result, dict):
        return result
    if hasattr(result, "content"):
        return {"content": result.content}
    if hasattr(result, "contents"):
        try:
            contents = []
            for item in result.contents:
                if hasattr(item, "model_dump"):
                    contents.append(item.model_dump())
                else:
                    contents.append(item)
            return {"contents": contents}
        except Exception:
            return {"raw": str(result)}
    return {"raw": str(result)}


def _parse_resource_text(result: ReadResourceResult) -> Any:
    if not result.contents:
        return {}
    text = result.contents[0].text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _resolve_report_days(user_input: str) -> int:
    lowered = user_input.lower()

    explicit = re.search(r"(?:last|past)\s+(\d+)\s+days?", lowered)
    if explicit:
        return max(1, min(int(explicit.group(1)), MAX_REPORT_DAYS))

    if "last month" in lowered or "past month" in lowered:
        return 30

    if "last week" in lowered or "past week" in lowered:
        return 7

    return DEFAULT_REPORT_DAYS


def _build_llm() -> ChatLiteLLM:
    if not LITELLM_API_BASE:
        raise RuntimeError("LITELLM_API_BASE is required for LiteLLM requests")
    if not LITELLM_MODEL:
        raise RuntimeError("LITELLM_MODEL is required for LiteLLM requests")

    llm_kwargs = {
        "model": LITELLM_MODEL,
        "temperature": 0.2,
        "api_base": LITELLM_API_BASE,
    }
    if LITELLM_API_KEY:
        llm_kwargs["api_key"] = LITELLM_API_KEY
    return ChatLiteLLM(**llm_kwargs)


async def load_profile(state: CoachState) -> Dict[str, Any]:
    profile = get_user_profile(state["user_id"]) or {}
    garmin_username = profile.get("garmin_username") or ""
    garmin_password = ""
    enc_password = profile.get("garmin_password_enc")
    if enc_password:
        try:
            garmin_password = decrypt_secret(enc_password)
        except Exception:
            garmin_password = ""

    report_days = state.get("report_days", _resolve_report_days(state["input"]))
    return {
        "profile": _sanitize_profile(profile),
        "garmin_auth": {"username": garmin_username, "password": garmin_password},
        "report_days": report_days,
        "days_ago": state.get("days_ago", 0),
    }


async def fetch_mcp_resources(state: CoachState) -> Dict[str, Any]:
    report_days = state.get("report_days", DEFAULT_REPORT_DAYS)
    days_ago = state.get("days_ago", 0)

    async with sse_client(MCP_URL) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            prompt_result: ReadResourceResult = await session.read_resource(
                "garmin://coach-prompt"
            )
            prompt = _parse_resource_text(prompt_result)
            if isinstance(prompt, dict) and prompt.get("error"):
                return {"error": prompt["error"]}

            result = await session.call_tool(
                "get_report",
                arguments={"days": report_days, "days_ago": days_ago},
            )
            if result.isError:
                return {
                    "error": result.content[0].text
                    if result.content
                    else "Garmin report failed"
                }

            payload: Dict[str, Any] | None = None
            for block in result.content:
                if hasattr(block, "text") and block.text:
                    payload = json.loads(block.text)
                    break

            ic("Raw MCP result:", payload, "Type:", type(payload))
            if payload is None:
                return {"error": "No weekly report returned from garmin-mcp"}
            if isinstance(payload, dict) and payload.get("error"):
                return {"error": payload["error"]}

    return {
        "coach_prompt": prompt if isinstance(prompt, str) else str(prompt),
        "weekly_report": _normalize_mcp_result(payload),
    }


async def generate_response(state: CoachState) -> Dict[str, Any]:
    ic("Generating response with state:", state)
    if state.get("error"):
        return {"response": _friendly_error(state["error"])}

    llm = _build_llm()
    report_days = state.get("report_days", DEFAULT_REPORT_DAYS)
    days_ago = state.get("days_ago", 0)
    window_label = (
        f"last {report_days} day(s)"
        if days_ago == 0
        else f"{report_days} day(s) ending {days_ago} day(s) ago"
    )
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "{coach_prompt}\n\n"
                "Athlete profile:\n{profile}\n\n"
                "Garmin review data ({window_label}):\n{weekly_report}\n\n"
                "Today's date: {date}",
            ),
            ("human", "{input}"),
        ]
    )
    messages = prompt.format_messages(
        coach_prompt=state.get("coach_prompt", ""),
        profile=json.dumps(state.get("profile", {}), indent=2),
        window_label=window_label,
        weekly_report=json.dumps(state.get("weekly_report", {}), indent=2),
        date=date.today().isoformat(),
        input=state["input"],
    )
    response = await llm.ainvoke(messages)
    return {"response": response.content}


def _friendly_error(error: str) -> str:
    lowered = error.lower()
    if "missing garmin credentials" in lowered:
        return "Garmin service unavailable: missing credentials. Set GARMIN_EMAIL and GARMIN_PASSWORD."
    if "authentication" in lowered or "login" in lowered:
        return "Garmin service unavailable: authentication failed. Check your Garmin credentials."
    if "not initialized" in lowered or "connection" in lowered:
        return "Garmin service unavailable. Please try again later."
    return f"Garmin service unavailable: {error}"


def build_graph(checkpointer):
    graph = StateGraph(CoachState)
    graph.add_node("load_profile", load_profile)
    graph.add_node("fetch_mcp_resources", fetch_mcp_resources)
    graph.add_node("generate_response", generate_response)

    graph.set_entry_point("load_profile")
    graph.add_edge("load_profile", "fetch_mcp_resources")
    graph.add_edge("fetch_mcp_resources", "generate_response")
    graph.add_edge("generate_response", END)

    return graph.compile(checkpointer=checkpointer)


_GRAPH = None
_GRAPH_LOCK = asyncio.Lock()


async def get_graph():
    global _GRAPH
    if _GRAPH is not None:
        return _GRAPH

    async with _GRAPH_LOCK:
        if _GRAPH is not None:
            return _GRAPH
        checkpointer = await get_checkpointer()
        _GRAPH = build_graph(checkpointer)
        return _GRAPH


async def run_agent(
    user_input: str,
    user_id: str,
    thread_id: Optional[str] = None,
    report_days: int = DEFAULT_REPORT_DAYS,
    days_ago: int = 0,
) -> str:
    prompt_input, parsed_days, parsed_days_ago, used_report_command = parse_report_command(
        user_input
    )
    if used_report_command:
        report_days = parsed_days if parsed_days is not None else report_days
        days_ago = parsed_days_ago if parsed_days_ago is not None else days_ago
    else:
        report_days = _resolve_report_days(user_input)

    if used_report_command and not prompt_input:
        window_end = date.today() - timedelta(days=days_ago)
        window_start = window_end - timedelta(days=report_days - 1)
        return (
            f"Report window set to {report_days} day(s) ending "
            f"{window_end.isoformat()} ({window_start.isoformat()} to {window_end.isoformat()}). "
            "Ask your next question to get coaching based on that period."
        )

    config = {"configurable": {"thread_id": thread_id or user_id}}
    graph = await get_graph()
    result = await graph.ainvoke(
        {
            "input": prompt_input,
            "user_id": user_id,
            "report_days": report_days,
            "days_ago": days_ago,
        },
        config=config,
    )
    return result["response"]

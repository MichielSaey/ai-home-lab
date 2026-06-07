import asyncio
import json
import os
from datetime import date
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

PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are a Garmin running coach. Use the profile and weekly report to provide clear, safe guidance.\n"
            # "Profile:\n{profile}\n\nWeekly report:\n{weekly_report}\n\nDate: {date}"
            "Weekly report:\n{weekly_report}\n\nDate: {date}",
        ),
        ("human", "{input}"),
    ]
)


class CoachState(TypedDict):
    user_id: str
    input: str
    profile: Dict[str, Any]
    garmin_auth: Dict[str, str]
    weekly_report: Dict[str, Any]
    response: str


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


def _build_llm() -> ChatLiteLLM:
    if not LITELLM_API_BASE:
        raise RuntimeError("LITELLM_API_BASE is required for LiteLLM requests")
    if not LITELLM_MODEL:
        raise RuntimeError("LITELLM_MODEL is required for LiteLLM requests")

    llm_kwargs = {
        "model": LITELLM_MODEL,
        "temperature": 0.2,
        "api_base": LITELLM_API_BASE,
        # "max_tokens": 2048,
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

    return {
        "profile": _sanitize_profile(profile),
        "garmin_auth": {"username": garmin_username, "password": garmin_password},
    }


async def fetch_weekly_report(state: CoachState) -> Dict[str, Any]:
    async with sse_client(MCP_URL) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result: ReadResourceResult = await session.read_resource("garmin://weekly-report")
            result = json.loads(result.contents[0].text)
            ic("Raw MCP result:", result, "Type:", type(result))
            if result.get("error"):
                return {"error": result["error"]}
    return {"weekly_report": _normalize_mcp_result(result)}


async def generate_response(state: CoachState) -> Dict[str, Any]:
    ic("Generating response with state:", state)
    if state.get("error"):
        return {"response": str(state["error"])}
    
    llm = _build_llm()
    messages = PROMPT.format_messages(
        profile=json.dumps(state.get("profile", {}), indent=2),
        weekly_report=json.dumps(state.get("weekly_report", {}), indent=2),
        date=date.today().isoformat(),
        input=state["input"],
    )
    response = await llm.ainvoke(messages)
    return {"response": response.content}


def build_graph(checkpointer):
    graph = StateGraph(CoachState)
    # graph.add_node("load_profile", load_profile)
    graph.add_node("get_weekly_report", fetch_weekly_report)
    graph.add_node("generate_response", generate_response)

    # graph.set_entry_point("load_profile")
    graph.set_entry_point("get_weekly_report")
    # graph.add_edge("load_profile", "get_weekly_report")
    graph.add_edge("get_weekly_report", "generate_response")
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



async def run_agent(user_input: str, user_id: str, thread_id: Optional[str] = None) -> str:
    config = {"configurable": {"thread_id": thread_id or user_id}}
    graph = await get_graph()
    result = await graph.ainvoke({"input": user_input, "user_id": user_id}, config=config)
    return result["response"]

"""HUDA Assistant (spec FR-22): chat answered from tool results only.

Conversations live in memory (implementation-plan D11): 30-min TTL, last 10 turns.
"""

import time
import uuid

from ..auth import User
from ..config import get_settings
from . import tools
from .gemini_client import GeminiUnavailable, generate

MAX_TOOL_ROUNDS = 4
TTL_S = 1800
MAX_TURNS = 10
UNAVAILABLE = ("Sorry — I can't reach the weather data right now, so I won't guess. "
               "Please check the Live map or try again in a few minutes.")

SYSTEM = """You are the HUDA Assistant for Sime Darby Property townships in Peninsular Malaysia.
Answer questions about heavy rain and flood-rain risk using ONLY the results of your tools.
- Always call a tool before answering a factual question. If tools return errors or no data, say the data is unavailable.
- Never invent numbers, never predict beyond what the tools return, and never state a risk level a tool did not return.
- Risk levels (GREEN/AMBER/RED) come from HUDA's rules and model; you cannot change them.
- Give ETAs in minutes. Keep answers short (2–4 sentences), plain language, and end with one practical suggestion when risk is AMBER or RED.
- Reply in the user's language (English or Bahasa Melayu).
- draft_warning creates a warning that waits for admin approval; say so clearly if you use it."""

_conversations: dict[str, tuple[float, list]] = {}


def _history(conversation_id: str | None, user: User) -> tuple[str, list]:
    now = time.monotonic()
    for cid in [c for c, (ts, _) in _conversations.items() if now - ts > TTL_S]:
        _conversations.pop(cid, None)
    key = f"{user.id}:{conversation_id}" if conversation_id else None
    if key and key in _conversations:
        return conversation_id, _conversations[key][1]
    return uuid.uuid4().hex[:12], []


def _trim(contents: list) -> list:
    """Keep the last MAX_TURNS user questions, cutting only at a user text turn
    (never between a function call and its response)."""
    starts = [i for i, c in enumerate(contents)
              if c.role == "user" and any(getattr(p, "text", None) for p in c.parts or [])]
    return contents[starts[-MAX_TURNS]:] if len(starts) > MAX_TURNS else contents


def chat(user: User, message: str, conversation_id: str | None = None) -> dict:
    from google.genai import types

    cid, history = _history(conversation_id, user)
    contents = list(history) + [types.Content(role="user", parts=[types.Part.from_text(text=message)])]
    trace, pending_id = [], None
    model = get_settings().gemini_model
    try:
        for _ in range(MAX_TOOL_ROUNDS + 1):
            response = generate(contents, system=SYSTEM, tools=tools.gemini_tools(user),
                                agent="assistant", cache=False)
            calls = response.function_calls or []
            if not calls:
                reply = (response.text or "").strip() or UNAVAILABLE
                break
            contents.append(response.candidates[0].content)
            parts = []
            for fc in calls:
                args = dict(fc.args or {})
                result = tools.call(user, fc.name, args)
                trace.append({"name": fc.name, "args": args})
                if fc.name == "draft_warning" and "pending_warning_id" in result:
                    pending_id = result["pending_warning_id"]
                parts.append(types.Part.from_function_response(name=fc.name, response={"result": result}))
            contents.append(types.Content(role="user", parts=parts))
        else:
            reply = UNAVAILABLE
    except GeminiUnavailable:
        reply = UNAVAILABLE

    contents.append(types.Content(role="model", parts=[types.Part.from_text(text=reply)]))
    _conversations[f"{user.id}:{cid}"] = (time.monotonic(), _trim(contents))
    out = {"conversation_id": cid, "reply": reply, "tool_calls": trace, "model": model}
    if pending_id:
        out["pending_warning_id"] = pending_id
    return out

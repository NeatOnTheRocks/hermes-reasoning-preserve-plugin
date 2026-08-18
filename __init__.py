"""reasoning-preserve — re-inject reasoning_content into outgoing API requests.

Background
==========
llama.cpp (and any OpenAI-compatible backend whose chat template reads
``message.reasoning_content``) needs the assistant's reasoning field replayed
in subsequent turns for multi-turn reasoning continuity. Hermes' send path
runs ``apply_reasoning_content_policy`` for every assistant turn while building
``api_messages``. For providers that do NOT enforce the thinking echo-back
(DeepSeek/Kimi/MiMo), the policy strips ``reasoning_content`` from the outgoing
copy — the field is gone from the wire before the backend ever sees it. The
original ``msg`` in the live history still carries it.

This plugin registers a ``pre_api_request`` hook. That hook fires synchronously
right before ``client.chat.completions.create(**api_kwargs)`` and hands the
callback:

* ``request_messages`` — the outgoing message list whose inner dicts are the
  ``api_msg`` clones actually sent to the wire (identity chain:
  ``api_messages`` → ``build_api_kwargs`` → ``apply_llm_request_middleware``
  → hook ``request_messages``; every link shares the inner dicts). Mutating an
  inner dict here mutates the outgoing request bytes.
* ``conversation_history`` — ``list(messages)``: the live history, where each
  assistant turn still carries its ``reasoning_content``.

The callback pairs each assistant message in ``request_messages`` with its
source in ``conversation_history`` (by tool_call IDs where present, falling
back to content) and re-injects ``reasoning_content`` if the source has it.

Self-scoping
============
The callback checks ``provider == "custom"`` first. It is inert for every
provider that legitimately rejects ``reasoning_content`` (strict
OpenAI-compatible gateways: Mistral, Cerebras, Groq, SambaNova, etc.).
"""
from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger("reasoning-preserve")

# Providers whose chat template reads ``reasoning_content`` from input history
# and replays it for multi-turn reasoning continuity. ``custom`` is the
# Hermes provider tag for user-defined OpenAI-compatible endpoints (e.g.
# llama.cpp at http://localhost:8080/v1).
_PRESERVE_PROVIDERS = frozenset({"custom"})


def _pair_key(msg: Dict[str, Any]) -> tuple:
    """Return a join key identifying a message across the two lists.

    Assistant messages with tool calls carry unique ``id`` fields — use those
    as the primary join key. Text-only turns fall back to a content hash.
    """
    tool_calls = msg.get("tool_calls")
    if isinstance(tool_calls, list) and tool_calls:
        ids = []
        for tc in tool_calls:
            if isinstance(tc, dict):
                tc_id = tc.get("id")
                if isinstance(tc_id, str) and tc_id:
                    ids.append(tc_id)
        if ids:
            return ("tool", tuple(ids))
    content = msg.get("content")
    if isinstance(content, str):
        return ("text", content)
    return ("none",)


def _source_by_key(conversation_history: list) -> Dict[tuple, Dict[str, Any]]:
    """Index the live history by join key for O(1) lookup."""
    index: Dict[tuple, Dict[str, Any]] = {}
    for msg in conversation_history:
        if not isinstance(msg, dict):
            continue
        if msg.get("role") != "assistant":
            continue
        key = _pair_key(msg)
        # First occurrence wins; later duplicates are ignored. This matches
        # the build loop's behaviour of appending one api_msg per history msg.
        if key not in index:
            index[key] = msg
    return index


def _on_pre_api_request(**kwargs: Any) -> None:
    """Re-inject ``reasoning_content`` into outgoing assistant turns.

    Runs on every API request. The mutation is the effect — the callback
    returns ``None`` (observer shape) because the inner dicts of
    ``request_messages`` are the same objects passed to ``create()``.
    """
    provider = kwargs.get("provider")
    if provider not in _PRESERVE_PROVIDERS:
        return None

    request_messages = kwargs.get("request_messages")
    if not isinstance(request_messages, list):
        return None

    conversation_history = kwargs.get("conversation_history")
    if not isinstance(conversation_history, list):
        # No source history — nothing to re-inject from. Fail open.
        return None

    source_by_key = _source_by_key(conversation_history)
    if not source_by_key:
        return None

    for api_msg in request_messages:
        if not isinstance(api_msg, dict):
            continue
        if api_msg.get("role") != "assistant":
            continue
        key = _pair_key(api_msg)
        if key[0] == "none":
            continue
        source = source_by_key.get(key)
        if source is None or source is api_msg:
            continue
        reasoning = source.get("reasoning_content")
        if isinstance(reasoning, str) and reasoning:
            if not api_msg.get("reasoning_content"):
                api_msg["reasoning_content"] = reasoning


def register(ctx) -> None:
    """Hermes plugin entry point."""
    ctx.register_hook("pre_api_request", _on_pre_api_request)

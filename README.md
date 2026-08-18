# reasoning-preserve

A Hermes Agent plugin that re-injects `reasoning_content` into outgoing API
requests for `custom` OpenAI-compatible providers whose chat template reads it. 
Inert for every other provider.

It fixes multi-turn reasoning continuity for local models: without it, the
model's own thinking from turn N never reaches turn N+1.

## Install

```bash
hermes plugins install NeatOnTheRocks/hermes-reasoning-preserve-plugin --enable
```

- Installs to `~/.hermes/plugins/reasoning-preserve/`. The directory name comes
  from the `name:` field in `plugin.yaml`, not the repo name.
- `--enable` adds it to `plugins.enabled` and skips the confirmation prompt.
  Without it the plugin installs disabled; activate it with
  `hermes plugins enable reasoning-preserve`.
- **Restart the gateway** for it to take effect — plugins are discovered once
  per process at startup; a running process does not pick up new plugins.

The whole repo root is the plugin package: `hermes plugins install` clones the
repo and moves the root into `~/.hermes/plugins/reasoning-preserve/`, so
`plugin.yaml`, `__init__.py`, and this README land together in the install
directory.

### Pin an exact commit

```bash
hermes plugins install NeatOnTheRocks/hermes-reasoning-preserve-plugin \
  --ref <40-char-commit-sha> --enable
```

`--ref` pins the install to one immutable revision and records it in
`~/.hermes/plugins/.install-metadata.json`, so later `hermes plugins update`
calls won't move the pin without an explicit `--ref`.

## Prerequisites

The plugin only does real work when your backend will actually *use* the field
it re-injects:

- Your `custom` provider (llama.cpp or another OpenAI-compatible endpoint) must
  use a **chat template that reads `message.reasoning_content`** for multi-turn
  reasoning continuity. If the template ignores the field, the re-injection is
  harmless but useless.
- **No Hermes config flag is required.** The `preserve_thinking:` and
  `passthrough_reasoning:` keys in the `custom_providers` block are not read by
  the current runtime — they are inert. This plugin *is* the fix; you do not
  need to set anything in `config.yaml` beyond enabling the plugin.

Self-scoping, fail-open:

- The callback checks `provider == "custom"` first, so it is **inert for strict
  OpenAI-compatible providers** (Mistral, Cerebras, Groq, SambaNova, plain
  OpenAI) that reject any `reasoning_content` key with HTTP 400/422.
- It skips any message that already carries `reasoning_content`, so if an
  upstream fix ever preserves the field, this plugin becomes a no-op.

## The problem

Hermes captures a model's `reasoning_content` into the message dict and
persists it to the session DB. But at send time the build loop runs
`apply_reasoning_content_policy(msg, api_msg, needs_thinking_pad)`
(`agent/message_sanitization.py`) for every assistant turn. The pad flag is
only `True` for providers that *require* the echo-back (DeepSeek / Kimi / MiMo
— `_REASONING_ECHO_RULES`). For a `custom` provider it is `False`, so the policy
does `api_msg.pop("reasoning_content", None)` — the field is gone from the wire
before llama.cpp ever sees it. Result: the model's own thinking from turn N
never reaches turn N+1, and multi-turn reasoning continuity breaks.

Repro: ask the model to generate two random 5-digit numbers and output only
their sum, then ask which two it added — it cannot answer.

## How it works

A `pre_api_request` plugin hook. It fires synchronously right before
`client.chat.completions.create(**api_kwargs)` and receives both:

- `request_messages` — the outgoing message list.
- `conversation_history` — the live history, where each assistant turn still
  carries its `reasoning_content`.

It is the only hook that sees both, which is why the plugin uses it. The
callback pairs each outgoing assistant message with its source in history (join
key: tool_call IDs where present, content otherwise) and re-injects
`reasoning_content` if the source has it. The mutation *is* the effect: the
inner dicts of `request_messages` are the same objects passed to `create()`
(identity chain: `api_messages` → `build_kwargs(messages=sanitized)` →
`apply_llm_request_middleware` → hook `request_messages`; each link shares the
inner dicts). The callback returns `None`.

## Why a plugin (not a config flag, not a source patch)

- Lives in `~/.hermes/plugins/` — untouched by `hermes update`, so the fix
  survives updates without re-applying it.
- No dependency on upstream capability flags or PRs landing in whatever repo
  your update pulls from.
- Self-scoped: the callback checks `provider == "custom"` first, so it is inert
  for strict providers (Mistral, Cerebras, Groq, SambaNova) that reject any
  `reasoning_content` key with HTTP 400/422, and for the echo-back families
  whose own policy owns the pad.
- If the upstream fix does land and the field is preserved, this plugin is
  harmless: its guard skips messages that already carry `reasoning_content`.

## Files

```
<repo root>  →  ~/.hermes/plugins/reasoning-preserve/
  plugin.yaml     # manifest: name, version, provides_hooks: [pre_api_request]
  __init__.py     # register(ctx) -> ctx.register_hook("pre_api_request", ...)
  README.md       # this file
  after-install.md  # rendered by `hermes plugins install` after install
```

## Verification

1. **Unit** — drive the registered callback with the exact hook payload shape;
   assert re-injection on tool-call turns (join by IDs) and text turns (join by
   content), and that non-assistant turns, strict providers, and echo-back
   providers are untouched.
2. **Real loader** — import Hermes' actual plugin manager in a fresh process,
   `discover_plugins(force=True)`, confirm `enabled=True` and
   `hooks_registered=['pre_api_request']`, then drive the real
   `invoke_hook("pre_api_request", ...)` dispatch and confirm the outgoing
   list is mutated.
3. **Live** — a real two-turn session against the local server in a fresh
   process (new chat after restarting Hermes, model pinned to the one you want
   — the custom provider defaults to HAL-Valence):
   - Turn 1: generate two random 5-digit numbers, output only their sum.
   - Turn 2: ask which two numbers were added.
   - Pass criterion: the model names the two numbers.
   - Optional wire proof: set `HERMES_DUMP_REQUESTS=1` in the environment before
     starting Hermes; each request is dumped to
     `~/.hermes/sessions/request_dump_<session>_<timestamp>.json` (after the
     hook runs, before the wire). Inspect the second request's
     `request.body.messages` — assistant turns should carry `reasoning_content`.

## Maintenance

- **Update**: `hermes plugins update reasoning-preserve` pulls the latest from
  the recorded source; the plugin reloads on the next session.
- **Remove**: `hermes plugins remove reasoning-preserve` (or delete the
  directory and drop it from `plugins.enabled`).
- **Failure mode**: if Hermes refactors the send path (hook kwargs renamed,
  shallow copy replaced by deep copy, `conversation_history` no longer passed),
  the plugin fails silently and the two-number bug returns. The hook dispatch is
  wrapped in try/except per callback, so a broken plugin cannot crash the agent
  loop — it just logs a warning.

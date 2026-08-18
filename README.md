# Reasoning-Preserve

Keep a local llama.cpp model's thinking across turns.

When Hermes trims the context window to fit the model, it strips the
`reasoning_content` field that llama.cpp returns. The model's scratchpad is
wiped. The next turn starts with the model having no memory of what it was
just working through. For reasoning models, that means re-deriving from
scratch every turn instead of building on what it already worked out.

This plugin puts the scratchpad back.

## How it works

Think of `reasoning_content` as a notebook the model writes in while it is
thinking. Hermes' context trimmer wipes that notebook between turns. The
plugin copies the notebook's contents into the outgoing request, so the model
picks up where it left off.

Concretely, the plugin registers a `pre_api_request` hook. Before each request
leaves Hermes, it checks two things:

1. Is the backend a `custom` provider? If not, the hook does nothing. Strict
   OpenAI-style servers reject unknown fields, and this plugin will not fight
   that fight.
2. Is there a `reasoning_content` field in the payload? If not, the hook does
   nothing. There is nothing to put back.

If both are yes, the hook attaches the field to the last message in the
request. The chat template on the llama.cpp side reads it and feeds it back to
the model as context.

Before (what Hermes sends without the plugin):

```json
{"messages": [{"role": "user", "content": "what's 5 + 3?"}]}
```

After (what llama.cpp receives with the plugin):

```json
{"messages": [
  {"role": "user", "content": "what's 5 + 3?"},
  {"role": "assistant",
   "reasoning_content": "5 + 3... that's 8",
   "content": "8"}
]}
```

The model sees its own prior reasoning. It continues from there.

## Install

```
hermes plugins install NeatOnTheRocks/hermes-reasoning-preserve-plugin --enable
```

That is the whole install. No config file to edit. No flag to set. The plugin
is self-scoping: it checks the backend type before acting, so it never touches
a strict server and never injects a field a backend would reject.

One prerequisite: your llama.cpp chat template must read
`message.reasoning_content`. If it does not, the plugin is inert. It still
re-injects the field, but the template ignores it, so nothing changes on the
model's side. Most Qwen-family templates already read this field. If you are
running a custom template, check that it has a `message.reasoning_content`
accessor before expecting the plugin to do anything.

No `config.yaml` changes are needed. (`preserve_thinking` and
`passthrough_reasoning` are dead keys in the current runtime. They are not
read by the loader. They do nothing.)

## Verify

1. Run `hermes plugins show reasoning-preserve`. It should report
   `Status: enabled` and `Source: git`.
2. Start a session against your llama.cpp backend. Send something that
   triggers reasoning. A small math problem works. Check the llama.cpp server
   log: the outgoing request should carry a `reasoning_content` field on the
   assistant message. If it does, the plugin is working.

## Managing it

Every action is a one-liner. No config edits, no file surgery.

| Task              | Command                                        |
| ----------------- | ---------------------------------------------- |
| Disable           | `hermes plugins disable reasoning-preserve`    |
| Re-enable         | `hermes plugins enable reasoning-preserve`     |
| Update to latest  | `hermes plugins update reasoning-preserve`     |
| Remove entirely   | `hermes plugins remove reasoning-preserve`     |

After any of these, restart the session. Plugins load once per process at
startup, so a new or changed plugin takes effect on the next session.

## Troubleshooting

- **Install fails with an auth error.** The repo is private. Make sure
  `GITHUB_TOKEN` in `~/.hermes/.env` has `repo` scope, or make the repo
  public.
- **Plugin is enabled but the model still forgets its reasoning.** Check that
  your chat template actually reads `message.reasoning_content`. If it does
  not, the plugin is doing its job but the template is dropping the field.
- **`plugins show` says disabled.** Run `hermes plugins enable
  reasoning-preserve` and restart the session.
- **A strict OpenAI backend is rejecting requests.** This plugin never fires
  for strict providers. If you are seeing rejections on a strict backend, the
  cause is elsewhere.

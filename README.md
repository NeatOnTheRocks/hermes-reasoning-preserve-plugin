# Reasoning-Preserve

Keep a local model's thinking across turns!

While Hermes supports retaining thinking content for a limited number of providers (Deepseek, Kimi, MiMo), this feature has yet to come to local/custom providers and the wider model ecosystem.
Documented here: https://github.com/NousResearch/hermes-agent/issues/56004

### The Problem

When Hermes trims the context window to fit a local model, it strips the
`reasoning_content` field that the local inference backend returns. This means that
each turn, Hermes remembers what it *said* to you in the previous turns, but not what it
*thought* about. Each turn may as well be a new Agent who read the message history.

Regardless of whether it gives a correct or incorrect answer, your agent is unable to tell you
how it arrived at its conclusion to the problem *you just gave it*.

### The Solution!

This plugin reinjects the thinking content of the previous turn into the next, so that your Hermes sessions
come closer to an ongoing conversation with a real agent, and less of playing telephone with someone new every single message.

## How It Works:

Think of `reasoning_content` as a notebook the model writes in while it is
thinking. Hermes' context trimmer wipes that notebook between turns. The
plugin copies the notebook's contents into the outgoing request, so the model
picks up where it left off.

Concretely, the plugin registers a `pre_api_request` hook. Before each request
leaves Hermes, it checks two things:

1. Is the backend a `custom` provider? If not, the hook does nothing. Strict
   OpenAI-style servers reject unknown fields anyway.
2. Is there a `reasoning_content` field in the payload? If not, the hook does
   nothing. There is nothing to put back.

If both are yes, the hook attaches the field to the last message in the
request. The chat template on the inference server's side reads it and feeds it back to
the model as context.

### Before:

> User: Generate two random 4-digit numbers, then output *only* the result
>
> Hermes: \<think\> *Number 1: 6,234. Number 2: 8,917. 6234 + 8917 = 15151* \</think\> \
> Hermes: **15151**
>
> User: Now tell me what two numbers you added to get 15151.
>
> Hermes: \<think\> *The numbers I added were 8,000 + 7,515. Wait, I actually can't remember what the numbers were. Wait, I never actually generated two numbers. I should be honest and tell the user that I just made a number up...*

The model has no idea what two numbers it added together, even if its thinking block is visible to you in Hermes' UI.
If you ask Hermes in the next turn what the two numbers were, it will either hallucinate, tell you it can't remember, or conclude that it never generated two numbers in the first place.

What Hermes sends without the plugin:

```json
{"messages": [
  {"role": "user", "content": "Generate two random 4-digit numbers, then output *only* the result"},
  {"role": "assistant",
   "content": "15151"}
]}
```

### After: 

> User: Generate two random 4-digit numbers, then output *only* the result
>
> Hermes: \<think\> *Number 1: 6,234. Number 2: 8,917. 6234 + 8917 = 15151* \</think\> \
> Hermes: **15151**
>
> User: Now tell me what two numbers you added to get 15151.
>
> Hermes: \<think\> *I can see that I added 6,234 and 8,917. \</think\> \
> Hermes: I added 6,234 and 8,917. **6,234 + 8,917 = 15151**.

The model sees its own prior reasoning. It continues from there.

What llama.cpp receives with the plugin:

```json
{"messages": [
  {"role": "user", "content": "generate two random 4-digit numbers, then output *only* the result"},
  {"role": "assistant",
   "reasoning_content": "Number 1: 6,234. Number 2: 8,917. 6234 + 8917 = 15151",
   "content": "15151"}
]}
```

## Install

```
hermes plugins install NeatOnTheRocks/hermes-reasoning-preserve-plugin --enable
```

That is the whole install. No config file to edit or flag to set or any of that. The plugin
is self-scoping: it checks the backend type before acting, so it never touches
a strict server and never injects a field a backend would reject.

Two prerequisites: you must be using a custom provider, and your model's chat template must read
`message.reasoning_content`. If it does not, the plugin is inert. It still
re-injects the field, but the template ignores it, so nothing changes on the
model's side. **Most Qwen-family templates already read this field**. If you are
running a custom template, check that it has a `message.reasoning_content`
accessor before expecting the plugin to do anything.

## Verify

1. Run `hermes plugins show reasoning-preserve`. It should report
   `Status: enabled` and `Source: git`.
2. Start a new session. Instruct Hermes to invent a simple math problem, but output only the *answer*. Then, on the next turn, ask what the question was. If the plugin is working, the agent will tell you the question that it previously thought of; if it's not working, it won't be able to remember.
   You can also check the llama.cpp server log: the outgoing request should carry a `reasoning_content` field on the
   assistant message. If it does, the plugin is working.

## Managing the Plugin

| Task              | Command                                        |
| ----------------- | ---------------------------------------------- |
| Disable           | `hermes plugins disable reasoning-preserve`    |
| Re-enable         | `hermes plugins enable reasoning-preserve`     |
| Update to latest  | `hermes plugins update reasoning-preserve`     |
| Remove entirely   | `hermes plugins remove reasoning-preserve`     |

After any of these, restart the session. Plugins load once per process at
startup, so a new or changed plugin takes effect on the next session.

## Troubleshooting

- **Plugin is enabled but the model still forgets its reasoning:** Check that "reasoning-preserve" (or the equivalent flag for your inference server of choice) is enabled, you're using a custom provider, and
  your chat template actually reads `message.reasoning_content`. If it does
  not, the plugin is doing its job but the template is dropping the field.
- **`plugins show` says disabled:** Run `hermes plugins enable
  reasoning-preserve` and restart the session.
- **A strict OpenAI backend is rejecting requests:** This plugin never fires
  for strict providers. If you are seeing rejections on a strict backend, the
  cause is elsewhere.

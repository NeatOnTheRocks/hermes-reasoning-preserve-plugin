## reasoning-preserve installed

Re-injects `reasoning_content` into outgoing requests for `custom` OpenAI-compatible
providers (llama.cpp) whose chat template reads it — restoring multi-turn reasoning
continuity for local models.

**One thing to confirm:** your `custom` backend's chat template reads
`message.reasoning_content`. If it doesn't, the plugin is inert (harmless, but a
no-op). No `config.yaml` flag is needed.

**Restart the gateway** to activate:

```bash
hermes gateway restart
```

It is self-scoping and fail-open: it does nothing for strict providers that reject
the field, and it skips messages that already carry `reasoning_content`.

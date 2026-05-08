# Strix with DeepSeek V4 Pro on DigitalOcean Serverless Inference

DigitalOcean's serverless inference exposes an OpenAI-compatible endpoint, so Strix
talks to it through litellm's `openai/...` provider prefix — same plumbing as a
self-hosted OpenAI-compatible server.

## Install

```bash
pipx install . --force
strix -v
```

## Configure

You need three things from the DigitalOcean inference console:

1. **Base URL** — the OpenAI-compatible endpoint for your inference resource
   (looks like `https://<something>.do-ai.run/v1` or similar). Copy whatever
   value works for you in opencode.
2. **API key** — the inference access key.
3. **Model identifier** — the exact string DO uses for DeepSeek V4 Pro on this
   endpoint. Copy it verbatim.

```bash
# Provider routing — openai/<model-id> tells litellm to use the OpenAI-compatible
# wire format. Replace <deepseek-v4-pro-model-id> with the exact ID from DO.
export STRIX_LLM="openai/<deepseek-v4-pro-model-id>"

# Credentials and endpoint
export LLM_API_KEY="<your DigitalOcean inference key>"
export LLM_API_BASE="<your DigitalOcean inference base URL, ending in /v1>"

# Optional: cap reasoning effort if the model supports it
# export STRIX_REASONING_EFFORT="medium"
```

That's it — Strix reads these via `resolve_llm_config()` in
`strix/config/config.py:202` and forwards them to litellm's `completion()`
calls (`strix/llm/llm.py:235-244`).

## Run

```bash
strix -t https://target.example.com \
    --instruction "Test using username=demo@account password=password123"
```

## Verifying tool calls work

Strix uses an XML tool-call format that the model emits as plain text — the
model doesn't need native OpenAI `tools` support, only the discipline to
produce well-formed `<function=...>...</function>` blocks. If it works in
opencode (which uses the same tool-call style for non-native providers), it
will work here.

First-run sanity check:

```bash
strix -t https://target.example.com -n
# After a minute, peek at the events log:
ls strix_runs/
tail -n 50 strix_runs/<latest>/events.jsonl | grep tool.execution.started
```

You should see `scan_start_info` followed by recon tool calls. If the run
stalls with no tool calls, the model is likely returning prose instead of
tool XML — try a different model ID or lower the reasoning effort.

## Troubleshooting

- **401 / 403 from the endpoint** — `LLM_API_KEY` is wrong or the inference
  resource isn't authorized for this model.
- **404 on the model** — the `openai/...` suffix doesn't match the model ID
  DO exposes. Check the DO console; some setups namespace models as
  `account/model` while litellm just needs the bare ID after `openai/`.
- **`api_base` ignored** — make sure you exported `LLM_API_BASE` (Strix also
  accepts `OPENAI_API_BASE` and `LITELLM_BASE_URL` as fallbacks; see
  `strix/config/config.py:220-225`).
- **Wonky tool-call parsing** — DeepSeek occasionally wraps tool calls in
  ```` ```xml ```` fences. Strix already strips a few common variants in
  `strix/llm/utils.py:normalize_tool_format`; if you see consistent
  failures, that's the file to extend.

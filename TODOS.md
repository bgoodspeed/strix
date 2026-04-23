<  Strix architecture (token-heavy)

  - Monolithic system prompt at strix/agents/StrixAgent/system_prompt.jinja — 431 lines, loaded in full on every LLM call (strix/llm/llm.py:78-104). Explicitly mandates "GO SUPER HARD" and "2000+ steps MINIMUM" (lines
  45-59), which actively incentivizes longer runs.
  - Single growing conversation per agent. Tool outputs are appended unfiltered to state.messages (base_agent.py:423). Errors get truncated at 500 chars (executor.py:182-183), but normal outputs don't.
  - Subagents duplicate context. agents_graph_actions.py:254-255 inherits the parent's full conversation history and re-loads the 431-line system prompt for each child. Each vulnerability × component gets its own
  subagent (per the prompt's instructions at lines 211-232).
  - Late compaction only. memory_compressor.py fires at 90K tokens (MAX_TOTAL_TOKENS = 100_000) and keeps the last 15 messages raw. Uses an LLM call to summarize — more tokens.
  - Cache is system-prompt-only. llm.py:318-334 marks the system block with cache_control: ephemeral but nothing else. 5-min TTL + fresh subagents = frequent misses.
  - No model routing visible — one model for everything.

  Shannon architecture (token-lean)

  - Per-phase scoped prompts in apps/worker/prompts/: recon (385), vuln-* (286–368), exploit-* (421–500), report (131). Modular @include for shared fragments (_target.txt, _rules.txt, login instructions).
  - Fresh conversation per agent. services/agent-execution.ts:144 literally passes '' as context. No transcript bleed between phases.
  - File-based handoffs. Agents write .shannon/deliverables/*.md and JSON queues; downstream agents read only what they need from disk, not via LLM context (apps/worker/prompts/vuln-xss.txt:43-45).
  - Temporal workflows do the top-level orchestration deterministically (temporal/workflows.ts) — no LLM-driven "what next?" at the phase level.
  - Model tiering (ai/models.ts:19-36): Opus → pre-recon, Sonnet → recon/vuln/exploit, Haiku → report. Overridable via ANTHROPIC_*_MODEL env vars.
  - No prompt caching (actually worse than Strix on this one dimension).

  Why Strix costs more

  The dominant factor is context stacking: a growing conversation + subagents that each carry the parent's full history + a duplicated 431-line system prompt per agent. Shannon short-circuits this by restarting the
  context window at every phase boundary and using disk as the shared memory. The "2000+ steps" language compounds the multiplier.

  Practical improvements for Strix (ranked)

  1. Pass structured summaries, not full transcripts, to subagents. Change the agents_graph default from "inherit full history" to "inherit structured handoff" — a short JSON or markdown blob. Biggest single win.
  2. Split the 431-line prompt into phase/role variants. Recon agents don't need exploit rules; reporting agents don't need recon tooling.
  3. Add disk-based deliverables. Let agents write findings to files and read siblings' outputs on demand, rather than keeping them in message history.
  4. Model routing. Haiku for reporting/summarization/triage; keep Sonnet/Opus for the hard loop. strix/llm/config.py already has the plumbing.
  5. Soften the escalation language in the system prompt ("2000+ steps", "GO SUPER HARD"). It literally pays you to run longer.
  6. Trim tool outputs at the source (terminal stdout, browser DOM dumps, web search results) before they hit state.messages, not only on error.
  7. Extend cache markers to the last stable message boundary, not just the system prompt — so mid-conversation replays hit the cache.
  8. Compact earlier — drop the 90K threshold way down, or do rolling summarization of older tool results.

  Rough guess: items 1–3 alone would likely cut token usage by 3–5× on multi-agent runs without changing output quality.


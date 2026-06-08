# SPEC v0 — claude-agent-sdk trace capture

Status: **v0 / scaffolding**. This document is the agreed design for the initial
build. It records *what* we are building and *why each decision was made*, so the
rationale survives past the conversation that produced it.

SDK pinned at install time: **`claude-agent-sdk` 0.2.93**. The hook/message API
notes below were verified against that version's installed source, not docs.

---

## 1. Purpose & scope

The eventual intent is **(b) evaluation / benchmarking** of a Claude agent —
comparing cost, latency, and behavior across runs. But there is **no comparison
axis and no task set yet**. Building an evaluation/batch/comparison layer against
undefined comparisons would mean guessing a schema that will be wrong.

So v0 is deliberately scoped to a **maximal single-run tracer**:

- Capture the maximum useful data from *one* agent run.
- Stamp every run with a `run_id` + timestamp so today's traces become a
  comparable dataset later, with zero rework.
- **Explicitly out of scope for v0:** batch runner, per-task success/failure
  judging, cross-run comparison tooling. These are added once a real axis and
  task set exist.

## 2. What is captured (per run)

Maximal capture, every run:

- System prompt and user prompt.
- Every assistant turn: text blocks and tool-use blocks.
- **Thinking** blocks (adaptive thinking is enabled), captured as their own
  span type — stored separately from assistant text.
- Tool **definitions** (name / description / input schema), serialized once at
  startup from the registered tools.
- Every tool **call** (input) and **result** (output).
- Per-tool **latency**, via `PreToolUse` → `PostToolUse` / `PostToolUseFailure`,
  correlated by `tool_use_id`.
- Per-turn **token usage** (`AssistantMessage.usage`).
- Aggregate **duration / cost / model breakdown** (`ResultMessage`:
  `duration_ms`, `duration_api_ms`, `total_cost_usd`, `usage`, `model_usage`).
- The **model** is unpinned (SDK default) but is **recorded** in the trace, so
  cross-model comparison is possible later.

Tool **failures** are first-class: a failed tool call is a separately-typed
event in both outputs (not folded into "result").

## 3. Outputs

Two artifacts per run, in a per-run directory:

```
traces/<timestamp>-<run_id>/
    trace.jsonl      # source of truth
    transcript.md    # human-readable projection
```

### 3.1 `trace.jsonl` — source of truth

- Append-only JSONL, one span per line.
- Written **live** by a **single background writer** task draining an
  `asyncio.Queue`. Hooks/handlers never write to disk directly — they only
  stamp time and enqueue a span. This keeps disk I/O off the latency hot path
  and means a single writer owns the file handle (no torn concurrent writes).
- Crash-resilient: spans hit disk as they are produced, so a crash mid-run
  leaves a valid partial trace.
- Every span carries a monotonic **`seq`** integer (assigned by the writer as it
  drains the queue) giving a total capture order independent of wall-clock.

### 3.2 `transcript.md` — projection

- A **pure projection** of `trace.jsonl`: `render(jsonl) -> markdown`.
- Rendered at end-of-run, and **regenerable** standalone from any past JSONL via
  `render.py` (see §6). The JSONL is authoritative; the Markdown is derived.
- Ordered chronologically by `seq`.
- A single causal event log (everything that happened, in order) rendered for
  humans — not a "context snapshot".
- **Thinking** is shown **inline, in causal position, visually demarcated**
  (collapsible / blockquoted reasoning section), so the conversation reads in
  order with reasoning set apart.
- **Failures** render inline as error callouts, so recovery behavior is visible.

## 4. Tools (v0: dummy, representative, upgradeable)

Three dummy tools, chosen so a single seed task exercises every capture path.
They are placeholders to be swapped for real tools later; the tracer keys off
`tool_use_id` / `tool_name`, never tool internals, so swapping them needs no
tracer change.

| Tool          | Character                              | Exercises                  |
|---------------|----------------------------------------|----------------------------|
| `calculate`   | fast, deterministic; fails on div-by-0 / unknown op | failure path |
| `read_file`   | real I/O latency, offline/reproducible; fails on missing path | latency variance + failure |
| `word_count`  | independent of the other two           | parallel tool use          |

The baked-in seed prompt deliberately induces: latency variance, a
failure-then-recover, and at least one parallel tool-call pair.

## 5. Hook / SDK integration notes (verified against 0.2.93)

These corrected several errors in the summarized public docs:

- Hook callback signature is **three positional args**:
  `async def hook(input_data, tool_use_id, context)`.
  - `input_data` is a discriminated dict (`hook_event_name`), carrying
    `tool_name`, `tool_input`, `tool_use_id`, and (Post*) `tool_response` /
    (failure) `error`.
  - `tool_use_id` is also passed as the 2nd positional arg.
  - `context` (`HookContext`) is currently `{"signal": None}` — holds nothing
    useful yet.
- Hooks are registered as a **dict keyed by event name**:
  `hooks={"PreToolUse": [HookMatcher(hooks=[cb])], ...}`.
- **`PostToolUseFailure` is a separate event** — failed tools fire it, *not*
  `PostToolUse`. Both are hooked, or failed-tool timers leak.
- `tool_use_id` is **unique per tool call** → correct latency correlation under
  parallel tool use. It also equals `ToolUseBlock.id` in the message stream, so
  hook spans and message-stream content share a join key.
- Tracer hooks are **observe-only**: they return `{}` (no decision) and never
  block execution.
- Timing: capture both `time.perf_counter()` (monotonic, for latency deltas) and
  `time.time()` (wall-clock, for human-readable timestamps).
- Options object is **`ClaudeAgentOptions`** (the old `ClaudeCodeOptions` is
  gone). Relevant fields: `system_prompt`, `mcp_servers`, `allowed_tools`,
  `hooks`, `include_partial_messages` (we leave **False** in v0 — no token-level
  timing), `include_hook_events`.

## 6. Run contract

- Dev setup: `uv` project (`pyproject.toml` + `uv.lock`), `requires-python
  >=3.10`, uv-managed `.venv`.
- **Run the agent:** `uv run agent.py [optional prompt override]`
  - Zero-arg: uses a baked-in default seed prompt + a hardcoded system prompt.
  - The system prompt is part of what is benchmarked, so it is logged as the
    first span, not hidden.
  - Output lands in `traces/<timestamp>-<run_id>/`.
- **Re-render a transcript from any past trace:**
  `uv run render.py traces/<dir>/trace.jsonl`
  - `render_markdown(jsonl_path) -> transcript.md` is a pure function with a
    standalone entry point, so historical traces can be re-rendered (e.g. after
    a rendering-bug fix) without re-running the agent.

## 7. Deferred (not in v0)

- Batch runner over a task set.
- Per-task success/failure evaluation.
- Cross-run comparison / regression tooling.
- Token-level / time-to-first-token timing (`include_partial_messages`).
- Real (non-dummy) tools.

# claude-agents-sdk-trace

Trace-capture and observability for a [Claude Agent SDK](https://pypi.org/project/claude-agent-sdk/)
agent run. It runs a single-shot agent with a few tools and captures the
**maximum useful data** from the run to disk: prompts, tool definitions,
per-tool latency, thinking, token usage, and aggregate cost/duration.

> **Status: v0 / scaffolding.** The design is fully specified in
> [`SPEC.md`](./SPEC.md); the implementation (tracer package, tools, entry
> points) is being built out. See [Project status](#project-status) below.

## What it captures

Every run produces two artifacts in a per-run directory:

```
traces/<timestamp>-<run_id>/
    trace.jsonl      # source of truth — one span per line
    transcript.md    # human-readable projection of the JSONL
```

- **System + user prompts**, every assistant turn (text and tool-use blocks).
- **Thinking** blocks (adaptive thinking enabled), captured as their own span
  type and rendered inline-but-demarcated in the transcript.
- **Tool definitions** (name / description / input schema).
- Every **tool call and result**, with **per-tool latency** correlated by
  `tool_use_id` — correct even under parallel tool use.
- **Tool failures** as a first-class, separately-typed event.
- **Per-turn token usage**, and aggregate **duration / cost / model breakdown**
  from the run's `ResultMessage`. The model is recorded (not pinned).

## Design at a glance

- **JSONL is the source of truth.** It is written live by a single background
  writer draining an `asyncio.Queue`, so disk I/O stays off the latency hot path
  and a crash mid-run still leaves a valid partial trace. Every span carries a
  monotonic `seq`.
- **The Markdown transcript is a pure projection** of the JSONL —
  `render(jsonl) -> markdown` — regenerable from any past trace without
  re-running the agent.

The full rationale (and the verified Claude Agent SDK 0.2.93 hook/message API
notes that back it) lives in [`SPEC.md`](./SPEC.md).

## Requirements

- Python ≥ 3.10
- [`uv`](https://docs.astral.sh/uv/)
- Claude Code logged in with your Claude Max / subscription account. The runner
  deliberately strips inherited `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN`
  variables before starting the SDK so the Claude Code CLI uses subscription
  auth instead of API-key auth.

## Setup

```sh
uv sync
```

This creates the project `.venv` and installs the locked dependencies.

## Usage

> These entry points are defined by the spec and are part of the in-progress
> v0 build.

Run the agent (zero-arg uses a baked-in seed prompt + system prompt; pass a
string to override the prompt):

```sh
uv run agent.py
uv run agent.py "your prompt here"
```

Re-render a transcript from any past trace (pure projection, no agent run):

```sh
uv run render.py traces/<dir>/trace.jsonl
```

## Tools (v0)

Three dummy-but-representative tools, chosen so a single run exercises every
capture path. They are placeholders to be swapped for real tools later — the
tracer keys off `tool_use_id` / `tool_name`, never tool internals, so swapping
them requires no tracer change.

| Tool         | Character                                            | Exercises               |
|--------------|------------------------------------------------------|-------------------------|
| `calculate`  | fast, deterministic; fails on div-by-0 / unknown op  | failure path            |
| `read_file`  | real I/O latency, offline; fails on missing path     | latency variance + failure |
| `word_count` | independent of the other two                         | parallel tool use       |

## Project status

Built:

- uv project scaffolding, `claude-agent-sdk` 0.2.93 pinned.
- [`SPEC.md`](./SPEC.md) — complete v0 design.
- `tracer/` package — async-queue writer, hooks, Markdown renderer.
- `tools.py`, `agent.py`, `render.py`.

Deferred (not v0): batch runner over a task set, per-task success/failure
evaluation, cross-run comparison tooling, token-level timing, real tools.

"""Render trace JSONL into a human-readable Markdown transcript."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def render_markdown(jsonl_path: str | Path) -> Path:
    """Render ``trace.jsonl`` to sibling ``transcript.md`` and return its path."""
    path = Path(jsonl_path)
    spans = _read_spans(path)
    markdown = _render(spans)
    output_path = path.with_name("transcript.md")
    output_path.write_text(markdown, encoding="utf-8")
    return output_path


def _read_spans(path: Path) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                spans.append(json.loads(line))
    return sorted(spans, key=lambda span: span.get("seq", 0))


def _render(spans: list[dict[str, Any]]) -> str:
    run_meta = next((span for span in spans if span["type"] == "run_start"), {})
    title = run_meta.get("run_id", "unknown")
    lines = [f"# Claude Agent Trace `{title}`", ""]

    if run_meta:
        lines.extend(
            [
                f"- Timestamp: `{run_meta.get('timestamp')}`",
                f"- Auth mode: `{run_meta.get('auth_mode', 'unknown')}`",
                f"- Trace source: `trace.jsonl`",
                "",
            ]
        )

    for span in spans:
        renderer = _RENDERERS.get(span["type"], _render_generic)
        lines.extend(renderer(span))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _render_prompt(span: dict[str, Any]) -> list[str]:
    role = span.get("role", "prompt").title()
    return [f"## {span['seq']}. {role} Prompt", "", _code(span.get("content", ""))]


def _render_tool_definition(span: dict[str, Any]) -> list[str]:
    return [
        f"## {span['seq']}. Tool Definition: `{span.get('name')}`",
        "",
        span.get("description") or "",
        "",
        _code(json.dumps(span.get("input_schema", {}), indent=2, sort_keys=True), "json"),
    ]


def _render_assistant_text(span: dict[str, Any]) -> list[str]:
    return [f"## {span['seq']}. Assistant", "", span.get("text", "")]


def _render_thinking(span: dict[str, Any]) -> list[str]:
    thinking = span.get("thinking") or ""
    return [
        f"## {span['seq']}. Thinking",
        "",
        "<details>",
        "<summary>Reasoning</summary>",
        "",
        "\n".join(f"> {line}" if line else ">" for line in thinking.splitlines()),
        "",
        "</details>",
    ]


def _render_assistant_tool_use(span: dict[str, Any]) -> list[str]:
    return [
        f"## {span['seq']}. Assistant Tool Use: `{span.get('tool_name')}`",
        "",
        f"- Tool use id: `{span.get('tool_use_id')}`",
        "",
        _code(json.dumps(span.get("tool_input", {}), indent=2, sort_keys=True), "json"),
    ]


def _render_tool_call(span: dict[str, Any]) -> list[str]:
    return [
        f"## {span['seq']}. Tool Call: `{span.get('tool_name')}`",
        "",
        f"- Tool use id: `{span.get('tool_use_id')}`",
        "",
        _code(json.dumps(span.get("tool_input", {}), indent=2, sort_keys=True), "json"),
    ]


def _render_tool_result(span: dict[str, Any]) -> list[str]:
    latency = span.get("latency_ms")
    latency_text = f"{latency:.1f} ms" if isinstance(latency, (int, float)) else "unknown"
    return [
        f"## {span['seq']}. Tool Result: `{span.get('tool_name')}`",
        "",
        f"- Tool use id: `{span.get('tool_use_id')}`",
        f"- Latency: `{latency_text}`",
        "",
        _code(json.dumps(span.get("tool_response"), indent=2, sort_keys=True), "json"),
    ]


def _render_tool_failure(span: dict[str, Any]) -> list[str]:
    latency = span.get("latency_ms")
    latency_text = f"{latency:.1f} ms" if isinstance(latency, (int, float)) else "unknown"
    return [
        f"## {span['seq']}. Tool Failure: `{span.get('tool_name')}`",
        "",
        f"> Error: {span.get('error')}",
        "",
        f"- Tool use id: `{span.get('tool_use_id')}`",
        f"- Latency: `{latency_text}`",
    ]


def _render_usage(span: dict[str, Any]) -> list[str]:
    return [
        f"## {span['seq']}. Assistant Usage",
        "",
        _code(json.dumps(span.get("usage", {}), indent=2, sort_keys=True), "json"),
    ]


def _render_result(span: dict[str, Any]) -> list[str]:
    return [
        f"## {span['seq']}. Result",
        "",
        f"- Subtype: `{span.get('subtype')}`",
        f"- Error: `{span.get('is_error')}`",
        f"- Turns: `{span.get('num_turns')}`",
        f"- Duration: `{span.get('duration_ms')} ms`",
        f"- API duration: `{span.get('duration_api_ms')} ms`",
        f"- Total cost: `{span.get('total_cost_usd')}`",
        "",
        _code(
            json.dumps(
                {
                    "usage": span.get("usage"),
                    "model_usage": span.get("model_usage"),
                    "stop_reason": span.get("stop_reason"),
                    "errors": span.get("errors"),
                },
                indent=2,
                sort_keys=True,
            ),
            "json",
        ),
    ]


def _render_generic(span: dict[str, Any]) -> list[str]:
    return [
        f"## {span['seq']}. {span['type'].replace('_', ' ').title()}",
        "",
        _code(json.dumps(span, indent=2, sort_keys=True), "json"),
    ]


def _code(text: str, lang: str = "") -> str:
    return f"```{lang}\n{text}\n```"


_RENDERERS = {
    "system_prompt": _render_prompt,
    "user_prompt": _render_prompt,
    "tool_definition": _render_tool_definition,
    "assistant_text": _render_assistant_text,
    "thinking": _render_thinking,
    "assistant_tool_use": _render_assistant_tool_use,
    "tool_call": _render_tool_call,
    "tool_result": _render_tool_result,
    "tool_failure": _render_tool_failure,
    "assistant_usage": _render_usage,
    "result": _render_result,
}

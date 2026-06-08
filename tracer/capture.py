"""Async JSONL trace capture for Claude Agent SDK runs."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from claude_agent_sdk import HookMatcher


def utc_timestamp() -> str:
    """Return a filesystem-friendly UTC timestamp."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def make_run_dir(root: Path = Path("traces")) -> tuple[Path, str, str]:
    """Create and return a per-run trace directory plus timestamp and run id."""
    run_id = uuid.uuid4().hex[:12]
    timestamp = utc_timestamp()
    run_dir = root / f"{timestamp}-{run_id}"
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir, timestamp, run_id


def json_safe(value: Any) -> Any:
    """Convert SDK dataclasses and arbitrary values into JSON-safe data."""
    if is_dataclass(value):
        return json_safe(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


class TraceCapture:
    """Queue-backed live JSONL writer plus observe-only SDK hooks."""

    def __init__(self, trace_path: Path, run_id: str, timestamp: str):
        self.trace_path = trace_path
        self.run_id = run_id
        self.timestamp = timestamp
        self._queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        self._writer_task: asyncio.Task[None] | None = None
        self._seq = 0
        self._tool_starts: dict[str, float] = {}

    async def __aenter__(self) -> "TraceCapture":
        self._writer_task = asyncio.create_task(self._writer())
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.close()

    async def close(self) -> None:
        """Flush all queued spans and stop the writer."""
        await self._queue.put(None)
        if self._writer_task is not None:
            await self._writer_task

    async def emit(self, span_type: str, **fields: Any) -> None:
        """Stamp and enqueue a span."""
        await self._queue.put(
            {
                "type": span_type,
                "run_id": self.run_id,
                "wall_time": time.time(),
                "monotonic_time": time.perf_counter(),
                **json_safe(fields),
            }
        )

    def hooks(self) -> dict[str, list[HookMatcher]]:
        """Return observe-only hook registrations for tool timing."""
        return {
            "PreToolUse": [HookMatcher(hooks=[self._pre_tool_use])],
            "PostToolUse": [HookMatcher(hooks=[self._post_tool_use])],
            "PostToolUseFailure": [HookMatcher(hooks=[self._post_tool_use_failure])],
        }

    async def _pre_tool_use(
        self, input_data: dict[str, Any], tool_use_id: str | None, context: dict[str, Any]
    ) -> dict[str, Any]:
        actual_id = tool_use_id or input_data.get("tool_use_id")
        if actual_id:
            self._tool_starts[str(actual_id)] = time.perf_counter()
        await self.emit(
            "tool_call",
            hook_event=input_data.get("hook_event_name"),
            tool_use_id=actual_id,
            tool_name=input_data.get("tool_name"),
            tool_input=input_data.get("tool_input"),
            hook_context=context,
        )
        return {}

    async def _post_tool_use(
        self, input_data: dict[str, Any], tool_use_id: str | None, context: dict[str, Any]
    ) -> dict[str, Any]:
        actual_id = tool_use_id or input_data.get("tool_use_id")
        latency_ms = self._latency_ms(actual_id)
        await self.emit(
            "tool_result",
            hook_event=input_data.get("hook_event_name"),
            tool_use_id=actual_id,
            tool_name=input_data.get("tool_name"),
            tool_input=input_data.get("tool_input"),
            tool_response=input_data.get("tool_response"),
            latency_ms=latency_ms,
            hook_context=context,
        )
        return {}

    async def _post_tool_use_failure(
        self, input_data: dict[str, Any], tool_use_id: str | None, context: dict[str, Any]
    ) -> dict[str, Any]:
        actual_id = tool_use_id or input_data.get("tool_use_id")
        latency_ms = self._latency_ms(actual_id)
        await self.emit(
            "tool_failure",
            hook_event=input_data.get("hook_event_name"),
            tool_use_id=actual_id,
            tool_name=input_data.get("tool_name"),
            tool_input=input_data.get("tool_input"),
            error=input_data.get("error"),
            is_interrupt=input_data.get("is_interrupt"),
            latency_ms=latency_ms,
            hook_context=context,
        )
        return {}

    def _latency_ms(self, tool_use_id: str | None) -> float | None:
        if not tool_use_id:
            return None
        started = self._tool_starts.pop(str(tool_use_id), None)
        if started is None:
            return None
        return (time.perf_counter() - started) * 1000

    async def _writer(self) -> None:
        self.trace_path.parent.mkdir(parents=True, exist_ok=True)
        with self.trace_path.open("a", encoding="utf-8") as handle:
            while True:
                span = await self._queue.get()
                if span is None:
                    self._queue.task_done()
                    break
                span["seq"] = self._seq
                self._seq += 1
                handle.write(json.dumps(span, ensure_ascii=False, sort_keys=True) + "\n")
                handle.flush()
                self._queue.task_done()

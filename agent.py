"""Run one traced Claude Agent SDK session."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    RateLimitEvent,
    ResultMessage,
    ServerToolResultBlock,
    ServerToolUseBlock,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    create_sdk_mcp_server,
    query,
)

from tools import allowed_tool_names, registered_tools, tool_definitions
from tracer import TraceCapture, make_run_dir, render_markdown


SYSTEM_PROMPT = """You are a careful tracing test agent.
Use the available tools when they help. For the seed task, deliberately exercise
the tools: run independent work in parallel when possible, recover from one
expected tool failure, and summarize what happened plainly."""

SEED_PROMPT = """Run the v0 tracer seed task.

1. In parallel where possible, read SPEC.md and count the words in this sentence:
   "single run tracing records prompts tools thinking latency usage and cost"
2. Deliberately call calculate with divide by zero once so the tracer captures a
   failed tool call, then recover by calculating 144 divided by 12.
3. Finish with a compact summary of the tool results and the failure recovery."""

API_KEY_ENV_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
SERVER_NAME = "trace_tools"


async def main() -> int:
    prompt = " ".join(sys.argv[1:]).strip() or SEED_PROMPT
    run_dir, timestamp, run_id = make_run_dir()
    trace_path = run_dir / "trace.jsonl"

    removed_auth_vars = strip_api_key_auth()

    async with TraceCapture(trace_path, run_id, timestamp) as capture:
        await capture.emit(
            "run_start",
            timestamp=timestamp,
            run_id=run_id,
            auth_mode="claude_code_subscription",
            removed_api_key_env_vars=removed_auth_vars,
            sdk="claude-agent-sdk",
            sdk_version="0.2.93",
        )
        await capture.emit("system_prompt", role="system", content=SYSTEM_PROMPT)
        await capture.emit("user_prompt", role="user", content=prompt)
        for definition in tool_definitions():
            await capture.emit("tool_definition", **definition)

        server = create_sdk_mcp_server(SERVER_NAME, tools=registered_tools())
        options = ClaudeAgentOptions(
            tools=[],
            allowed_tools=allowed_tool_names(SERVER_NAME),
            system_prompt=SYSTEM_PROMPT,
            mcp_servers={SERVER_NAME: server},
            hooks=capture.hooks(),
            include_partial_messages=False,
            include_hook_events=False,
            thinking={"type": "adaptive", "display": "summarized"},
            cwd=Path.cwd(),
            max_turns=8,
        )

        try:
            async for message in query(prompt=prompt, options=options):
                await capture_message(capture, message)
        except Exception as exc:  # noqa: BLE001 - failures should be trace artifacts.
            await capture.emit("run_exception", error=repr(exc), error_type=type(exc).__name__)
            raise

    transcript_path = render_markdown(trace_path)
    print(f"Trace written to {trace_path}")
    print(f"Transcript written to {transcript_path}")
    return 0


def strip_api_key_auth() -> list[str]:
    """Prevent inherited Anthropic API-key auth from overriding Claude Code login."""
    removed: list[str] = []
    for name in API_KEY_ENV_VARS:
        if os.environ.pop(name, None) is not None:
            removed.append(name)
    return removed


async def capture_message(capture: TraceCapture, message: Any) -> None:
    if isinstance(message, AssistantMessage):
        await capture_assistant_message(capture, message)
    elif isinstance(message, UserMessage):
        await capture.emit(
            "user_message",
            content=message.content,
            uuid=message.uuid,
            parent_tool_use_id=message.parent_tool_use_id,
            tool_use_result=message.tool_use_result,
        )
    elif isinstance(message, ResultMessage):
        await capture.emit(
            "result",
            subtype=message.subtype,
            duration_ms=message.duration_ms,
            duration_api_ms=message.duration_api_ms,
            is_error=message.is_error,
            num_turns=message.num_turns,
            session_id=message.session_id,
            stop_reason=message.stop_reason,
            total_cost_usd=message.total_cost_usd,
            usage=message.usage,
            model_usage=message.model_usage,
            result=message.result,
            errors=message.errors,
            api_error_status=message.api_error_status,
            uuid=message.uuid,
        )
    elif isinstance(message, SystemMessage):
        await capture.emit(
            "system_message",
            subtype=message.subtype,
            data=message.data,
        )
    elif isinstance(message, RateLimitEvent):
        await capture.emit(
            "rate_limit",
            rate_limit_info=message.rate_limit_info,
            uuid=message.uuid,
            session_id=message.session_id,
        )
    else:
        await capture.emit("message", message_type=type(message).__name__, message=message)


async def capture_assistant_message(capture: TraceCapture, message: AssistantMessage) -> None:
    common = {
        "model": message.model,
        "message_id": message.message_id,
        "session_id": message.session_id,
        "uuid": message.uuid,
        "stop_reason": message.stop_reason,
        "parent_tool_use_id": message.parent_tool_use_id,
    }
    for block in message.content:
        if isinstance(block, TextBlock):
            await capture.emit("assistant_text", text=block.text, **common)
        elif isinstance(block, ThinkingBlock):
            await capture.emit(
                "thinking",
                thinking=block.thinking,
                signature=block.signature,
                **common,
            )
        elif isinstance(block, ToolUseBlock):
            await capture.emit(
                "assistant_tool_use",
                tool_use_id=block.id,
                tool_name=block.name,
                tool_input=block.input,
                **common,
            )
        elif isinstance(block, ToolResultBlock):
            await capture.emit(
                "assistant_tool_result",
                tool_use_id=block.tool_use_id,
                content=block.content,
                is_error=block.is_error,
                **common,
            )
        elif isinstance(block, ServerToolUseBlock):
            await capture.emit(
                "server_tool_use",
                tool_use_id=block.id,
                tool_name=block.name,
                tool_input=block.input,
                **common,
            )
        elif isinstance(block, ServerToolResultBlock):
            await capture.emit(
                "server_tool_result",
                tool_use_id=block.tool_use_id,
                content=block.content,
                **common,
            )
        else:
            await capture.emit(
                "assistant_content_block",
                block_type=type(block).__name__,
                block=block,
                **common,
            )

    if message.usage is not None:
        await capture.emit("assistant_usage", usage=message.usage, **common)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

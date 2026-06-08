"""Dummy tools used by the v0 trace-capture seed run."""

from __future__ import annotations

import asyncio
import operator
from pathlib import Path
from typing import Any

from claude_agent_sdk import SdkMcpTool, tool


CALCULATE_SCHEMA = {
    "type": "object",
    "properties": {
        "operation": {
            "type": "string",
            "enum": ["add", "subtract", "multiply", "divide"],
            "description": "Arithmetic operation to perform.",
        },
        "left": {"type": "number", "description": "Left operand."},
        "right": {"type": "number", "description": "Right operand."},
    },
    "required": ["operation", "left", "right"],
    "additionalProperties": False,
}

READ_FILE_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": "Path to a UTF-8 text file, relative to the project root or absolute.",
        }
    },
    "required": ["path"],
    "additionalProperties": False,
}

WORD_COUNT_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {"type": "string", "description": "Text whose words should be counted."}
    },
    "required": ["text"],
    "additionalProperties": False,
}


@tool("calculate", "Perform a simple arithmetic calculation.", CALCULATE_SCHEMA)
async def calculate(args: dict[str, Any]) -> dict[str, Any]:
    operations = {
        "add": operator.add,
        "subtract": operator.sub,
        "multiply": operator.mul,
        "divide": operator.truediv,
    }
    operation = args["operation"]
    if operation not in operations:
        raise ValueError(f"unknown operation: {operation}")
    if operation == "divide" and args["right"] == 0:
        raise ZeroDivisionError("division by zero")
    result = operations[operation](args["left"], args["right"])
    return _text_result(f"{args['left']} {operation} {args['right']} = {result}")


@tool("read_file", "Read a UTF-8 text file with real local I/O latency.", READ_FILE_SCHEMA)
async def read_file(args: dict[str, Any]) -> dict[str, Any]:
    await asyncio.sleep(0.15)
    path = Path(args["path"]).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    text = path.read_text(encoding="utf-8")
    return _text_result(text)


@tool("word_count", "Count whitespace-delimited words in text.", WORD_COUNT_SCHEMA)
async def word_count(args: dict[str, Any]) -> dict[str, Any]:
    words = args["text"].split()
    return _text_result(f"word_count = {len(words)}")


def registered_tools() -> list[SdkMcpTool[Any]]:
    return [calculate, read_file, word_count]


def tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": tool_def.name,
            "description": tool_def.description,
            "input_schema": tool_def.input_schema,
        }
        for tool_def in registered_tools()
    ]


def allowed_tool_names(server_name: str) -> list[str]:
    return [f"mcp__{server_name}__{tool_def.name}" for tool_def in registered_tools()]


def _text_result(text: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}]}

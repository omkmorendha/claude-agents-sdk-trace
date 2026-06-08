"""Regenerate transcript.md from a trace JSONL file."""

from __future__ import annotations

import sys
from pathlib import Path

from tracer import render_markdown


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: uv run render.py traces/<dir>/trace.jsonl", file=sys.stderr)
        return 2

    jsonl_path = Path(sys.argv[1])
    if not jsonl_path.exists():
        print(f"trace file not found: {jsonl_path}", file=sys.stderr)
        return 1

    output_path = render_markdown(jsonl_path)
    print(f"Transcript written to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Builds prompts for and parses output from the draft generator.

Prompt specs live in /prompts/*.md as human-readable docs. This module
injects the actual inputs into them and parses Gemini's JSON output.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from core.llm.gemini import generate

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"

FORMAT_EMAIL = "email"
FORMAT_LINKEDIN_NOTE = "linkedin_note"
FORMAT_LINKEDIN_DM = "linkedin_dm"

_TEMPLATE_FILES = {
    FORMAT_EMAIL: "email_draft.md",
    FORMAT_LINKEDIN_NOTE: "linkedin_note.md",
    FORMAT_LINKEDIN_DM: "linkedin_note.md",
}


def _read_template(fmt: str) -> str:
    fname = _TEMPLATE_FILES[fmt]
    return (PROMPTS_DIR / fname).read_text(encoding="utf-8")


def build_prompt(fmt: str, inputs: dict) -> str:
    spec = _read_template(fmt)
    if fmt == FORMAT_LINKEDIN_NOTE:
        inputs = {**inputs, "format": "connection_note"}
    elif fmt == FORMAT_LINKEDIN_DM:
        inputs = {**inputs, "format": "dm"}
    payload = json.dumps(inputs, indent=2)
    return f"{spec}\n\n## Actual inputs\n\n```json\n{payload}\n```\n\nProduce the JSON output now."


_CODE_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _parse_json(raw: str) -> dict:
    cleaned = _CODE_FENCE.sub("", raw).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Last-ditch: pull the first {...} block
        m = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        raise


def draft(fmt: str, inputs: dict, temperature: float = 0.65) -> dict:
    prompt = build_prompt(fmt, inputs)
    raw = generate(prompt, temperature=temperature, max_tokens=700)
    return _parse_json(raw)

from __future__ import annotations

from pathlib import Path
from string import Template
from typing import Optional


PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "assets" / "prompts"


def load_prompt(stage_name: str, context: Optional[dict] = None) -> str:
    path = PROMPTS_DIR / f"{stage_name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt template not found: {path}")
    text = path.read_text(encoding="utf-8")
    if context:
        text = Template(text).safe_substitute(context)
    return text

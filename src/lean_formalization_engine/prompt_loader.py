from __future__ import annotations

from pathlib import Path
from typing import Iterable


PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def load_prompt_template(name: str) -> str:
    prompt_path = PROMPTS_DIR / name
    if not prompt_path.is_file():
        raise FileNotFoundError(f"Missing Terry prompt template `{name}` under `{PROMPTS_DIR}`.")
    return prompt_path.read_text(encoding="utf-8")


def render_prompt_template(name: str, **kwargs: object) -> str:
    return load_prompt_template(name).format(**kwargs)


def render_bullet_list(items: Iterable[str]) -> str:
    rendered = [f"- {item}" for item in items]
    if not rendered:
        return "- none"
    return "\n".join(rendered)

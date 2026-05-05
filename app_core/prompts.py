from __future__ import annotations

import re
from pathlib import Path


PROMPTS_FILE = Path(__file__).resolve().parent.parent / "specs" / "promts.md"


def load_prompt_templates() -> dict[str, str]:
    content = PROMPTS_FILE.read_text(encoding="utf-8")
    return {
        "universal_system": _extract_block(content, "#### SYSTEM (universal)", "#### USER (universal) — TEMPLATE"),
        "universal_user": _extract_block(content, "#### USER (universal) — TEMPLATE", "### 2)"),
        "manual_system": _extract_block(content, "#### SYSTEM (manual-question)", "#### USER (manual-question) — TEMPLATE"),
        "manual_user": _extract_block(content, "#### USER (manual-question) — TEMPLATE", "### 4)"),
        "final_system": _extract_block(content, "#### SYSTEM (final-analysis)", "#### USER (final-analysis) — TEMPLATE"),
        "final_user": _extract_block(content, "#### USER (final-analysis) — TEMPLATE", "### 5)"),
        # PII masking was moved to a separate service. These templates are optional.
        "pii_system": _try_extract_block(content, "#### SYSTEM (pii-mask)", "#### USER (pii-mask) — TEMPLATE"),
        "pii_user": _try_extract_block(content, "#### USER (pii-mask) — TEMPLATE", None),
    }


def render_user_template(template: str, **values: str) -> str:
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", value)
    return rendered.strip()


def _extract_block(content: str, start_marker: str, end_marker: str | None) -> str:
    start = content.index(start_marker) + len(start_marker)
    if end_marker is None:
        block = content[start:]
    else:
        end = content.index(end_marker, start)
        block = content[start:end]
    block = block.strip()
    block = re.sub(r"^---\s*$", "", block, flags=re.MULTILINE).strip()
    return block


def _try_extract_block(content: str, start_marker: str, end_marker: str | None) -> str:
    try:
        return _extract_block(content, start_marker, end_marker)
    except ValueError:
        return ""

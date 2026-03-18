import json
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

from domain.models import DocumentBrief, GenerationOptions, SectionBrief


CACHE_ROOT = Path.home() / ".mathhistoria" / "cache"
SECTION_CACHE_DIR = CACHE_ROOT / "sections"
BIBLIOGRAPHY_CACHE_DIR = CACHE_ROOT / "bibliography"


def _stable_hash(payload: dict) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return sha256(encoded).hexdigest()


def build_section_cache_key(
    outline: dict,
    brief: SectionBrief,
    document_brief: DocumentBrief,
    options: GenerationOptions,
) -> str:
    payload = {
        "outline_title": outline.get("title", ""),
        "mathematician": outline.get("mathematician", options.topic),
        "brief": asdict(brief),
        "document_brief": asdict(document_brief),
        "language": options.language,
        "depth": options.depth,
        "focus": options.focus,
        "custom_prompt": options.custom_prompt,
        "existing_context_hash": sha256(options.existing_context.encode("utf-8")).hexdigest(),
        "draft_model": options.model or "",
        "planning_model": options.planning_model or "",
        "generator_version": 4,
    }
    return _stable_hash(payload)


def build_bibliography_cache_key(
    outline: dict,
    document_brief: DocumentBrief,
    section_briefs: list[SectionBrief],
    options: GenerationOptions,
) -> str:
    payload = {
        "outline_title": outline.get("title", ""),
        "mathematician": outline.get("mathematician", options.topic),
        "document_brief": asdict(document_brief),
        "section_briefs": [asdict(brief) for brief in section_briefs],
        "language": options.language,
        "depth": options.depth,
        "focus": options.focus,
        "custom_prompt": options.custom_prompt,
        "draft_model": options.model or "",
        "planning_model": options.planning_model or "",
        "generator_version": 5,
    }
    return _stable_hash(payload)


def load_section_cache(cache_key: str) -> dict | None:
    cache_path = SECTION_CACHE_DIR / f"{cache_key}.json"
    if not cache_path.exists():
        return None
    try:
        return json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_section_cache(cache_key: str, content: str, summary: str) -> None:
    SECTION_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = SECTION_CACHE_DIR / f"{cache_key}.json"
    payload = {"content": content, "summary": summary}
    cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_bibliography_cache(cache_key: str) -> dict | None:
    cache_path = BIBLIOGRAPHY_CACHE_DIR / f"{cache_key}.json"
    if not cache_path.exists():
        return None
    try:
        return json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_bibliography_cache(cache_key: str, plan: dict, content: str) -> None:
    BIBLIOGRAPHY_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = BIBLIOGRAPHY_CACHE_DIR / f"{cache_key}.json"
    payload = {"plan": plan, "content": content}
    cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

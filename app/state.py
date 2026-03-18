import json
import os
import time

import config
from services.tracing import build_trace_path
from utils.keystore import keystore
from utils.security import safe_filename


PREFS_DIR = os.path.expanduser("~/.mathhistoria")
PREFS_FILE = os.path.join(PREFS_DIR, "preferences.json")
DRAFTS_DIR = os.path.join(PREFS_DIR, "drafts")


def _default_preferences() -> dict:
    api_key = keystore.get_api_key("default") or config.API_KEY or ""
    return {
        "api_key": api_key,
        "base_url": config.BASE_URL,
        "draft_model": config.MODEL,
        "planning_model": config.MODEL,
        "ui_language": "zh",
        "language": "en",
        "length": "standard",
        "depth": "undergraduate",
        "focus": "balanced",
        "diversity_count": 3,
        "concurrency": 4,
        "cache_enabled": False,
    }


def load_preferences() -> dict:
    """Load persisted GUI preferences."""
    prefs = _default_preferences()
    if not os.path.exists(PREFS_FILE):
        return prefs

    try:
        with open(PREFS_FILE, "r", encoding="utf-8") as f:
            saved_prefs = json.load(f)
    except Exception:
        return prefs

    saved_prefs.pop("api_key", None)
    if "draft_model" not in saved_prefs and "model" in saved_prefs:
        saved_prefs["draft_model"] = saved_prefs["model"]
    if not saved_prefs.get("base_url"):
        saved_prefs["base_url"] = config.BASE_URL
    if not saved_prefs.get("draft_model"):
        saved_prefs["draft_model"] = config.MODEL
    if not saved_prefs.get("planning_model"):
        saved_prefs["planning_model"] = config.MODEL
    if "ui_language" not in saved_prefs:
        saved_prefs["ui_language"] = prefs["ui_language"]
    saved_prefs["cache_enabled"] = False
    saved_prefs.pop("model", None)
    prefs.update(saved_prefs)
    prefs["cache_enabled"] = False
    return prefs


def save_preferences(prefs: dict) -> None:
    """Persist GUI preferences, storing api_key in the keystore instead of JSON."""
    try:
        os.makedirs(PREFS_DIR, exist_ok=True)
        prefs_to_save = dict(prefs)
        api_key = prefs_to_save.pop("api_key", None)

        if api_key is not None and api_key.strip():
            keystore.save_api_key("default", api_key)
        elif api_key is not None:
            keystore.delete_api_key("default")

        with open(PREFS_FILE, "w", encoding="utf-8") as f:
            json.dump(prefs_to_save, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def _draft_path(draft_id: str) -> str:
    return os.path.join(DRAFTS_DIR, f"{draft_id}.json")


def save_draft(draft_data: dict) -> str | None:
    """Persist an in-progress draft snapshot."""
    try:
        os.makedirs(DRAFTS_DIR, exist_ok=True)
        draft_path = _draft_path(draft_data["draft_id"])
        with open(draft_path, "w", encoding="utf-8") as f:
            json.dump(draft_data, f, indent=2, ensure_ascii=False)
        return draft_path
    except Exception:
        return None


def load_draft(draft_id: str) -> dict | None:
    """Load a saved draft snapshot."""
    try:
        with open(_draft_path(draft_id), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def list_drafts() -> list[dict]:
    """List saved drafts ordered by most recent timestamp."""
    if not os.path.exists(DRAFTS_DIR):
        return []

    drafts: list[dict] = []
    for filename in os.listdir(DRAFTS_DIR):
        if not filename.endswith(".json"):
            continue
        try:
            with open(os.path.join(DRAFTS_DIR, filename), "r", encoding="utf-8") as f:
                drafts.append(json.load(f))
        except Exception:
            continue

    return sorted(drafts, key=lambda item: item.get("timestamp", ""), reverse=True)


def delete_draft(draft_id: str) -> bool:
    """Delete a persisted draft snapshot."""
    try:
        draft_path = _draft_path(draft_id)
        if os.path.exists(draft_path):
            os.remove(draft_path)
        return True
    except Exception:
        return False


def format_draft_list(drafts: list[dict] | None = None) -> tuple[str, list[tuple[str, str]]]:
    """Format drafts for the GUI radio selector."""
    drafts = drafts if drafts is not None else list_drafts()
    if not drafts:
        return "暂无草稿", []

    lines = ["📨 未完成的草稿：\n"]
    choices: list[tuple[str, str]] = []
    for draft in drafts:
        topic = draft.get("topic", "Unknown")
        completed = len(draft.get("completed_sections", []))
        total = draft.get("total_sections", 0)
        timestamp = draft.get("timestamp", "")
        draft_id = draft.get("draft_id", "")

        lines.append(f"• {topic} ({completed}/{total}章) - {timestamp}")
        choices.append((f"{topic} ({completed}/{total}章)", draft_id))

    return "\n".join(lines), choices


def create_draft_record(
    topic: str,
    outline: dict,
    language: str,
    depth: str,
    custom_prompt: str,
    diversity_count: int,
    concurrency: int,
    cache_enabled: bool,
    existing_context: str = "",
    prepared_plan: dict | None = None,
    template_profile: dict | None = None,
    draft_model: str | None = None,
    planning_model: str | None = None,
) -> dict:
    """Create the canonical draft payload used by the GUI flows."""
    draft_id = f"{int(time.time())}_{safe_filename(topic)}"
    trace_path = build_trace_path(draft_id)
    return {
        "draft_id": draft_id,
        "topic": topic,
        "outline": outline,
        "language": language,
        "depth": depth,
        "custom_prompt": custom_prompt,
        "diversity_count": diversity_count,
        "concurrency": int(concurrency),
        "cache_enabled": bool(cache_enabled),
        "existing_context": existing_context,
        "completed_sections": [],
        "section_summaries": [],
        "total_sections": len(outline.get("sections", [])),
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "prepared_plan": prepared_plan,
        "template_profile": template_profile,
        "trace_path": trace_path,
        "draft_model": draft_model or "",
        "planning_model": planning_model or "",
    }


def build_resume_buffers(draft_data: dict) -> tuple[list[str | None], list[str | None]]:
    """Rebuild section/summary buffers aligned to outline order for resume flows."""
    total_sections = int(draft_data.get("total_sections", 0))
    section_contents: list[str | None] = [None] * total_sections
    section_summaries: list[str | None] = [None] * total_sections
    legacy_summaries = draft_data.get("section_summaries", [])

    for position, section in enumerate(draft_data.get("completed_sections", [])):
        try:
            index = int(section.get("index"))
        except (TypeError, ValueError):
            continue

        if not 0 <= index < total_sections:
            continue

        section_contents[index] = section.get("content")
        summary = section.get("summary")
        if summary is None and position < len(legacy_summaries):
            summary = legacy_summaries[position]
        section_summaries[index] = summary

    return section_contents, section_summaries


def append_completed_section(draft_data: dict, section_index: int, content: str, summary: str) -> None:
    """Append a generated section to a draft snapshot."""
    entry = {
        "index": section_index,
        "content": content,
        "summary": summary,
    }

    completed_sections = draft_data.setdefault("completed_sections", [])
    for idx, existing in enumerate(completed_sections):
        if existing.get("index") == section_index:
            completed_sections[idx] = entry
            break
    else:
        completed_sections.append(entry)

    completed_sections.sort(key=lambda item: item.get("index", 0))

    section_summaries = draft_data.setdefault("section_summaries", [])
    while len(section_summaries) <= section_index:
        section_summaries.append(None)
    section_summaries[section_index] = summary

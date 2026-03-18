import re

import pypdf
from openai import OpenAI
from rich.console import Console

import config

console = Console()


def extract_text_from_pdf(pdf_path: str) -> tuple[str, int]:
    """
    Extract text from all pages of a PDF.
    Returns (full_text, page_count).
    """
    reader = pypdf.PdfReader(pdf_path)
    pages = []
    for page in reader.pages:
        text = page.extract_text()
        if text and text.strip():
            pages.append(text.strip())

    full_text = "\n\n".join(pages)
    return full_text, len(reader.pages)


def _extract_block(text: str, start_label: str, end_label: str | None = None) -> str:
    start_pattern = re.escape(start_label) + r"\s*\n"
    if end_label:
        pattern = start_pattern + r"([\s\S]*?)\n" + re.escape(end_label)
    else:
        pattern = start_pattern + r"([\s\S]*)"
    match = re.search(pattern, text)
    return match.group(1).strip() if match else ""


def _extract_single_line(text: str, label: str) -> str:
    match = re.search(rf"^{re.escape(label)}\s*(.+)$", text, re.MULTILINE)
    return match.group(1).strip() if match else ""


def _parse_bullet_block(text: str, start_label: str, end_label: str) -> list[str]:
    block = _extract_block(text, start_label, end_label)
    return [line.strip()[2:].strip() for line in block.splitlines() if line.strip().startswith("- ")]


def _parse_analysis_text(text: str) -> dict:
    result = {
        "mathematician": _extract_single_line(text, "MATHEMATICIAN:"),
        "topic": _extract_single_line(text, "TOPIC:"),
        "summary": _extract_block(text, "SUMMARY:", "END SUMMARY"),
        "covered_sections": _parse_bullet_block(text, "COVERED SECTIONS:", "END COVERED SECTIONS"),
        "missing_areas": _parse_bullet_block(text, "MISSING AREAS:", "END MISSING AREAS"),
    }
    if not result["mathematician"]:
        raise ValueError("Missing mathematician in PDF analysis")
    return result


def analyze_pdf(client: OpenAI, pdf_text: str, page_count: int, max_retries: int = 3, model: str = None) -> dict:
    """
    Ask the LLM to analyze an existing paper/outline PDF.
    Returns a dict with: mathematician, topic, covered_sections, summary, missing_areas.
    """
    excerpt = pdf_text[:6000] + ("\n\n[... content truncated ...]" if len(pdf_text) > 6000 else "")

    messages = [
        {
            "role": "system",
            "content": (
                "You are an academic paper analyst. "
                "Return plain text only, using the requested labels and bullet lists. "
                "Do not return JSON or markdown fences."
            ),
        },
        {
            "role": "user",
            "content": f"""Analyze this mathematics paper or outline ({page_count} pages).

--- DOCUMENT START ---
{excerpt}
--- DOCUMENT END ---

Return ONLY plain text in this structure:

MATHEMATICIAN: Full name of the mathematician discussed
TOPIC: Main topic of the paper
SUMMARY:
Two short sentences describing what the existing document covers.
END SUMMARY
COVERED SECTIONS:
- Topic 1
- Topic 2
- Topic 3
END COVERED SECTIONS
MISSING AREAS:
- Missing topic 1
- Missing topic 2
- Missing topic 3
END MISSING AREAS""",
        },
    ]

    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=model or config.MODEL,
                messages=messages,
                max_tokens=1024,
            )
            text = (response.choices[0].message.content or "").strip()
            return _parse_analysis_text(text)
        except Exception as exc:
            last_error = exc
            if attempt >= max_retries - 1:
                break

    raise RuntimeError(f"Failed to analyze PDF after {max_retries} attempts: {last_error}")

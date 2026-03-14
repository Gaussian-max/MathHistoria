import json
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


def analyze_pdf(client: OpenAI, pdf_text: str, page_count: int, max_retries: int = 3) -> dict:
    """
    Ask the LLM to analyze an existing paper/outline PDF.
    Returns a dict with: mathematician, topic, covered_sections, summary, missing_areas.
    Retries up to max_retries times on JSON parse failure.
    """
    # Feed at most ~6000 chars to avoid hitting context limits
    excerpt = pdf_text[:6000] + ("\n\n[... content truncated ...]" if len(pdf_text) > 6000 else "")

    messages = [
        {
            "role": "system",
            "content": (
                "You are an academic paper analyst. "
                "Read the provided document and return ONLY a JSON object — "
                "no markdown fences, no extra text, no trailing commas."
            ),
        },
        {
            "role": "user",
            "content": f"""Analyze this mathematics paper or outline ({page_count} pages) and return ONLY the JSON below.

--- DOCUMENT START ---
{excerpt}
--- DOCUMENT END ---

Return ONLY this JSON structure (keep all string values short and ASCII-safe):
{{
  "mathematician": "Full name of the mathematician discussed",
  "topic": "Main topic of the paper",
  "covered_sections": ["Topic 1", "Topic 2", "Topic 3"],
  "summary": "Two sentence summary of what the existing document covers.",
  "missing_areas": ["Missing topic 1", "Missing topic 2", "Missing topic 3"]
}}""",
        },
    ]

    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=config.MODEL,
                messages=messages,
                max_tokens=1024,
                temperature=0.2,
            )
            text = response.choices[0].message.content.strip()
            # Strip markdown fences if present
            text = re.sub(r"```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```", "", text)
            # Extract outermost {...}
            match = re.search(r"\{[\s\S]*\}", text)
            if match:
                text = match.group(0)
            return json.loads(text)
        except (json.JSONDecodeError, ValueError) as e:
            last_error = e
            if attempt < max_retries:
                continue

    raise RuntimeError(f"Failed to analyze PDF after {max_retries} attempts: {last_error}")

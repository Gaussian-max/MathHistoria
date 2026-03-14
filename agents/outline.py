import json
import re

from openai import OpenAI

import config


def _extract_json(text: str) -> str:
    """Best-effort extraction of a JSON object from LLM response text."""
    # Strip markdown code fences
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if match:
        text = match.group(1)

    # Extract outermost {...}
    json_match = re.search(r"\{[\s\S]*\}", text)
    if json_match:
        text = json_match.group(0)

    return text.strip()


def generate_outline(client: OpenAI, topic: str, max_retries: int = 3) -> dict:
    """调用 LLM 生成论文大纲，返回结构化 JSON。失败时自动重试。"""

    system_prompt = (
        "You are an expert mathematician and historian of mathematics with a PhD "
        "in both mathematics and history of science. You write comprehensive academic papers. "
        "All output — titles, abstracts, section names, subsections, keywords — must be in English. "
        "Return ONLY valid JSON, no markdown fences, no extra commentary."
    )

    # Simpler prompt to reduce token usage and avoid truncation
    user_prompt = f"""Create a detailed outline for a 50+ page academic paper about {topic}.

Requirements:
- Exactly 12 major sections, each with 3-4 subsections
- Cover: biography, historical context, major mathematical contributions, key theorems/proofs, legacy

Return ONLY this JSON structure:
{{
  "title": "Full paper title",
  "mathematician": "Full Name",
  "birth_year": "YYYY",
  "death_year": "YYYY",
  "nationality": "nationality",
  "abstract": "150-word scholarly abstract",
  "sections": [
    {{"title": "Section Title", "subsections": ["Sub 1", "Sub 2", "Sub 3"]}}
  ],
  "keywords": ["kw1", "kw2", "kw3", "kw4", "kw5"]
}}"""

    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=config.MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=4096,
                temperature=0.5,
            )

            raw = response.choices[0].message.content.strip()
            text = _extract_json(raw)
            result = json.loads(text)

            # Basic validation
            if "sections" not in result or len(result["sections"]) < 5:
                raise ValueError(f"Outline has too few sections: {len(result.get('sections', []))}")

            return result

        except (json.JSONDecodeError, ValueError) as e:
            last_error = e
            if attempt < max_retries:
                continue

    raise RuntimeError(f"Failed to generate valid outline after {max_retries} attempts: {last_error}")


def generate_outline_from_pdf(
    client: OpenAI,
    analysis: dict,
    pdf_text: str,
    existing_pages: int = 0,
    max_retries: int = 3,
) -> dict:
    """
    Generate a full 12-section outline for a rewritten, expanded 50+ page paper based on an existing PDF.
    """
    mathematician = analysis.get("mathematician", "the mathematician")
    covered = ", ".join(analysis.get("covered_sections", []))
    missing = ", ".join(analysis.get("missing_areas", []))
    summary = analysis.get("summary", "")

    system_prompt = (
        "You are an expert mathematician and historian of mathematics. "
        "You are rewriting and greatly expanding an existing partial paper into a comprehensive 50+ page academic work. "
        "All output must be in English. Return ONLY valid JSON, no markdown, no extra text."
    )

    user_prompt = f"""An existing PDF about {mathematician} already covers: {covered}.

Summary of existing content: {summary}

Topics not yet covered (must be included): {missing}

Create a 12-section outline for a COMPLETE, EXPANDED 50+ page paper about {mathematician}.
The outline must:
- Include all topics already in the existing paper (they will be rewritten and greatly expanded)
- Add all missing areas listed above
- Each section must have 3-4 subsections

Return ONLY this JSON:
{{
  "title": "Full paper title",
  "mathematician": "Full Name",
  "birth_year": "YYYY",
  "death_year": "YYYY",
  "nationality": "nationality",
  "abstract": "150-word scholarly abstract",
  "sections": [
    {{"title": "Section Title", "subsections": ["Sub 1", "Sub 2", "Sub 3"]}}
  ],
  "keywords": ["kw1", "kw2", "kw3", "kw4", "kw5"]
}}"""

    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=config.MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=4096,
                temperature=0.5,
            )
            raw = response.choices[0].message.content.strip()
            text = _extract_json(raw)
            result = json.loads(text)
            if "sections" not in result or len(result["sections"]) < 5:
                raise ValueError(f"Outline has too few sections: {len(result.get('sections', []))}")
            return result
        except (json.JSONDecodeError, ValueError) as e:
            last_error = e
            if attempt < max_retries:
                continue

    raise RuntimeError(f"Failed to generate outline from PDF after {max_retries} attempts: {last_error}")

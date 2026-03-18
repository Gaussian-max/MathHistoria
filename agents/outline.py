import re

from openai import OpenAI

import config


def _call_text_completion(
    client: OpenAI,
    *,
    system_prompt: str,
    user_prompt: str,
    model: str | None,
    max_tokens: int,
) -> str:
    response = client.chat.completions.create(
        model=model or config.MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=max_tokens,
    )
    return (response.choices[0].message.content or "").strip()


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


def _parse_pipe_list(raw: str) -> list[str]:
    return [item.strip() for item in raw.split("|") if item.strip()]


def _parse_outline_text(text: str) -> dict:
    title = _extract_single_line(text, "TITLE:")
    mathematician = _extract_single_line(text, "MATHEMATICIAN:")
    birth_year = _extract_single_line(text, "BIRTH_YEAR:")
    death_year = _extract_single_line(text, "DEATH_YEAR:")
    nationality = _extract_single_line(text, "NATIONALITY:")
    keywords = _parse_pipe_list(_extract_single_line(text, "KEYWORDS:"))
    abstract = _extract_block(text, "ABSTRACT:", "END ABSTRACT")

    section_matches = list(re.finditer(r"^SECTION\s+(\d+):\s*(.+)$", text, re.MULTILINE))
    sections: list[dict] = []
    for index, match in enumerate(section_matches):
        start = match.end()
        end = section_matches[index + 1].start() if index + 1 < len(section_matches) else len(text)
        body = text[start:end]
        subsections = [
            line.strip()[2:].strip()
            for line in body.splitlines()
            if line.strip().startswith("- ")
        ]
        sections.append({"title": match.group(2).strip(), "subsections": subsections})

    result = {
        "title": title,
        "mathematician": mathematician,
        "birth_year": birth_year,
        "death_year": death_year,
        "nationality": nationality,
        "abstract": abstract,
        "sections": sections,
        "keywords": keywords,
    }

    if not result["title"] or not result["mathematician"] or len(result["sections"]) < 5:
        raise ValueError("Outline text is incomplete")
    return result


def _outline_format_instructions() -> str:
    return """Return ONLY plain text in this exact structure:

TITLE: Full paper title
MATHEMATICIAN: Full Name
BIRTH_YEAR: YYYY
DEATH_YEAR: YYYY
NATIONALITY: nationality
ABSTRACT:
150-word scholarly abstract
END ABSTRACT
KEYWORDS: kw1 | kw2 | kw3 | kw4 | kw5

SECTION 1: Section Title
- Subsection 1
- Subsection 2
- Subsection 3

SECTION 2: Section Title
- Subsection 1
- Subsection 2
- Subsection 3"""


def generate_outline(
    client: OpenAI,
    topic: str,
    max_retries: int = 3,
    language: str = "en",
    length: str = "standard",
    focus: str = "balanced",
    variant_hint: str = "",
    section_count: int = 0,
    subsection_range: str = "3-5",
    model: str = None,
) -> dict:
    import random

    lang_map = {"en": "English", "zh": "Chinese"}
    output_lang = lang_map.get(language, "English")

    if section_count > 0:
        sections = section_count
    else:
        # 英文：章节更少，每章更短
        if language == "en":
            length_config = {"short": (7, 9), "standard": (9, 11), "long": (13, 15)}
        else:  # zh
            length_config = {"short": (8, 10), "standard": (13, 15), "long": (15, 18)}
        min_sec, max_sec = length_config.get(length, (9, 11) if language == "en" else (13, 15))
        sections = random.randint(min_sec, max_sec)

    pages_config = {"short": "20-30", "standard": "50-60", "long": "70-80"}
    pages = pages_config.get(length, "50-60")

    focus_hint = {
        "balanced": "biography, historical context, major mathematical contributions, key theorems/proofs, legacy",
        "biography": "detailed biography, personal life, historical context, relationships with other mathematicians, cultural impact",
        "mathematics": "mathematical contributions, detailed theorems and proofs, technical developments, influence on modern mathematics",
    }.get(focus, "biography, historical context, major mathematical contributions, key theorems/proofs, legacy")

    system_prompt = (
        f"You are an expert mathematician and historian of mathematics. "
        f"All output must be in {output_lang}. Return plain text only, with the requested labels and no markdown fences."
    )

    user_prompt = f"""Create a detailed outline for a {pages}-page academic paper about {topic}.

This is a historical biography, not a research-methodology paper.

Requirements:
- Exactly {sections} major sections, each with {subsection_range} subsections
- Cover: {focus_hint}
- All content in {output_lang}
- Use concrete, specific section titles tied to the mathematician's actual life and work
- Avoid generic sections like Introduction, Conclusion, Future Work, Significance, Reflection

Candidate flavour:
{variant_hint or "Use a balanced academic structure with only light stylistic variation."}

{_outline_format_instructions()}"""

    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            raw = _call_text_completion(
                client,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=model,
                max_tokens=32000,
            )
            return _parse_outline_text(raw)
        except Exception as exc:
            last_error = exc
            if attempt >= max_retries - 1:
                break

    raise RuntimeError(f"Failed to generate valid outline after {max_retries} attempts: {last_error}")


def generate_outline_from_pdf(
    client: OpenAI,
    analysis: dict,
    pdf_text: str,
    existing_pages: int = 0,
    max_retries: int = 3,
    language: str = "en",
    length: str = "standard",
    focus: str = "balanced",
    section_count: int = 0,
    subsection_range: str = "3-5",
    model: str = None,
) -> dict:
    import random

    mathematician = analysis.get("mathematician", "the mathematician")
    covered = ", ".join(analysis.get("covered_sections", []))
    missing = ", ".join(analysis.get("missing_areas", []))
    summary = analysis.get("summary", "")

    lang_map = {"en": "English", "zh": "Chinese"}
    output_lang = lang_map.get(language, "English")

    if section_count > 0:
        sections = section_count
    else:
        # 英文：章节更少，每章更短
        if language == "en":
            length_config = {"short": (7, 9), "standard": (9, 11), "long": (13, 15)}
        else:  # zh
            length_config = {"short": (8, 10), "standard": (13, 15), "long": (15, 18)}
        min_sec, max_sec = length_config.get(length, (9, 11) if language == "en" else (13, 15))
        sections = random.randint(min_sec, max_sec)

    pages_config = {"short": "20-30", "standard": "50-60", "long": "70-80"}
    pages = pages_config.get(length, "50-60")

    system_prompt = (
        f"You are an expert mathematician and historian of mathematics. "
        f"You are expanding an existing paper into a fuller academic work. "
        f"All output must be in {output_lang}. Return plain text only, with the requested labels and no markdown fences."
    )

    user_prompt = f"""An existing PDF about {mathematician} already covers: {covered}.

Summary of existing content: {summary}

Topics not yet covered and still required: {missing}

Create a complete {sections}-section outline for an expanded {pages}-page paper about {mathematician}.

Requirements:
- Include the themes already present in the existing paper
- Add the missing areas above
- Each section should have {subsection_range} subsections
- Avoid generic academic-template headings
- Use specific, content-rich titles

{_outline_format_instructions()}"""

    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            raw = _call_text_completion(
                client,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=model,
                max_tokens=32000,
            )
            return _parse_outline_text(raw)
        except Exception as exc:
            last_error = exc
            if attempt >= max_retries - 1:
                break

    raise RuntimeError(f"Failed to generate outline from PDF after {max_retries} attempts: {last_error}")

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict

from openai import OpenAI

import config
from agents.outline import generate_outline
from domain.models import DocumentBrief, GenerationOptions, GenerationPlan, SectionBrief


_FOCUS_HINTS = {
    "balanced": "Balance biography, historical context, and mathematics.",
    "biography": "Emphasize biographical narrative and historical relationships.",
    "mathematics": "Emphasize technical mathematical contributions and proofs.",
}

_OUTLINE_VARIANT_HINTS = [
    "Keep a light emphasis on chronological development and intellectual maturation, while still covering mathematical contributions comprehensively.",
    "Keep a light emphasis on organizing the paper around major mathematical contributions, while still preserving biographical continuity and historical context.",
    "Keep a light emphasis on relationships, influence networks, and scholarly reception, while still covering biography and technical work thoroughly.",
]

_BRIEF_VARIANT_HINTS = [
    "Use a slightly more narrative-forward briefing style. Keep section openings and objectives attentive to continuity across the paper.",
    "Use a slightly more mathematics-forward briefing style. Keep must_cover items and key terms precise without losing historical context.",
]


def _pick_variant_hint(hints: list[str], count: int) -> tuple[int, str]:
    active_hints = hints[:count] if count > 0 else hints[:1]
    if not active_hints:
        return 0, ""
    selected_index = __import__("random").randrange(len(active_hints))
    return selected_index, active_hints[selected_index]


def _make_objective(title: str, subsections: list[str], options: GenerationOptions) -> str:
    subsection_text = ", ".join(subsections[:3]) if subsections else "the core themes of this section"
    focus_hint = _FOCUS_HINTS.get(options.focus, _FOCUS_HINTS["balanced"])
    return f"Give {title} a clear role in the paper through {subsection_text}. Keep the chapter selective rather than encyclopedic. {focus_hint}"


def _make_summary(title: str, subsections: list[str], options: GenerationOptions) -> str:
    if subsections:
        joined = ", ".join(subsections[:3])
        return f"This section uses {joined} to advance the paper's treatment of {title}."
    return f"This section advances the paper's treatment of {title}."


def _extract_key_terms(title: str, subsections: list[str]) -> list[str]:
    candidates = [title, *subsections]
    key_terms: list[str] = []
    for item in candidates:
        cleaned = item.strip()
        if cleaned and cleaned not in key_terms:
            key_terms.append(cleaned)
        if len(key_terms) >= 6:
            break
    return key_terms


def _call_text_completion(
    client: OpenAI,
    *,
    system_prompt: str,
    user_prompt: str,
    model: str,
    max_tokens: int,
    max_retries: int = 2,
) -> str:
    last_error: Exception | None = None
    for _ in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=max_tokens,
            )
            if not response.choices:
                raise RuntimeError("Model returned no choices")
            raw = (response.choices[0].message.content or "").strip()
            if not raw:
                raise RuntimeError("Model returned empty content")
            return raw
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"Failed to obtain completion: {last_error}")


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


def _parse_bullet_block(text: str, start_label: str, end_label: str) -> list[str]:
    block = _extract_block(text, start_label, end_label)
    return [line.strip()[2:].strip() for line in block.splitlines() if line.strip().startswith("- ")]


def _format_outline_text(outline: dict) -> str:
    sections = []
    for index, section in enumerate(outline.get("sections", []), 1):
        sections.append(f"SECTION {index}: {section.get('title', f'Section {index}')}")
        for subsection in section.get("subsections", []):
            sections.append(f"- {subsection}")
        sections.append("")

    return "\n".join(
        [
            f"TITLE: {outline.get('title', '')}",
            f"MATHEMATICIAN: {outline.get('mathematician', '')}",
            f"BIRTH_YEAR: {outline.get('birth_year', '')}",
            f"DEATH_YEAR: {outline.get('death_year', '')}",
            f"NATIONALITY: {outline.get('nationality', '')}",
            "ABSTRACT:",
            outline.get("abstract", ""),
            "END ABSTRACT",
            f"KEYWORDS: {' | '.join(outline.get('keywords', []))}",
            "",
            *sections,
        ]
    ).strip()


def _parse_outline_text(text: str) -> dict:
    title = _extract_single_line(text, "TITLE:")
    mathematician = _extract_single_line(text, "MATHEMATICIAN:")
    birth_year = _extract_single_line(text, "BIRTH_YEAR:")
    death_year = _extract_single_line(text, "DEATH_YEAR:")
    nationality = _extract_single_line(text, "NATIONALITY:")
    abstract = _extract_block(text, "ABSTRACT:", "END ABSTRACT")
    keywords = _parse_pipe_list(_extract_single_line(text, "KEYWORDS:"))

    section_matches = list(re.finditer(r"^SECTION\s+(\d+):\s*(.+)$", text, re.MULTILINE))
    sections: list[dict] = []
    for index, match in enumerate(section_matches):
        start = match.end()
        end = section_matches[index + 1].start() if index + 1 < len(section_matches) else len(text)
        body = text[start:end]
        subsections = [line.strip()[2:].strip() for line in body.splitlines() if line.strip().startswith("- ")]
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
        raise ValueError("Parsed outline is incomplete")
    return result


def build_section_briefs(outline: dict, options: GenerationOptions) -> list[SectionBrief]:
    briefs: list[SectionBrief] = []
    for index, section in enumerate(outline.get("sections", []), 1):
        subsections = list(section.get("subsections", []))
        title = section.get("title", f"Section {index}")
        briefs.append(
            SectionBrief(
                index=index,
                title=title,
                subsections=subsections,
                objective=_make_objective(title, subsections, options),
                must_cover=subsections[:4] if subsections else [title],
                key_terms=_extract_key_terms(title, subsections),
                summary=_make_summary(title, subsections, options),
                opening_hint=f"Open by clarifying why {title} matters in this particular paper, rather than sounding like a generic chapter introduction.",
            )
        )
    return briefs


def build_document_brief(topic: str, outline: dict, section_briefs: list[SectionBrief]) -> DocumentBrief:
    mathematician = outline.get("mathematician", topic)
    birth = outline.get("birth_year", "")
    death = outline.get("death_year", "")
    lifespan = f"({birth}--{death})" if birth and death else (birth or "")
    title = outline.get("title", topic)
    abstract = outline.get("abstract", "")
    keywords = list(outline.get("keywords", []))
    narrative_arc = [brief.objective for brief in section_briefs]
    section_summaries = [brief.summary for brief in section_briefs]
    return DocumentBrief(
        title=title,
        mathematician=mathematician,
        lifespan=lifespan,
        abstract=abstract,
        keywords=keywords,
        narrative_arc=narrative_arc,
        section_summaries=section_summaries,
    )


def _build_llm_planning_prompt(
    topic: str,
    outline: dict,
    options: GenerationOptions,
    variant_hint: str = "",
) -> str:
    variant_block = variant_hint or "Keep the planning style balanced and academically grounded."
    return f"""You are planning a long academic paper before drafting any section prose.

Topic: {topic}
Language: {options.language}
Depth: {options.depth}
Focus: {options.focus}
Custom requirements: {options.custom_prompt or "None"}

Outline:
{_format_outline_text(outline)}

Planning flavour:
- {variant_block}

Return ONLY plain text in this structure:

DOCUMENT TITLE: ...
MATHEMATICIAN: ...
LIFESPAN: ...
ABSTRACT:
...
END ABSTRACT
KEYWORDS: kw1 | kw2 | kw3
NARRATIVE ARC:
- ...
- ...
END NARRATIVE ARC
SECTION SUMMARIES:
- ...
- ...
END SECTION SUMMARIES

SECTION BRIEF 1: Section title
SUBSECTIONS: item 1 | item 2 | item 3
OBJECTIVE:
...
END OBJECTIVE
MUST COVER:
- ...
- ...
END MUST COVER
KEY TERMS: term 1 | term 2 | term 3
SUMMARY:
...
END SUMMARY
OPENING HINT:
...
END OPENING HINT

Rules:
- Preserve the original section order exactly
- Do not add or remove sections
- Treat this as an intention card, not a rigid construction blueprint
- Make each section brief concrete, selective, and non-generic
- Keep must_cover and key_terms specific to the mathematician's work
- Do not force the whole paper into a complete cradle-to-legacy life survey if a more selective organizing idea is stronger
- Allow uneven chapter density; some sections can be broad and some narrower
- Let summaries describe the chapter's role, not a full mini-essay
- Keep each MUST COVER list focused; 2 to 4 strong items is better than a long exhaustive checklist
"""


def _format_plan_text(plan: GenerationPlan) -> str:
    lines = [
        f"DOCUMENT TITLE: {plan.document_brief.title}",
        f"MATHEMATICIAN: {plan.document_brief.mathematician}",
        f"LIFESPAN: {plan.document_brief.lifespan}",
        "ABSTRACT:",
        plan.document_brief.abstract,
        "END ABSTRACT",
        f"KEYWORDS: {' | '.join(plan.document_brief.keywords)}",
        "NARRATIVE ARC:",
    ]
    lines.extend(f"- {item}" for item in plan.document_brief.narrative_arc)
    lines.extend(["END NARRATIVE ARC", "SECTION SUMMARIES:"])
    lines.extend(f"- {item}" for item in plan.document_brief.section_summaries)
    lines.extend(["END SECTION SUMMARIES", ""])

    for brief in plan.section_briefs:
        lines.extend(
            [
                f"SECTION BRIEF {brief.index}: {brief.title}",
                f"SUBSECTIONS: {' | '.join(brief.subsections)}",
                "OBJECTIVE:",
                brief.objective,
                "END OBJECTIVE",
                "MUST COVER:",
                *(f"- {item}" for item in brief.must_cover),
                "END MUST COVER",
                f"KEY TERMS: {' | '.join(brief.key_terms)}",
                "SUMMARY:",
                brief.summary,
                "END SUMMARY",
                "OPENING HINT:",
                brief.opening_hint,
                "END OPENING HINT",
                "",
            ]
        )
    return "\n".join(lines).strip()


def _plan_from_data(
    outline: dict,
    options: GenerationOptions,
    data: dict,
    topic: str,
) -> GenerationPlan:
    section_briefs = [
        SectionBrief(
            index=int(item["index"]),
            title=item["title"],
            subsections=list(item.get("subsections", [])),
            objective=item["objective"],
            must_cover=list(item.get("must_cover", [])),
            key_terms=list(item.get("key_terms", [])),
            summary=item.get("summary", ""),
            opening_hint=item.get("opening_hint", ""),
        )
        for item in data["section_briefs"]
    ]

    if len(section_briefs) != len(outline.get("sections", [])):
        raise ValueError("Planning returned mismatched section count")

    doc_data = data["document_brief"]
    document_brief = DocumentBrief(
        title=doc_data.get("title", outline.get("title", topic)),
        mathematician=doc_data.get("mathematician", outline.get("mathematician", topic)),
        lifespan=doc_data.get("lifespan", ""),
        abstract=doc_data.get("abstract", outline.get("abstract", "")),
        keywords=list(doc_data.get("keywords", outline.get("keywords", []))),
        narrative_arc=list(doc_data.get("narrative_arc", [])),
        section_summaries=list(doc_data.get("section_summaries", [])),
    )

    return GenerationPlan(
        outline=outline,
        options=options,
        section_briefs=section_briefs,
        document_brief=document_brief,
    )


def _parse_plan_text(outline: dict, options: GenerationOptions, text: str, topic: str) -> GenerationPlan:
    document_brief = {
        "title": _extract_single_line(text, "DOCUMENT TITLE:") or outline.get("title", topic),
        "mathematician": _extract_single_line(text, "MATHEMATICIAN:") or outline.get("mathematician", topic),
        "lifespan": _extract_single_line(text, "LIFESPAN:"),
        "abstract": _extract_block(text, "ABSTRACT:", "END ABSTRACT") or outline.get("abstract", ""),
        "keywords": _parse_pipe_list(_extract_single_line(text, "KEYWORDS:")) or list(outline.get("keywords", [])),
        "narrative_arc": _parse_bullet_block(text, "NARRATIVE ARC:", "END NARRATIVE ARC"),
        "section_summaries": _parse_bullet_block(text, "SECTION SUMMARIES:", "END SECTION SUMMARIES"),
    }

    section_matches = list(re.finditer(r"^SECTION BRIEF\s+(\d+):\s*(.+)$", text, re.MULTILINE))
    section_briefs: list[dict] = []
    for index, match in enumerate(section_matches):
        start = match.end()
        end = section_matches[index + 1].start() if index + 1 < len(section_matches) else len(text)
        block = text[start:end]
        section_briefs.append(
            {
                "index": int(match.group(1)),
                "title": match.group(2).strip(),
                "subsections": _parse_pipe_list(_extract_single_line(block, "SUBSECTIONS:")),
                "objective": _extract_block(block, "OBJECTIVE:", "END OBJECTIVE"),
                "must_cover": _parse_bullet_block(block, "MUST COVER:", "END MUST COVER"),
                "key_terms": _parse_pipe_list(_extract_single_line(block, "KEY TERMS:")),
                "summary": _extract_block(block, "SUMMARY:", "END SUMMARY"),
                "opening_hint": _extract_block(block, "OPENING HINT:", "END OPENING HINT"),
            }
        )

    if not section_briefs:
        raise ValueError("No section briefs parsed from planning text")

    return _plan_from_data(
        outline,
        options,
        {"document_brief": document_brief, "section_briefs": section_briefs},
        topic,
    )


def build_generation_plan_with_llm(
    client: OpenAI,
    topic: str,
    outline: dict,
    options: GenerationOptions,
    max_retries: int = 2,
    variant_hint: str = "",
) -> GenerationPlan | None:
    prompt = _build_llm_planning_prompt(topic, outline, options, variant_hint=variant_hint)
    model = options.planning_model or options.model or config.MODEL

    for _ in range(max_retries):
        try:
            raw = _call_text_completion(
                client,
                system_prompt="You are an expert planning assistant for long-form academic writing. Return plain text only with the requested labels.",
                user_prompt=prompt,
                model=model,
                max_tokens=12000,
                max_retries=1,
            )
            return _parse_plan_text(outline, options, raw, topic)
        except Exception:
            continue

    return None


def build_generation_plan(
    topic: str,
    outline: dict,
    options: GenerationOptions,
    client: OpenAI | None = None,
) -> GenerationPlan:
    if client is not None:
        planned = build_generation_plan_with_llm(client, topic, outline, options)
        if planned is not None:
            return planned

    section_briefs = build_section_briefs(outline, options)
    document_brief = build_document_brief(topic, outline, section_briefs)
    return GenerationPlan(
        outline=outline,
        options=options,
        section_briefs=section_briefs,
        document_brief=document_brief,
    )


def generation_plan_to_payload(plan: GenerationPlan) -> dict:
    return {
        "outline": plan.outline,
        "document_brief": asdict(plan.document_brief),
        "section_briefs": [asdict(brief) for brief in plan.section_briefs],
    }


def generation_plan_from_payload(payload: dict, options: GenerationOptions, topic: str) -> GenerationPlan:
    return _plan_from_data(
        payload["outline"],
        options,
        {
            "document_brief": payload["document_brief"],
            "section_briefs": payload["section_briefs"],
        },
        topic,
    )


def generate_outline_candidates(
    client: OpenAI,
    topic: str,
    *,
    language: str,
    length: str,
    focus: str,
    section_count: int,
    subsection_range: str,
    model: str | None,
    count: int = 3,
) -> list[dict]:
    hints = _OUTLINE_VARIANT_HINTS[:count]

    def worker(index: int) -> dict:
        hint = hints[index % len(hints)]
        return generate_outline(
            client,
            topic,
            language=language,
            length=length,
            focus=focus,
            variant_hint=hint,
            section_count=section_count,
            subsection_range=subsection_range,
            model=model,
        )

    with ThreadPoolExecutor(max_workers=max(1, min(count, len(hints)))) as executor:
        futures = [executor.submit(worker, idx) for idx in range(count)]
        return [future.result() for future in futures]


def generate_single_outline_candidate(
    client: OpenAI,
    topic: str,
    *,
    language: str,
    length: str,
    focus: str,
    section_count: int,
    subsection_range: str,
    model: str | None,
    variant_count: int = 3,
    custom_requirements: str = "",
    suggested_title: str = "",
) -> tuple[dict, int, int]:
    selected_index, hint = _pick_variant_hint(_OUTLINE_VARIANT_HINTS, variant_count)
    outline = generate_outline(
        client,
        topic,
        language=language,
        length=length,
        focus=focus,
        variant_hint=hint,
        section_count=section_count,
        subsection_range=subsection_range,
        model=model,
        custom_requirements=custom_requirements,
        suggested_title=suggested_title,
    )
    return outline, selected_index, min(max(1, variant_count), len(_OUTLINE_VARIANT_HINTS))


def critique_outline(
    client: OpenAI,
    topic: str,
    outline: dict,
    *,
    language: str,
    focus: str,
    model: str | None,
    custom_requirements: str = "",
) -> str:
    model_name = model or config.MODEL

    user_custom_block = ""
    if custom_requirements:
        user_custom_block = f"\n=== USER-PROVIDED REQUIREMENTS ===\n{custom_requirements}\n=== END USER REQUIREMENTS ===\n"

    try:
        return _call_text_completion(
            client,
            system_prompt="You are a rigorous academic outlining critic. Return plain text only.",
            user_prompt=f"""Review this academic paper outline for a mathematics-history paper.

Topic: {topic}
Language: {language}
Focus: {focus}
{user_custom_block}
Outline:
{_format_outline_text(outline)}

Return plain text only.
- If the outline is already strong, say so briefly.
- Otherwise list concrete problems and the fix for each one.
- Focus on coverage gaps, ordering problems, redundancy, generic titles, forced symmetry, and outlines that drift into a totalized life summary instead of a paper with a clear angle.
- Flag any titles that sound AI-generated or formulaic (e.g., "A Study of...", "An Analysis of...")
- Check if user requirements (if provided) are properly addressed.
""",
            model=model_name,
            max_tokens=4000,
        )
    except Exception as exc:
        return f"Critique skipped: {exc}"


def repair_outline(
    client: OpenAI,
    topic: str,
    outline: dict,
    critique: str,
    *,
    language: str,
    focus: str,
    model: str | None,
    custom_requirements: str = "",
    suggested_title: str = "",
) -> dict:
    model_name = model or config.MODEL

    user_custom_block = ""
    if custom_requirements:
        user_custom_block = f"\n=== USER-PROVIDED REQUIREMENTS (MUST RESPECT) ===\n{custom_requirements}\n=== END USER REQUIREMENTS ===\n"

    title_guidance = ""
    if suggested_title:
        title_guidance = f"\n- IMPORTANT: The user suggested the title \"{suggested_title}\". Preserve its spirit and meaning unless there's a strong reason to change it.\n"

    try:
        raw = _call_text_completion(
            client,
            system_prompt="You repair academic paper outlines. Return plain text only with the requested labels.",
            user_prompt=f"""Repair the following outline using the critique below.

Topic: {topic}
Language: {language}
Focus: {focus}
{user_custom_block}
Original outline:
{_format_outline_text(outline)}

Critique:
{critique}

Return ONLY the repaired outline using this plain-text structure:

TITLE: ...
MATHEMATICIAN: ...
BIRTH_YEAR: ...
DEATH_YEAR: ...
NATIONALITY: ...
ABSTRACT:
...
END ABSTRACT
KEYWORDS: kw1 | kw2 | kw3

SECTION 1: ...
- ...
- ...

Rules:
{title_guidance}- Preserve the overall organizing idea and flavour of the selected outline
- Apply the minimum necessary changes to fix real issues
- Keep the outline academically specific and non-generic
- Prefer local repairs over global rewrites
- Do not normalize the outline into a standard cradle-to-legacy biography if the original has a sharper lens
- Preserve useful asymmetry; do not force every section to look equally weighted
- You may rename, reorder, split, or merge sections only when genuinely necessary
- Keep the repaired outline within roughly plus or minus two sections of the original unless the critique identifies a serious structural failure
- Avoid formulaic titles like "A Study of...", "An Analysis of..."
""",
            model=model_name,
            max_tokens=6000,
        )
        repaired = _parse_outline_text(raw)
    except Exception:
        return outline
    if len(repaired.get("sections", [])) < 5:
        return outline
    return repaired


def generate_brief_candidates(
    client: OpenAI,
    topic: str,
    outline: dict,
    options: GenerationOptions,
    *,
    count: int = 2,
) -> list[GenerationPlan]:
    hints = _BRIEF_VARIANT_HINTS[:count]

    def worker(index: int) -> GenerationPlan:
        hint = hints[index % len(hints)]
        planned = build_generation_plan_with_llm(
            client,
            topic,
            outline,
            options,
            variant_hint=hint,
        )
        if planned is None:
            return build_generation_plan(topic, outline, options, client=None)
        return planned

    with ThreadPoolExecutor(max_workers=max(1, min(count, len(hints)))) as executor:
        futures = [executor.submit(worker, idx) for idx in range(count)]
        return [future.result() for future in futures]


def generate_single_brief_candidate(
    client: OpenAI,
    topic: str,
    outline: dict,
    options: GenerationOptions,
    *,
    variant_count: int = 2,
) -> tuple[GenerationPlan, int, int]:
    selected_index, hint = _pick_variant_hint(_BRIEF_VARIANT_HINTS, variant_count)
    planned = build_generation_plan_with_llm(
        client,
        topic,
        outline,
        options,
        variant_hint=hint,
    )
    if planned is None:
        planned = build_generation_plan(topic, outline, options, client=None)
    return planned, selected_index, min(max(1, variant_count), len(_BRIEF_VARIANT_HINTS))


def critique_generation_plan(
    client: OpenAI,
    topic: str,
    plan: GenerationPlan,
    *,
    model: str | None,
) -> str:
    model_name = model or config.MODEL
    try:
        return _call_text_completion(
            client,
            system_prompt="You are a rigorous academic writing-planning critic. Return plain text only.",
            user_prompt=f"""Review this document brief and section brief pack for an academic mathematics-history paper.

Topic: {topic}

Plan:
{_format_plan_text(plan)}

Return plain text only.
- If the plan is already strong, say so briefly.
- Otherwise list concrete planning problems and fixes.
- Focus on blurry objectives, missing coverage, term inconsistency, cross-section overlap, weak summaries, weak openings, and over-normalized planning that makes every chapter feel equally weighted.
""",
            model=model_name,
            max_tokens=5000,
        )
    except Exception as exc:
        return f"Critique skipped: {exc}"


def repair_generation_plan(
    client: OpenAI,
    topic: str,
    plan: GenerationPlan,
    critique: str,
    *,
    model: str | None,
) -> GenerationPlan:
    model_name = model or config.MODEL
    try:
        raw = _call_text_completion(
            client,
            system_prompt="You repair document briefs and section brief packs. Return plain text only with the requested labels.",
            user_prompt=f"""Repair this brief pack using the critique below.

Topic: {topic}

Original plan:
{_format_plan_text(plan)}

Critique:
{critique}

Return ONLY plain text in this structure:

DOCUMENT TITLE: ...
MATHEMATICIAN: ...
LIFESPAN: ...
ABSTRACT:
...
END ABSTRACT
KEYWORDS: kw1 | kw2 | kw3
NARRATIVE ARC:
- ...
END NARRATIVE ARC
SECTION SUMMARIES:
- ...
END SECTION SUMMARIES

SECTION BRIEF 1: ...
SUBSECTIONS: item 1 | item 2
OBJECTIVE:
...
END OBJECTIVE
MUST COVER:
- ...
END MUST COVER
KEY TERMS: term 1 | term 2
SUMMARY:
...
END SUMMARY
OPENING HINT:
...
END OPENING HINT

Rules:
- Preserve the plan's overall flavour and organization
- Apply the minimum necessary changes to resolve the critique
- Keep section indices aligned with the outline
- Do not add or remove sections
- Do not turn the plan into a rigid full-life survey if the original has a sharper angle
- Preserve uneven chapter density where it helps the paper
- Keep must-cover lists selective rather than exhaustive
""",
            model=model_name,
            max_tokens=7000,
        )
        return _parse_plan_text(plan.outline, plan.options, raw, topic)
    except Exception:
        return plan

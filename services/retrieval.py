import re

from domain.models import SectionBrief


def chunk_text(text: str, chunk_size: int = 1800, overlap: int = 200) -> list[str]:
    if not text:
        return []

    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return []

    chunks: list[str] = []
    start = 0
    step = max(1, chunk_size - overlap)
    while start < len(normalized):
        end = min(len(normalized), start + chunk_size)
        chunks.append(normalized[start:end])
        start += step
    return chunks


def _score_chunk(chunk: str, terms: list[str]) -> int:
    lowered = chunk.lower()
    score = 0
    for term in terms:
        token = term.strip().lower()
        if token:
            score += lowered.count(token)
    return score


def retrieve_section_context(
    existing_context: str,
    brief: SectionBrief,
    max_chunks: int = 3,
) -> str:
    chunks = chunk_text(existing_context)
    if not chunks:
        return ""

    terms = [brief.title, *brief.subsections, *brief.key_terms]
    scored = [(index, _score_chunk(chunk, terms), chunk) for index, chunk in enumerate(chunks)]
    scored.sort(key=lambda item: (item[1], -item[0]), reverse=True)

    selected = [chunk for _, score, chunk in scored[:max_chunks] if score > 0]
    if not selected:
        selected = chunks[:1]

    return "\n\n".join(selected)

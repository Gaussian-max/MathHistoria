from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable

from domain.models import SectionBrief


@dataclass(slots=True)
class SectionGenerationResult:
    index: int
    title: str
    content: str
    summary: str
    from_cache: bool = False
    repaired: bool = False
    review_issue_count: int = 0


def _normalize_worker_payload(payload):
    if isinstance(payload, tuple):
        content, metadata = payload
    else:
        content, metadata = payload, {}
    return content, metadata or {}


def generate_sections(
    briefs: list[SectionBrief],
    worker: Callable[[SectionBrief], str | tuple[str, dict]],
    summary_builder: Callable[[SectionBrief, str], str],
    concurrency: int,
):
    max_workers = max(1, min(concurrency, len(briefs)))
    if not briefs:
        return

    if max_workers == 1:
        for brief in briefs:
            content, metadata = _normalize_worker_payload(worker(brief))
            yield SectionGenerationResult(
                index=brief.index,
                title=brief.title,
                content=content,
                summary=summary_builder(brief, content),
                repaired=bool(metadata.get("repaired", False)),
                review_issue_count=int(metadata.get("review_issue_count", 0)),
            )
        return

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(worker, brief): brief for brief in briefs}
        for future in as_completed(future_map):
            brief = future_map[future]
            content, metadata = _normalize_worker_payload(future.result())
            yield SectionGenerationResult(
                index=brief.index,
                title=brief.title,
                content=content,
                summary=summary_builder(brief, content),
                repaired=bool(metadata.get("repaired", False)),
                review_issue_count=int(metadata.get("review_issue_count", 0)),
            )

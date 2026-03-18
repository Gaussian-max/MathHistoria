from dataclasses import dataclass, field


@dataclass(slots=True)
class GenerationOptions:
    topic: str
    language: str = "en"
    depth: str = "undergraduate"
    focus: str = "balanced"
    custom_prompt: str = ""
    diversity_count: int = 0
    existing_context: str = ""
    model: str | None = None
    planning_model: str | None = None
    concurrency: int = 4
    cache_enabled: bool = True


@dataclass(slots=True)
class SectionBrief:
    index: int
    title: str
    subsections: list[str]
    objective: str
    must_cover: list[str] = field(default_factory=list)
    key_terms: list[str] = field(default_factory=list)
    summary: str = ""
    opening_hint: str = ""

    def to_prompt_block(self) -> str:
        subsections = ", ".join(self.subsections) if self.subsections else "None"
        must_cover = ", ".join(self.must_cover) if self.must_cover else "None"
        key_terms = ", ".join(self.key_terms) if self.key_terms else "None"

        lines = [
            f"SECTION BRIEF {self.index}: {self.title}",
            f"- Objective: {self.objective}",
            f"- Subsections: {subsections}",
            f"- Must cover: {must_cover}",
            f"- Key terms: {key_terms}",
        ]
        if self.summary:
            lines.append(f"- Summary: {self.summary}")
        if self.opening_hint:
            lines.append(f"- Opening hint: {self.opening_hint}")
        return "\n".join(lines)


@dataclass(slots=True)
class DocumentBrief:
    title: str
    mathematician: str
    lifespan: str = ""
    abstract: str = ""
    keywords: list[str] = field(default_factory=list)
    narrative_arc: list[str] = field(default_factory=list)
    section_summaries: list[str] = field(default_factory=list)

    def to_prompt_block(self) -> str:
        keywords = ", ".join(self.keywords) if self.keywords else "None"
        arc = "\n".join(f"- {item}" for item in self.narrative_arc) or "- None"
        summaries = "\n".join(f"- {item}" for item in self.section_summaries) or "- None"

        return (
            "DOCUMENT BRIEF:\n"
            f"- Title: {self.title}\n"
            f"- Subject: {self.mathematician} {self.lifespan}\n"
            f"- Abstract: {self.abstract or 'None'}\n"
            f"- Keywords: {keywords}\n"
            f"- Narrative arc:\n{arc}\n"
            f"- Planned section summaries:\n{summaries}"
        )


@dataclass(slots=True)
class GenerationPlan:
    outline: dict
    options: GenerationOptions
    section_briefs: list[SectionBrief]
    document_brief: DocumentBrief

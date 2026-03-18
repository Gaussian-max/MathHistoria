import gradio as gr
from openai import OpenAI

import config
from agents.generator import generate_paper
from app.pipeline import persist_and_compile_output
from app.state import (
    append_completed_section,
    build_resume_buffers,
    delete_draft,
    load_draft,
    save_draft,
)
from services.tracing import append_trace_event


def _button_states():
    return gr.update(interactive=False), gr.update(interactive=True)


def _t(lang: str, key: str, **kwargs) -> str:
    messages = {
        "trace_log": {
            "en": "Trace log: {path}",
            "zh": "追踪日志：{path}",
        },
        "all_sections_done": {
            "en": "All sections generated.",
            "zh": "所有章节已生成。",
        },
        "compiling_pdf": {
            "en": "Compiling PDF...",
            "zh": "正在编译 PDF...",
        },
        "compile_success": {
            "en": "PDF compiled successfully. Total pages: {pages}\n\nFile: {path}",
            "zh": "PDF 编译成功，共 {pages} 页。\n\n文件：{path}",
        },
        "compile_failed": {
            "en": "PDF compilation failed.\n\nLaTeX file: {path}",
            "zh": "PDF 编译失败。\n\nLaTeX 文件：{path}",
        },
        "generation_failed": {
            "en": "Generation failed: {error}",
            "zh": "生成失败：{error}",
        },
        "draft_load_failed": {
            "en": "Unable to load draft.",
            "zh": "无法加载草稿。",
        },
        "resume_header": {
            "en": "Resuming draft: {topic}\nCompleted {completed}/{total} sections\n{divider}\n",
            "zh": "从草稿恢复：{topic}\n已完成 {completed}/{total} 个章节\n{divider}\n",
        },
    }
    locale = "zh" if lang == "zh" else "en"
    return messages[key][locale].format(**kwargs)


def persist_generated_output(latex_content: str, topic: str, language: str):
    """Persist LaTeX output and compile the matching PDF through the shared pipeline."""
    return persist_and_compile_output(latex_content, topic, language)


def stream_paper_generation(
    client: OpenAI,
    draft_data: dict,
    *,
    topic: str,
    outline: dict,
    language: str,
    depth: str,
    custom_prompt: str,
    diversity_count: int,
    model: str,
    planning_model: str | None = None,
    existing_context: str = "",
    initial_lines: list[str] | None = None,
    resume_from: int = 0,
    resume_sections: list[str] | None = None,
    resume_summaries: list[str] | None = None,
    ui_language: str = "en",
):
    """Shared GUI streaming workflow for fresh generation and draft resume."""
    btn_disabled, btn_enabled = _button_states()
    progress_log = list(initial_lines or [])
    trace_path = draft_data.get("trace_path")
    effective_draft_model = (model or "").strip() or draft_data.get("draft_model") or config.MODEL
    effective_planning_model = (
        (planning_model or "").strip()
        or draft_data.get("planning_model")
        or effective_draft_model
    )

    def progress_callback(msg):
        progress_log.append(msg)
        append_trace_event(trace_path, "progress", message=msg)

    def draft_callback(section_index, content, summary):
        append_completed_section(draft_data, section_index, content, summary)
        save_draft(draft_data)
        append_trace_event(
            trace_path,
            "draft_section_saved",
            section_index=section_index,
            content_length=len(content),
            summary=summary,
        )

    save_draft(draft_data)
    append_trace_event(
        trace_path,
        "run_started",
        topic=topic,
        language=language,
        depth=depth,
        diversity_count=diversity_count,
        draft_model=effective_draft_model,
        planning_model=effective_planning_model,
        concurrency=draft_data.get("concurrency", 4),
        cache_enabled=draft_data.get("cache_enabled", True),
    )
    if trace_path:
        progress_log.append(_t(ui_language, "trace_log", path=trace_path))
    yield "\n".join(progress_log), None, None, btn_disabled, btn_disabled

    try:
        for status, latex_content in generate_paper(
            client,
            topic,
            outline,
            existing_context=existing_context,
            language=language,
            depth=depth,
            custom_prompt=custom_prompt,
            diversity_count=diversity_count,
            progress_callback=progress_callback,
            draft_callback=draft_callback,
            resume_from=resume_from,
            resume_sections=resume_sections,
            resume_summaries=resume_summaries,
            model=effective_draft_model,
            planning_model=effective_planning_model,
            concurrency=draft_data.get("concurrency", 4),
            cache_enabled=draft_data.get("cache_enabled", True),
            prepared_plan_payload=draft_data.get("prepared_plan"),
            template_profile=draft_data.get("template_profile"),
            trace_callback=lambda event, **payload: append_trace_event(trace_path, event, **payload),
        ):
            if status == "progress":
                yield "\n".join(progress_log), None, None, btn_disabled, btn_disabled
                continue

            if status != "done":
                continue

            progress_log.append(f"\n{'-' * 50}\n{_t(ui_language, 'all_sections_done')}\n")
            yield "\n".join(progress_log), None, None, btn_disabled, btn_disabled

            progress_log.append(_t(ui_language, "compiling_pdf"))
            yield "\n".join(progress_log), None, None, btn_disabled, btn_disabled

            append_trace_event(trace_path, "compile_started", topic=topic, language=language)
            latex_path, pdf_path, pages = persist_generated_output(latex_content, topic, language)

            if pdf_path:
                delete_draft(draft_data["draft_id"])
                append_trace_event(
                    trace_path,
                    "compile_succeeded",
                    latex_path=latex_path,
                    pdf_path=pdf_path,
                    pages=pages,
                )
                progress_log.append(_t(ui_language, "compile_success", pages=pages, path=pdf_path))
                yield "\n".join(progress_log), pdf_path, latex_path, btn_enabled, btn_enabled
            else:
                append_trace_event(trace_path, "compile_failed", latex_path=latex_path)
                progress_log.append(_t(ui_language, "compile_failed", path=latex_path))
                yield "\n".join(progress_log), None, latex_path, btn_enabled, btn_enabled
            return
    except Exception as exc:
        append_trace_event(trace_path, "run_failed", error=str(exc))
        yield _t(ui_language, "generation_failed", error=str(exc)), None, None, btn_enabled, btn_enabled


def resume_from_draft_stream(
    draft_id: str,
    api_key: str,
    base_url: str,
    model: str,
    planning_model: str | None = None,
    ui_language: str = "en",
):
    """Resume generation from a saved GUI draft."""
    _, btn_enabled = _button_states()
    draft = load_draft(draft_id)
    if draft is None:
        yield _t(ui_language, "draft_load_failed"), None, btn_enabled, btn_enabled
        return

    topic = draft["topic"]
    total = draft["total_sections"]
    draft_model = (model or "").strip() or draft.get("draft_model") or config.MODEL
    effective_planning_model = (
        (planning_model or "").strip()
        or draft.get("planning_model")
        or draft_model
    )
    resume_sections, resume_summaries = build_resume_buffers(draft)
    completed = sum(content is not None for content in resume_sections)
    initial_lines = [
        _t(ui_language, "resume_header", topic=topic, completed=completed, total=total, divider="-" * 50)
    ]
    client = OpenAI(api_key=api_key, base_url=base_url)

    yield from stream_paper_generation(
        client,
        draft,
        topic=topic,
        outline=draft["outline"],
        language=draft["language"],
        depth=draft["depth"],
        custom_prompt=draft.get("custom_prompt", ""),
        diversity_count=draft.get("diversity_count", 5),
        model=draft_model,
        planning_model=effective_planning_model,
        existing_context=draft.get("existing_context", ""),
        initial_lines=initial_lines,
        resume_from=completed,
        resume_sections=resume_sections,
        resume_summaries=resume_summaries,
        ui_language=ui_language,
    )

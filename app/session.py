import gradio as gr
from openai import OpenAI

import config
from agents.generator import generate_paper
from app.pipeline import persist_and_compile_output
from services.tracing import append_trace_event


def _button_states():
    return gr.update(interactive=False), gr.update(interactive=True)


def _t(lang: str, key: str, **kwargs) -> str:
    messages = {
        "trace_log": "追踪日志：{path}",
        "all_sections_done": "所有章节均已生成。",
        "compiling_pdf": "正在尝试编译 PDF（若失败仍会保留 .tex 文件）……",
        "compile_success": "PDF 编译成功，共 {pages} 页。\n\n文件：{path}",
        "compile_missing_engine": "未检测到 LaTeX 编译环境。已生成 .tex 文件，可直接下载。\n\nLaTeX 文件：{path}",
        "compile_failed": "PDF 编译失败，但已生成 .tex 文件，可直接下载。\n\nLaTeX 文件：{path}",
        "generation_failed": "生成失败：{error}",
        "draft_load_failed": "无法加载草稿。",
        "resume_header": "从草稿恢复：{topic}\n已完成 {completed}/{total} 个章节\n{divider}\n",
    }
    return messages[key].format(**kwargs)


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
    focus: str = "balanced",
    custom_prompt: str,
    diversity_count: int,
    model: str,
    planning_model: str | None = None,
    existing_context: str = "",
    initial_lines: list[str] | None = None,
    resume_from: int = 0,
    resume_sections: list[str] | None = None,
    resume_summaries: list[str] | None = None,
    ui_language: str = "zh",
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

    append_trace_event(
        trace_path,
        "run_started",
        topic=topic,
        language=language,
        depth=depth,
        focus=focus,
        diversity_count=diversity_count,
        draft_model=effective_draft_model,
        planning_model=effective_planning_model,
        concurrency=draft_data.get("concurrency", 4),
        cache_enabled=draft_data.get("cache_enabled", False),
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
            focus=focus,
            custom_prompt=custom_prompt,
            diversity_count=diversity_count,
            progress_callback=progress_callback,
            draft_callback=None,
            resume_from=resume_from,
            resume_sections=resume_sections,
            resume_summaries=resume_summaries,
            model=effective_draft_model,
            planning_model=effective_planning_model,
            concurrency=draft_data.get("concurrency", 4),
            cache_enabled=draft_data.get("cache_enabled", False),
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
            latex_path, pdf_path, pages, compile_status = persist_generated_output(latex_content, topic, language)

            if pdf_path:
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
                if compile_status == "missing_engine":
                    append_trace_event(trace_path, "compile_skipped", latex_path=latex_path, reason="missing_engine")
                    progress_log.append(_t(ui_language, "compile_missing_engine", path=latex_path))
                else:
                    append_trace_event(trace_path, "compile_failed", latex_path=latex_path)
                    progress_log.append(_t(ui_language, "compile_failed", path=latex_path))
                yield "\n".join(progress_log), None, latex_path, btn_enabled, btn_enabled
            return
    except Exception as exc:
        append_trace_event(trace_path, "run_failed", error=str(exc))
        yield _t(ui_language, "generation_failed", error=str(exc)), None, None, btn_enabled, btn_enabled

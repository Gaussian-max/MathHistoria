import json
import os
import random
import time

import gradio as gr
from openai import OpenAI

import config
from agents.generator import sample_template_profile
from agents.outline import generate_outline, generate_outline_from_pdf
from agents.pdf_reader import analyze_pdf, extract_text_from_pdf
from agents.pdf_tools import get_pdf_page_count, merge_pdfs
from agents.suggester import get_suggestions
from app.session import resume_from_draft_stream, stream_paper_generation
from app.state import (
    create_draft_record,
    delete_draft,
    format_draft_list,
    load_preferences,
    save_preferences,
)
from domain.models import GenerationOptions
from services.tracing import append_trace_event, build_trace_path
from services.planning import (
    critique_generation_plan,
    critique_outline,
    generate_single_brief_candidate,
    generate_single_outline_candidate,
    generation_plan_to_payload,
    repair_generation_plan,
    repair_outline,
)
from utils.security import safe_filename


prefs = load_preferences()
suggestions = get_suggestions()
topic_choices = [f"{item['name']} - {item['years']}" for item in suggestions] + ["Custom"]
current_ui_language = prefs.get("ui_language", "zh")

TRANSLATIONS = {
    "app_title": {"en": "MathHistoria", "zh": "MathHistoria"},
    "app_subtitle": {"en": "AI-powered mathematics history paper generator", "zh": "AI 驱动的数学史论文生成器"},
    "integrity_note": {
        "en": "Academic integrity reminder: generated content is for learning and drafting support only. Please verify all references and do not submit raw model output as coursework.",
        "zh": "学术诚信提醒：生成内容仅用于学习与写作辅助。请核对所有参考资料，不要将未经核验的模型输出直接作为课程作业提交。",
    },
    "api_settings": {"en": "API Settings", "zh": "API 设置"},
    "ui_language": {"en": "UI Language", "zh": "界面语言"},
    "ui_language_hint": {"en": "Change the UI language here. Refresh the page to fully rebuild static labels.", "zh": "在这里切换界面语言。刷新页面后，静态标签会完整重建。"},
    "api_key": {"en": "API Key", "zh": "API Key"},
    "base_url": {"en": "Base URL", "zh": "Base URL"},
    "draft_model": {"en": "Draft Model", "zh": "正文模型 (Draft Model)"},
    "planning_model": {"en": "Planning Model (Optional)", "zh": "规划模型 (Planning Model，可选)"},
    "concurrency": {"en": "Max concurrent section jobs", "zh": "最大并发章节任务数"},
    "cache_enabled": {"en": "Enable local section cache", "zh": "启用本地章节缓存"},
    "planning_fallback_hint": {
        "en": "If Planning Model is empty, Draft Model will be used for all planning and review steps.",
        "zh": "如果“规划模型”留空，所有规划与审阅步骤都会自动使用“正文模型”。",
    },
    "tab_quick": {"en": "Quick Generate", "zh": "省心生成"},
    "tab_custom": {"en": "Custom Generate", "zh": "自定义生成"},
    "tab_continue_pdf": {"en": "Continue from PDF", "zh": "从 PDF 续写"},
    "tab_merge": {"en": "Merge PDFs", "zh": "合并 PDF"},
    "quick_help": {"en": "Use the default settings to generate a full paper in one run.", "zh": "使用默认设置，一次生成完整论文。"},
    "mathematician": {"en": "Mathematician", "zh": "数学家"},
    "custom_topic": {"en": "Custom topic", "zh": "自定义主题"},
    "custom_topic_placeholder": {"en": "Example: Emmy Noether", "zh": "例如：Emmy Noether"},
    "generate_zh": {"en": "Generate Chinese Paper", "zh": "生成中文论文"},
    "generate_en": {"en": "Generate English Paper", "zh": "生成英文论文"},
    "progress": {"en": "Progress", "zh": "进度"},
    "pdf_output": {"en": "PDF Output", "zh": "PDF 输出"},
    "resume_draft": {"en": "Resume Draft", "zh": "恢复草稿"},
    "choose_draft": {"en": "Choose a draft", "zh": "选择草稿"},
    "refresh": {"en": "Refresh", "zh": "刷新"},
    "resume": {"en": "Resume", "zh": "继续"},
    "delete": {"en": "Delete", "zh": "删除"},
    "resume_progress": {"en": "Resume Progress", "zh": "恢复进度"},
    "resumed_pdf": {"en": "Resumed PDF Output", "zh": "恢复后的 PDF 输出"},
    "paper_language": {"en": "Paper language", "zh": "论文语言"},
    "target_length": {"en": "Target length", "zh": "目标篇幅"},
    "math_depth": {"en": "Mathematical depth", "zh": "数学深度"},
    "focus": {"en": "Focus", "zh": "侧重点"},
    "extra_requirements": {"en": "Extra requirements", "zh": "额外要求"},
    "extra_requirements_placeholder_1": {"en": "Example: Put more emphasis on the development of the Riemann hypothesis.", "zh": "例如：更强调黎曼猜想的发展脉络。"},
    "extra_requirements_placeholder_2": {"en": "Example: Add more comparison with contemporaries.", "zh": "例如：增加与同时代数学家的比较。"},
    "opening_diversity": {"en": "Opening diversity", "zh": "开头多样性"},
    "section_mode": {"en": "Section mode", "zh": "章节模式"},
    "fixed_section_count": {"en": "Fixed section count", "zh": "固定章节数"},
    "subsections_per_section": {"en": "Subsections per section", "zh": "每章小节数"},
    "generate_outline": {"en": "Generate Outline", "zh": "生成大纲"},
    "status": {"en": "Status", "zh": "状态"},
    "outline_preview": {"en": "Outline Preview", "zh": "大纲预览"},
    "all_outlines_hidden": {"en": "All outlines (hidden)", "zh": "全部大纲（隐藏）"},
    "selected_outline": {"en": "Selected outline", "zh": "当前大纲"},
    "editable_outline_json": {"en": "Editable outline JSON", "zh": "可编辑的大纲 JSON"},
    "generate_paper_from_outline": {"en": "Generate Paper from Outline", "zh": "根据大纲生成论文"},
    "generation_progress": {"en": "Generation Progress", "zh": "生成进度"},
    "existing_pdf": {"en": "Existing PDF", "zh": "已有 PDF"},
    "generate_expanded_outline": {"en": "Generate Expanded Outline", "zh": "生成扩展大纲"},
    "generate_paper_from_pdf_outline": {"en": "Generate Paper from PDF Outline", "zh": "根据 PDF 大纲生成论文"},
    "merge_help": {
        "en": "Upload multiple PDF files and merge selected page ranges into a new file.\n\nPage range examples:\n- `1-5`\n- `1,3,5`\n- `1-5,8-10`\n- `all` or blank for the entire file",
        "zh": "上传多个 PDF 文件，并将指定页码范围合并成一个新文件。\n\n页码范围示例：\n- `1-5`\n- `1,3,5`\n- `1-5,8-10`\n- `all` 或留空表示整份文件",
    },
    "pdf_files": {"en": "PDF files", "zh": "PDF 文件"},
    "page_ranges": {"en": "Page ranges (one line per file, in upload order)", "zh": "页码范围（每个文件一行，按上传顺序）"},
    "page_ranges_placeholder": {"en": "all\n1-5\n3,7-10", "zh": "all\n1-5\n3,7-10"},
    "merge_pdfs": {"en": "Merge PDFs", "zh": "合并 PDF"},
    "footer_notes": {
        "en": "---\n- Use the API settings panel to save your endpoint, draft model, planning model, concurrency, and cache preferences.\n- The custom flow lets you inspect and edit the outline JSON before generation.\n- The PDF continuation flow analyzes an uploaded PDF, expands the outline, and keeps the original text as context.\n- Generation can take several minutes depending on section count and model latency.",
        "zh": "---\n- 可在 API 设置中保存 endpoint、正文模型、规划模型、并发数和缓存偏好。\n- 自定义流程允许你在生成前检查并编辑大纲 JSON。\n- PDF 续写流程会分析上传的 PDF、扩展大纲，并把原文保留为上下文。\n- 生成可能需要几分钟，具体取决于章节数和模型延迟。",
    },
    "please_provide_api_key": {"en": "Please provide an API key.", "zh": "请先填写 API Key。"},
    "please_upload_pdf": {"en": "Please upload a PDF first.", "zh": "请先上传 PDF。"},
    "extracting_pdf": {"en": "Extracting text from the uploaded PDF...", "zh": "正在提取上传 PDF 的文本..."},
    "could_not_extract_pdf": {"en": "Could not extract text from this PDF.", "zh": "无法从该 PDF 中提取文本。"},
    "analyzing_pdf": {"en": "Analyzing the uploaded PDF ({pages} pages)...", "zh": "正在分析上传的 PDF（{pages} 页）..."},
    "generating_outline_candidate": {"en": "Generating outline candidate {index}/3...", "zh": "正在生成大纲候选 {index}/3..."},
    "generated_outline_candidates": {"en": "Generated 3 outline candidates. Randomly selected candidate {index} as the default draft. You can still switch to another candidate below.", "zh": "已生成 3 份大纲候选，默认随机选择第 {index} 份。你仍然可以在下方切换。"},
    "outline_generation_failed": {"en": "Outline generation failed: {error}", "zh": "大纲生成失败：{error}"},
    "generating_expanded_outline_candidate": {"en": "Generating expanded outline candidate {index}/3...", "zh": "正在生成扩展大纲候选 {index}/3..."},
    "detected_mathematician": {"en": "Detected mathematician: {name}. Generated 3 expanded outlines and selected candidate {index} by default.", "zh": "识别出的数学家：{name}。已生成 3 份扩展大纲，并默认选择第 {index} 份。"},
    "pdf_outline_generation_failed": {"en": "PDF outline generation failed: {error}", "zh": "PDF 大纲生成失败：{error}"},
    "selecting_outline_variant": {"en": "Selecting one outline prompt variant and generating the outline...", "zh": "正在选择一个大纲提示词变体并生成大纲..."},
    "selected_outline_variant": {"en": "Selected outline prompt variant {index}/{count}.", "zh": "已选择第 {index}/{count} 个大纲提示词变体。"},
    "critiquing_outline": {"en": "Critiquing selected outline...", "zh": "正在批评所选大纲..."},
    "outline_critique_completed": {"en": "Outline critique completed.", "zh": "大纲批评已完成。"},
    "repairing_outline": {"en": "Repairing selected outline...", "zh": "正在修复所选大纲..."},
    "selecting_brief_variant": {"en": "Selecting one brief prompt variant and generating the brief pack...", "zh": "正在选择一个 brief 提示词变体并生成 brief 包..."},
    "selected_brief_variant": {"en": "Selected brief prompt variant {index}/{count}.", "zh": "已选择第 {index}/{count} 个 brief 提示词变体。"},
    "critiquing_brief": {"en": "Critiquing selected brief pack...", "zh": "正在批评所选 brief 包..."},
    "brief_critique_completed": {"en": "Brief critique completed.", "zh": "brief 批评已完成。"},
    "repairing_brief": {"en": "Repairing selected brief pack...", "zh": "正在修复所选 brief 包..."},
    "frozen_final_outline": {"en": "Frozen final outline:", "zh": "冻结后的最终大纲："},
    "starting_generation_sections": {"en": "Starting paper generation for {count} sections.", "zh": "开始生成论文，共 {count} 个章节。"},
    "quick_generation_failed": {"en": "Quick generation failed: {error}\nTrace log: {trace}", "zh": "省心生成失败：{error}\n追踪日志：{trace}"},
    "generate_or_paste_outline": {"en": "Please generate or paste an outline first.", "zh": "请先生成或粘贴大纲。"},
    "invalid_outline_json": {"en": "The outline JSON is invalid.", "zh": "大纲 JSON 无效。"},
    "paper_generation_failed": {"en": "Paper generation failed: {error}", "zh": "论文生成失败：{error}"},
    "please_choose_draft": {"en": "Please choose a draft.", "zh": "请选择一个草稿。"},
    "please_upload_pdf_files": {"en": "Please upload at least one PDF file.", "zh": "请至少上传一个 PDF 文件。"},
    "preparing_merge_job": {"en": "Preparing merge job:", "zh": "正在准备合并任务："},
    "merging_pdfs": {"en": "Merging PDFs...", "zh": "正在合并 PDF..."},
    "saved_to": {"en": "{message}\nSaved to: {path}", "zh": "{message}\n已保存到：{path}"},
    "merge_failed": {"en": "Merge failed: {message}", "zh": "合并失败：{message}"},
}


def _tr(key: str, **kwargs) -> str:
    locale = "zh" if current_ui_language == "zh" else "en"
    return TRANSLATIONS[key][locale].format(**kwargs)


def _rt(lang: str, key: str, **kwargs) -> str:
    locale = "zh" if lang == "zh" else "en"
    return TRANSLATIONS[key][locale].format(**kwargs)


def _button_states():
    return gr.update(interactive=False), gr.update(interactive=True)


def _topic_from_choice(topic_choice: str, custom_topic: str) -> str:
    if topic_choice == "Custom":
        return custom_topic.strip() if custom_topic.strip() else "Bernhard Riemann"
    return topic_choice.split(" - ")[0]


def _detect_language_from_outline(outline: dict) -> str:
    title = outline.get("title", "")
    return "zh" if any("\u4e00" <= ch <= "\u9fff" for ch in title) else "en"


def _resolve_models(draft_model: str, planning_model: str | None) -> tuple[str, str]:
    resolved_draft = (draft_model or "").strip() or config.MODEL
    resolved_planning = (planning_model or "").strip() or resolved_draft
    return resolved_draft, resolved_planning


def resume_from_draft(draft_id, api_key, base_url, draft_model, planning_model, ui_language):
    resolved_draft, resolved_planning = _resolve_models(draft_model, planning_model)
    yield from resume_from_draft_stream(
        draft_id,
        api_key,
        base_url,
        resolved_draft,
        resolved_planning,
        ui_language=ui_language,
    )


def format_outline_preview(outline: dict) -> str:
    sections = outline.get("sections", [])
    lines = [
        f"# {outline.get('title', 'Untitled')}",
        "",
        f"- Mathematician: {outline.get('mathematician', 'Unknown')}",
        f"- Years: {outline.get('birth_year', '?')} - {outline.get('death_year', '?')}",
        f"- Nationality: {outline.get('nationality', 'Unknown')}",
    ]

    abstract = outline.get("abstract", "").strip()
    if abstract:
        lines.extend(["", "## Abstract", abstract])

    keywords = outline.get("keywords", [])
    if keywords:
        lines.extend(["", f"- Keywords: {', '.join(keywords)}"])

    lines.extend(["", "## Sections"])
    for index, section in enumerate(sections, start=1):
        lines.append(f"### {index}. {section.get('title', 'Untitled Section')}")
        for sub_index, subsection in enumerate(section.get("subsections", []), start=1):
            lines.append(f"{index}.{sub_index} {subsection}")
        lines.append("")

    return "\n".join(lines).strip()


def select_outline(outlines_json, selected_index):
    try:
        outlines = json.loads(outlines_json)
        selected = outlines[int(selected_index)]
        return json.dumps(selected, ensure_ascii=False, indent=2)
    except Exception:
        return outlines_json


def _preview_candidates(outlines: list[dict]) -> str:
    blocks = []
    for idx, outline in enumerate(outlines, start=1):
        blocks.append(f"## Candidate {idx}\n{format_outline_preview(outline)}")
    return "\n\n---\n\n".join(blocks)


def step1_generate_outline(
    topic_choice,
    custom_topic,
    language,
    length,
    focus,
    section_mode,
    section_count,
    subsection_mode,
    api_key,
    base_url,
    draft_model,
    planning_model,
    ui_language,
):
    if not api_key:
        return _rt(ui_language, "please_provide_api_key"), None, None, None, gr.update(visible=False)

    topic = _topic_from_choice(topic_choice, custom_topic)
    client = OpenAI(api_key=api_key, base_url=base_url)
    _, effective_planning_model = _resolve_models(draft_model, planning_model)
    fixed_sections = int(section_count) if section_mode == "fixed" else 0

    try:
        outlines = []
        for index in range(1, 4):
            yield (
                _rt(ui_language, "generating_outline_candidate", index=index),
                None,
                None,
                None,
                gr.update(visible=False),
            )
            outline = generate_outline(
                client,
                topic,
                language=language,
                length=length,
                focus=focus,
                section_count=fixed_sections,
                subsection_range=subsection_mode,
                model=effective_planning_model,
            )
            outlines.append(outline)

        selected_idx = random.randint(0, len(outlines) - 1)
        selected_outline = outlines[selected_idx]
        status = (
            _rt(ui_language, "generated_outline_candidates", index=selected_idx + 1)
        )
        return (
            status,
            _preview_candidates(outlines),
            json.dumps(outlines, ensure_ascii=False, indent=2),
            json.dumps(selected_outline, ensure_ascii=False, indent=2),
            gr.update(visible=True),
        )
    except Exception as exc:
        return _rt(ui_language, "outline_generation_failed", error=exc), None, None, None, gr.update(visible=False)


def step1_generate_outline_from_pdf(
    pdf_file,
    language,
    length,
    focus,
    api_key,
    base_url,
    draft_model,
    planning_model,
    ui_language,
):
    if not api_key:
        return _rt(ui_language, "please_provide_api_key"), None, None, None, gr.update(visible=False)
    if not pdf_file:
        return _rt(ui_language, "please_upload_pdf"), None, None, None, gr.update(visible=False)

    client = OpenAI(api_key=api_key, base_url=base_url)
    _, effective_planning_model = _resolve_models(draft_model, planning_model)
    try:
        yield _rt(ui_language, "extracting_pdf"), None, None, None, gr.update(visible=False)
        pdf_text, page_count = extract_text_from_pdf(pdf_file.name)
        if not pdf_text.strip():
            return _rt(ui_language, "could_not_extract_pdf"), None, None, None, gr.update(visible=False)

        yield _rt(ui_language, "analyzing_pdf", pages=page_count), None, None, None, gr.update(visible=False)
        analysis = analyze_pdf(client, pdf_text, page_count, model=effective_planning_model)
        mathematician = analysis.get("mathematician", "Unknown")

        outlines = []
        for index in range(1, 4):
            yield (
                _rt(ui_language, "generating_expanded_outline_candidate", index=index),
                None,
                None,
                None,
                gr.update(visible=False),
            )
            outline = generate_outline_from_pdf(
                client,
                analysis,
                pdf_text,
                existing_pages=page_count,
                language=language,
                length=length,
                focus=focus,
                model=effective_planning_model,
            )
            outline["_pdf_context"] = pdf_text
            outlines.append(outline)

        selected_idx = random.randint(0, len(outlines) - 1)
        selected_outline = outlines[selected_idx]
        status = (
            _rt(ui_language, "detected_mathematician", name=mathematician, index=selected_idx + 1)
        )
        return (
            status,
            _preview_candidates(outlines),
            json.dumps(outlines, ensure_ascii=False, indent=2),
            json.dumps(selected_outline, ensure_ascii=False, indent=2),
            gr.update(visible=True),
        )
    except Exception as exc:
        return _rt(ui_language, "pdf_outline_generation_failed", error=exc), None, None, None, gr.update(visible=False)


def easy_mode_generate(
    topic_choice,
    custom_topic,
    language,
    api_key,
    base_url,
    draft_model,
    planning_model,
    concurrency,
    cache_enabled,
    ui_language,
):
    btn_disabled, btn_enabled = _button_states()
    if not api_key:
        yield _rt(ui_language, "please_provide_api_key"), None, None, btn_enabled, btn_enabled
        return

    topic = _topic_from_choice(topic_choice, custom_topic)
    client = OpenAI(api_key=api_key, base_url=base_url)
    resolved_draft_model, resolved_planning_model = _resolve_models(draft_model, planning_model)
    progress_log: list[str] = []
    template_profile = sample_template_profile(language)
    trace_run_id = f"quick_{int(time.time())}_{safe_filename(topic)}"
    trace_path = build_trace_path(trace_run_id)
    append_trace_event(
        trace_path,
        "quick_run_started",
        topic=topic,
        language=language,
        draft_model=resolved_draft_model,
        planning_model=resolved_planning_model,
        concurrency=int(concurrency),
        cache_enabled=bool(cache_enabled),
    )
    progress_log.append(f"Trace log: {trace_path}")

    try:
        progress_log.append(_rt(ui_language, "selecting_outline_variant"))
        append_trace_event(trace_path, "outline_variant_selected_started", variant_count=3)
        yield "\n".join(progress_log), None, None, btn_disabled, btn_disabled
        selected_outline, selected_idx, outline_variant_count = generate_single_outline_candidate(
            client,
            topic,
            language=language,
            length="standard",
            focus="balanced",
            section_count=0,
            subsection_range="3-5",
            model=resolved_planning_model,
            variant_count=3,
        )
        append_trace_event(
            trace_path,
            "outline_variant_selected_finished",
            selected_index=selected_idx + 1,
            variant_count=outline_variant_count,
        )
        progress_log.append(_rt(ui_language, "selected_outline_variant", index=selected_idx + 1, count=outline_variant_count))
        progress_log.append(_rt(ui_language, "critiquing_outline"))
        append_trace_event(trace_path, "outline_critique_started")
        yield "\n".join(progress_log), None, None, btn_disabled, btn_disabled
        outline_critique = critique_outline(
            client,
            topic,
            selected_outline,
            language=language,
            focus="balanced",
            model=resolved_planning_model,
        )
        append_trace_event(trace_path, "outline_critique_finished")
        progress_log.append(_rt(ui_language, "outline_critique_completed"))
        progress_log.append(_rt(ui_language, "repairing_outline"))
        append_trace_event(trace_path, "outline_repair_started")
        yield "\n".join(progress_log), None, None, btn_disabled, btn_disabled
        repaired_outline = repair_outline(
            client,
            topic,
            selected_outline,
            outline_critique,
            language=language,
            focus="balanced",
            model=resolved_planning_model,
        )
        append_trace_event(trace_path, "outline_repair_finished", section_count=len(repaired_outline.get("sections", [])))

        planning_options = GenerationOptions(
            topic=topic,
            language=language,
            depth="undergraduate",
            focus="balanced",
            custom_prompt="",
            diversity_count=0,
            existing_context="",
            model=resolved_draft_model,
            planning_model=resolved_planning_model,
            concurrency=int(concurrency),
            cache_enabled=bool(cache_enabled),
        )

        progress_log.append(_rt(ui_language, "selecting_brief_variant"))
        append_trace_event(trace_path, "brief_variant_selected_started", variant_count=2)
        yield "\n".join(progress_log), None, None, btn_disabled, btn_disabled
        selected_plan, selected_brief_idx, brief_variant_count = generate_single_brief_candidate(
            client,
            topic,
            repaired_outline,
            planning_options,
            variant_count=2,
        )
        append_trace_event(
            trace_path,
            "brief_variant_selected_finished",
            selected_index=selected_brief_idx + 1,
            variant_count=brief_variant_count,
        )
        progress_log.append(_rt(ui_language, "selected_brief_variant", index=selected_brief_idx + 1, count=brief_variant_count))
        progress_log.append(_rt(ui_language, "critiquing_brief"))
        append_trace_event(trace_path, "brief_critique_started")
        yield "\n".join(progress_log), None, None, btn_disabled, btn_disabled
        brief_critique = critique_generation_plan(
            client,
            topic,
            selected_plan,
            model=resolved_planning_model,
        )
        append_trace_event(trace_path, "brief_critique_finished")
        progress_log.append(_rt(ui_language, "brief_critique_completed"))
        progress_log.append(_rt(ui_language, "repairing_brief"))
        append_trace_event(trace_path, "brief_repair_started")
        yield "\n".join(progress_log), None, None, btn_disabled, btn_disabled
        final_plan = repair_generation_plan(
            client,
            topic,
            selected_plan,
            brief_critique,
            model=resolved_planning_model,
        )
        append_trace_event(trace_path, "brief_repair_finished", section_count=len(final_plan.section_briefs))

        progress_log.append(_rt(ui_language, "frozen_final_outline"))
        progress_log.append(format_outline_preview(final_plan.outline))
        progress_log.append("-" * 50)
        progress_log.append(_rt(ui_language, "starting_generation_sections", count=len(final_plan.outline.get("sections", []))))

        draft_data = create_draft_record(
            topic=topic,
            outline=final_plan.outline,
            language=language,
            depth="undergraduate",
            custom_prompt="",
            diversity_count=0,
            concurrency=int(concurrency),
            cache_enabled=bool(cache_enabled),
            existing_context="",
            prepared_plan=generation_plan_to_payload(final_plan),
            template_profile=template_profile,
            draft_model=resolved_draft_model,
            planning_model=resolved_planning_model,
        )
        draft_data["trace_path"] = trace_path

        yield from stream_paper_generation(
            client,
            draft_data,
            topic=topic,
            outline=final_plan.outline,
            language=language,
            depth="undergraduate",
            custom_prompt="",
            diversity_count=0,
            model=resolved_draft_model,
            planning_model=resolved_planning_model,
            existing_context="",
            initial_lines=progress_log,
            ui_language=ui_language,
        )
    except Exception as exc:
        append_trace_event(trace_path, "quick_run_failed", error=str(exc))
        yield _rt(ui_language, "quick_generation_failed", error=exc, trace=trace_path), None, None, btn_enabled, btn_enabled


def easy_mode_generate_zh(
    topic_choice,
    custom_topic,
    api_key,
    base_url,
    draft_model,
    planning_model,
    concurrency,
    cache_enabled,
    ui_language,
):
    yield from easy_mode_generate(
        topic_choice,
        custom_topic,
        "zh",
        api_key,
        base_url,
        draft_model,
        planning_model,
        concurrency,
        cache_enabled,
        ui_language,
    )


def easy_mode_generate_en(
    topic_choice,
    custom_topic,
    api_key,
    base_url,
    draft_model,
    planning_model,
    concurrency,
    cache_enabled,
    ui_language,
):
    yield from easy_mode_generate(
        topic_choice,
        custom_topic,
        "en",
        api_key,
        base_url,
        draft_model,
        planning_model,
        concurrency,
        cache_enabled,
        ui_language,
    )


def step2_generate_paper(
    outline_json,
    topic_choice,
    custom_topic,
    depth,
    custom_prompt,
    enable_diversity,
    concurrency,
    cache_enabled,
    api_key,
    base_url,
    draft_model,
    planning_model,
    ui_language,
):
    btn_disabled, btn_enabled = _button_states()
    if not api_key:
        yield _rt(ui_language, "please_provide_api_key"), None, None, btn_enabled, btn_enabled
        return
    if not outline_json:
        yield _rt(ui_language, "generate_or_paste_outline"), None, None, btn_enabled, btn_enabled
        return

    try:
        outline = json.loads(outline_json)
    except json.JSONDecodeError:
        yield _rt(ui_language, "invalid_outline_json"), None, None, btn_enabled, btn_enabled
        return

    topic = outline.get("mathematician") or _topic_from_choice(topic_choice, custom_topic)
    language = _detect_language_from_outline(outline)
    existing_context = outline.pop("_pdf_context", "")
    client = OpenAI(api_key=api_key, base_url=base_url)
    resolved_draft_model, resolved_planning_model = _resolve_models(draft_model, planning_model)
    template_profile = sample_template_profile(language)

    draft_data = create_draft_record(
        topic=topic,
        outline=outline,
        language=language,
        depth=depth,
        custom_prompt=custom_prompt,
        diversity_count=int(enable_diversity),
        concurrency=int(concurrency),
        cache_enabled=bool(cache_enabled),
        existing_context=existing_context,
        template_profile=template_profile,
        draft_model=resolved_draft_model,
        planning_model=resolved_planning_model,
    )

    initial_lines = [
        _rt(ui_language, "starting_generation_sections", count=len(outline.get("sections", []))),
        "-" * 50,
    ]

    try:
        yield from stream_paper_generation(
            client,
            draft_data,
            topic=topic,
            outline=outline,
            language=language,
            depth=depth,
            custom_prompt=custom_prompt,
            diversity_count=int(enable_diversity),
            model=resolved_draft_model,
            planning_model=resolved_planning_model,
            existing_context=existing_context,
            initial_lines=initial_lines,
            ui_language=ui_language,
        )
    except Exception as exc:
        yield _rt(ui_language, "paper_generation_failed", error=exc), None, None, btn_enabled, btn_enabled


def save_api_auto(key, url, draft_mdl, planning_mdl, concurrency, cache_enabled, ui_language):
    prefs.update(
        {
            "api_key": key,
            "base_url": url,
            "draft_model": draft_mdl,
            "planning_model": planning_mdl,
            "concurrency": int(concurrency),
            "cache_enabled": bool(cache_enabled),
            "ui_language": ui_language,
        }
    )
    save_preferences(prefs)


def save_generation_prefs(language, length, depth, focus, diversity, concurrency, cache_enabled):
    prefs.update(
        {
            "language": language,
            "length": length,
            "depth": depth,
            "focus": focus,
            "diversity_count": int(diversity),
            "concurrency": int(concurrency),
            "cache_enabled": bool(cache_enabled),
        }
    )
    save_preferences(prefs)


def refresh_draft_list():
    info, choices = format_draft_list()
    if choices:
        return gr.update(value=info), gr.update(choices=choices, visible=True, value=choices[0][1])
    return gr.update(value=info), gr.update(choices=[], visible=False, value=None)


def delete_selected_draft(draft_id):
    if draft_id:
        delete_draft(draft_id)
    return refresh_draft_list()


def merge_pdfs_handler(files, page_ranges_text, ui_language):
    if not files:
        return _rt(ui_language, "please_upload_pdf_files"), None

    ranges = [line.strip() for line in page_ranges_text.strip().splitlines()] if page_ranges_text.strip() else []
    while len(ranges) < len(files):
        ranges.append("all")

    info_lines = [_rt(ui_language, "preparing_merge_job")]
    pdf_list = []
    for index, file in enumerate(files, start=1):
        page_count = get_pdf_page_count(file.name)
        page_range = ranges[index - 1]
        info_lines.append(f"{index}. {os.path.basename(file.name)} ({page_count} pages) -> {page_range}")
        pdf_list.append((file.name, page_range))

    yield "\n".join(info_lines + ["", _rt(ui_language, "merging_pdfs")]), None

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(config.OUTPUT_DIR, f"merged_{timestamp}.pdf")
    success, message = merge_pdfs(pdf_list, output_path)
    if success:
        yield _rt(ui_language, "saved_to", message=message, path=output_path), output_path
    else:
        yield _rt(ui_language, "merge_failed", message=message), None


initial_draft_info, initial_draft_choices = format_draft_list()


with gr.Blocks(title="MathHistoria") as app:
    gr.Markdown(f"# {_tr('app_title')}\n{_tr('app_subtitle')}")
    gr.Markdown(_tr("integrity_note"))

    with gr.Accordion(_tr("api_settings"), open=False):
        ui_language = gr.Dropdown(
            choices=[("中文", "zh"), ("English", "en")],
            value=prefs["ui_language"],
            label=_tr("ui_language"),
        )
        gr.Markdown(_tr("ui_language_hint"))
        api_key = gr.Textbox(label=_tr("api_key"), type="password", value=prefs["api_key"])
        base_url = gr.Textbox(label=_tr("base_url"), value=prefs["base_url"])
        draft_model = gr.Textbox(label=_tr("draft_model"), value=prefs["draft_model"])
        runtime_concurrency = gr.Slider(
            minimum=1,
            maximum=16,
            step=1,
            value=prefs["concurrency"],
            label=_tr("concurrency"),
        )
        planning_model = gr.Textbox(label=_tr("planning_model"), value=prefs["planning_model"])
        runtime_cache = gr.Checkbox(value=prefs["cache_enabled"], label=_tr("cache_enabled"))
        gr.Markdown(_tr("planning_fallback_hint"))

        for component in [api_key, base_url, draft_model, planning_model, runtime_concurrency, runtime_cache, ui_language]:
            component.change(
                save_api_auto,
                inputs=[api_key, base_url, draft_model, planning_model, runtime_concurrency, runtime_cache, ui_language],
                outputs=[],
            )

    with gr.Tabs():
        with gr.Tab(_tr("tab_quick")):
            gr.Markdown(_tr("quick_help"))

            with gr.Row():
                easy_topic = gr.Dropdown(choices=topic_choices, label=_tr("mathematician"), value=topic_choices[4])
                easy_custom = gr.Textbox(label=_tr("custom_topic"), placeholder=_tr("custom_topic_placeholder"))

            with gr.Row():
                easy_generate_btn_zh = gr.Button(_tr("generate_zh"), variant="primary", size="lg")
                easy_generate_btn_en = gr.Button(_tr("generate_en"), variant="primary", size="lg")

            easy_status = gr.Textbox(label=_tr("progress"), lines=8)
            easy_pdf = gr.File(label=_tr("pdf_output"))
            easy_latex = gr.File(label="LaTeX Source")

            easy_custom.change(
                lambda text: gr.update(value="Custom") if text.strip() else gr.update(),
                inputs=[easy_custom],
                outputs=[easy_topic],
            )
            easy_topic.change(
                lambda choice: gr.update(value="") if choice != "Custom" else gr.update(),
                inputs=[easy_topic],
                outputs=[easy_custom],
            )

            easy_generate_btn_zh.click(
                easy_mode_generate_zh,
                inputs=[
                    easy_topic,
                    easy_custom,
                    api_key,
                    base_url,
                    draft_model,
                    planning_model,
                    runtime_concurrency,
                    runtime_cache,
                    ui_language,
                ],
                outputs=[easy_status, easy_pdf, easy_latex, easy_generate_btn_zh, easy_generate_btn_en],
            )
            easy_generate_btn_en.click(
                easy_mode_generate_en,
                inputs=[
                    easy_topic,
                    easy_custom,
                    api_key,
                    base_url,
                    draft_model,
                    planning_model,
                    runtime_concurrency,
                    runtime_cache,
                    ui_language,
                ],
                outputs=[easy_status, easy_pdf, easy_latex, easy_generate_btn_zh, easy_generate_btn_en],
            )

        with gr.Tab(_tr("tab_custom"), visible=False):
            with gr.Accordion(_tr("resume_draft"), open=False):
                draft_info = gr.Markdown(initial_draft_info)
                draft_selector = gr.Radio(
                    choices=initial_draft_choices,
                    label=_tr("choose_draft"),
                    visible=bool(initial_draft_choices),
                    value=initial_draft_choices[0][1] if initial_draft_choices else None,
                )
                with gr.Row():
                    refresh_drafts_btn = gr.Button(_tr("refresh"), size="sm")
                    resume_draft_btn = gr.Button(_tr("resume"), variant="primary", size="sm")
                    delete_draft_btn = gr.Button(_tr("delete"), size="sm")
                resume_status = gr.Textbox(label=_tr("resume_progress"), lines=8, visible=False)
                resume_pdf = gr.File(label=_tr("resumed_pdf"), visible=False)
                resume_latex = gr.File(label="LaTeX Source", visible=False)

            gr.Markdown("---")

            with gr.Row():
                with gr.Column(scale=2):
                    topic_dropdown = gr.Dropdown(choices=topic_choices, label=_tr("mathematician"), value=topic_choices[4])
                    custom_topic_input = gr.Textbox(label=_tr("custom_topic"), placeholder=_tr("custom_topic_placeholder"))
                with gr.Column(scale=1):
                    language1 = gr.Radio(
                        choices=[("English", "en"), ("Chinese", "zh")],
                        value=prefs["language"],
                        label=_tr("paper_language"),
                    )
                    length1 = gr.Radio(
                        choices=[("Short (20-30 pages)", "short"), ("Standard (50-60 pages)", "standard"), ("Long (70-80 pages)", "long")],
                        value=prefs["length"],
                        label=_tr("target_length"),
                    )

            with gr.Row():
                depth1 = gr.Radio(
                    choices=[("Popular", "popular"), ("Undergraduate", "undergraduate"), ("Research", "research")],
                    value=prefs["depth"],
                    label=_tr("math_depth"),
                )
                focus1 = gr.Radio(
                    choices=[("Balanced", "balanced"), ("Biography-heavy", "biography"), ("Math-heavy", "mathematics")],
                    value=prefs["focus"],
                    label=_tr("focus"),
                )

            custom_prompt1 = gr.Textbox(
                label=_tr("extra_requirements"),
                placeholder=_tr("extra_requirements_placeholder_1"),
                lines=2,
            )

            enable_diversity1 = gr.Dropdown(
                choices=[("Off", 0), ("3 opening variants", 3), ("5 opening variants", 5)],
                value=prefs["diversity_count"],
                label=_tr("opening_diversity"),
            )

            with gr.Row():
                section_mode1 = gr.Radio(
                    choices=[("Random section count", "random"), ("Fixed section count", "fixed")],
                    value="random",
                    label=_tr("section_mode"),
                )
                section_count1 = gr.Number(label=_tr("fixed_section_count"), value=12, minimum=5, maximum=20, step=1)

            subsection_mode1 = gr.Radio(
                choices=[("3-5 subsections", "3-5"), ("3-4 subsections", "3-4")],
                value="3-5",
                label=_tr("subsections_per_section"),
            )

            generate_outline_btn = gr.Button(_tr("generate_outline"), variant="primary", size="lg")
            status_output1 = gr.Textbox(label=_tr("status"), lines=3)
            outline_preview1 = gr.Markdown(label=_tr("outline_preview"))
            outlines_storage1 = gr.Textbox(label=_tr("all_outlines_hidden"), visible=False)
            outline_selector1 = gr.Radio(
                choices=[("Candidate 1", "0"), ("Candidate 2", "1"), ("Candidate 3", "2")],
                value="0",
                label=_tr("selected_outline"),
                visible=False,
            )
            outline_json1 = gr.Textbox(label=_tr("editable_outline_json"), lines=15)
            confirm_btn1 = gr.Button(_tr("generate_paper_from_outline"), variant="primary", size="lg", visible=False)
            status_output1_final = gr.Textbox(label=_tr("generation_progress"), lines=8)
            pdf_output1 = gr.File(label=_tr("pdf_output"))
            latex_output1 = gr.File(label="LaTeX Source")

            custom_topic_input.change(
                lambda text: gr.update(value="Custom") if text.strip() else gr.update(),
                inputs=[custom_topic_input],
                outputs=[topic_dropdown],
            )
            topic_dropdown.change(
                lambda choice: gr.update(value="") if choice != "Custom" else gr.update(),
                inputs=[topic_dropdown],
                outputs=[custom_topic_input],
            )

            for component in [
                language1,
                length1,
                depth1,
                focus1,
                enable_diversity1,
                runtime_concurrency,
                runtime_cache,
            ]:
                component.change(
                    save_generation_prefs,
                    inputs=[language1, length1, depth1, focus1, enable_diversity1, runtime_concurrency, runtime_cache],
                    outputs=[],
                )

            refresh_drafts_btn.click(refresh_draft_list, outputs=[draft_info, draft_selector])
            resume_draft_btn.click(
                lambda draft_id, key, url, draft_mdl, planning_mdl, ui_lang: resume_from_draft(
                    draft_id,
                    key,
                    url,
                    draft_mdl,
                    planning_mdl,
                    ui_lang,
                )
                if draft_id
                else (_rt(ui_lang, "please_choose_draft"), None, gr.update(interactive=True), gr.update(interactive=True)),
                inputs=[draft_selector, api_key, base_url, draft_model, planning_model, ui_language],
                outputs=[resume_status, resume_pdf, resume_latex, resume_draft_btn, delete_draft_btn],
            ).then(
                lambda: (gr.update(visible=True), gr.update(visible=True)),
                outputs=[resume_status, resume_pdf, resume_latex],
            )
            delete_draft_btn.click(delete_selected_draft, inputs=[draft_selector], outputs=[draft_info, draft_selector])

            generate_outline_btn.click(
                step1_generate_outline,
                inputs=[
                    topic_dropdown,
                    custom_topic_input,
                    language1,
                    length1,
                    focus1,
                    section_mode1,
                    section_count1,
                    subsection_mode1,
                    api_key,
                    base_url,
                    draft_model,
                    planning_model,
                    ui_language,
                ],
                outputs=[status_output1, outline_preview1, outlines_storage1, outline_json1, outline_selector1],
            ).then(
                lambda: gr.update(visible=True),
                outputs=[outline_selector1],
            ).then(
                lambda: gr.update(visible=True),
                outputs=[confirm_btn1],
            )

            outline_selector1.change(
                select_outline,
                inputs=[outlines_storage1, outline_selector1],
                outputs=[outline_json1],
            )

            confirm_btn1.click(
                step2_generate_paper,
                inputs=[
                    outline_json1,
                    topic_dropdown,
                    custom_topic_input,
                    depth1,
                    custom_prompt1,
                    enable_diversity1,
                    runtime_concurrency,
                    runtime_cache,
                    api_key,
                    base_url,
                    draft_model,
                    planning_model,
                    ui_language,
                ],
                outputs=[status_output1_final, pdf_output1, latex_output1, confirm_btn1, generate_outline_btn],
            )

        with gr.Tab(_tr("tab_continue_pdf"), visible=False):
            with gr.Row():
                with gr.Column(scale=2):
                    pdf_input = gr.File(label=_tr("existing_pdf"), file_types=[".pdf"])
                with gr.Column(scale=1):
                    language2 = gr.Radio(
                        choices=[("English", "en"), ("Chinese", "zh")],
                        value=prefs["language"],
                        label=_tr("paper_language"),
                    )
                    length2 = gr.Radio(
                        choices=[("Short (20-30 pages)", "short"), ("Standard (50-60 pages)", "standard"), ("Long (70-80 pages)", "long")],
                        value=prefs["length"],
                        label=_tr("target_length"),
                    )

            with gr.Row():
                depth2 = gr.Radio(
                    choices=[("Popular", "popular"), ("Undergraduate", "undergraduate"), ("Research", "research")],
                    value=prefs["depth"],
                    label=_tr("math_depth"),
                )
                focus2 = gr.Radio(
                    choices=[("Balanced", "balanced"), ("Biography-heavy", "biography"), ("Math-heavy", "mathematics")],
                    value=prefs["focus"],
                    label=_tr("focus"),
                )

            custom_prompt2 = gr.Textbox(
                label=_tr("extra_requirements"),
                placeholder=_tr("extra_requirements_placeholder_2"),
                lines=2,
            )
            enable_diversity2 = gr.Dropdown(
                choices=[("Off", 0), ("3 opening variants", 3), ("5 opening variants", 5)],
                value=prefs["diversity_count"],
                label=_tr("opening_diversity"),
            )

            generate_outline_btn2 = gr.Button(_tr("generate_expanded_outline"), variant="primary", size="lg")
            status_output2 = gr.Textbox(label=_tr("status"), lines=3)
            outline_preview2 = gr.Markdown(label=_tr("outline_preview"))
            outlines_storage2 = gr.Textbox(label=_tr("all_outlines_hidden"), visible=False)
            outline_selector2 = gr.Radio(
                choices=[("Candidate 1", "0"), ("Candidate 2", "1"), ("Candidate 3", "2")],
                value="0",
                label=_tr("selected_outline"),
                visible=False,
            )
            outline_json2 = gr.Textbox(label=_tr("editable_outline_json"), lines=15)
            placeholder_topic2 = gr.Textbox(visible=False, value="")
            placeholder_custom2 = gr.Textbox(visible=False, value="")
            confirm_btn2 = gr.Button(_tr("generate_paper_from_pdf_outline"), variant="primary", size="lg", visible=False)
            status_output2_final = gr.Textbox(label=_tr("generation_progress"), lines=8)
            pdf_output2 = gr.File(label=_tr("pdf_output"))
            latex_output2 = gr.File(label="LaTeX Source")

            generate_outline_btn2.click(
                step1_generate_outline_from_pdf,
                inputs=[pdf_input, language2, length2, focus2, api_key, base_url, draft_model, planning_model, ui_language],
                outputs=[status_output2, outline_preview2, outlines_storage2, outline_json2, outline_selector2],
            ).then(
                lambda: gr.update(visible=True),
                outputs=[outline_selector2],
            ).then(
                lambda: gr.update(visible=True),
                outputs=[confirm_btn2],
            )

            outline_selector2.change(
                select_outline,
                inputs=[outlines_storage2, outline_selector2],
                outputs=[outline_json2],
            )

            confirm_btn2.click(
                step2_generate_paper,
                inputs=[
                    outline_json2,
                    placeholder_topic2,
                    placeholder_custom2,
                    depth2,
                    custom_prompt2,
                    enable_diversity2,
                    runtime_concurrency,
                    runtime_cache,
                    api_key,
                    base_url,
                    draft_model,
                    planning_model,
                    ui_language,
                ],
                outputs=[status_output2_final, pdf_output2, latex_output2, confirm_btn2, generate_outline_btn2],
            )

        with gr.Tab(_tr("tab_merge")):
            gr.Markdown(_tr("merge_help"))

            pdf_files_input = gr.File(label=_tr("pdf_files"), file_count="multiple", file_types=[".pdf"])
            page_ranges_input = gr.Textbox(
                label=_tr("page_ranges"),
                placeholder=_tr("page_ranges_placeholder"),
                lines=5,
            )
            merge_btn = gr.Button(_tr("merge_pdfs"), variant="primary", size="lg")
            merge_status = gr.Textbox(label=_tr("status"), lines=5)
            merged_pdf_output = gr.File(label=_tr("pdf_output"))

            merge_btn.click(
                merge_pdfs_handler,
                inputs=[pdf_files_input, page_ranges_input, ui_language],
                outputs=[merge_status, merged_pdf_output],
            )

    gr.Markdown(_tr("footer_notes"))


if __name__ == "__main__":
    app.launch(share=False, inbrowser=True, theme=gr.themes.Soft())

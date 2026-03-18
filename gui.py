import json
import os
import random
import sys
import time


def _ensure_standard_streams() -> None:
    """PyInstaller windowed executables may start with stdout/stderr set to None."""
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")


_ensure_standard_streams()

import gradio as gr
from openai import OpenAI

import config
from agents.compiler import find_latex_engine
from agents.generator import build_template_profile, sample_template_profile
from agents.outline import generate_outline, generate_outline_from_pdf
from agents.pdf_reader import analyze_pdf, extract_text_from_pdf
from agents.pdf_tools import get_pdf_page_count, merge_pdfs
from agents.suggester import get_suggestions
from app.session import stream_paper_generation
from app.state import (
    create_draft_record,
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
CUSTOM_TOPIC_CHOICE = "自定义"
topic_choices = [f"{item['name']} - {item['years']}" for item in suggestions] + [CUSTOM_TOPIC_CHOICE]
default_topic_choice = topic_choices[4] if len(topic_choices) > 4 else topic_choices[0]

TEXT = {
    "app_title": "MathHistoria",
    "app_subtitle": "AI 驱动的数学史论文生成器",
    "integrity_note": "学术诚信提醒：生成内容仅用于学习、整理和写作辅助，请自行核对史实与参考文献，不要直接提交未经核验的模型输出。",
    "api_settings": "API 设置",
    "api_guide": (
        "新手建议：\n"
        "1. 先准备一个可用的 API Key，并填在下面的 API Key 输入框里。\n"
        "2. 默认地址已经是 Gemini 官方 OpenAI 兼容接口；如果你使用别的中转服务，再修改 Base URL。\n"
        "3. 如果你暂时没有 key，可以自行寻找可用渠道；有用户会去淘宝搜索 API Key，先买少量额度测试，例如 1 美元左右的 Gemini 额度。\n"
        "4. 第三方 key 可能存在稳定性、限额和隐私风险，请自行甄别。"
    ),
    "api_key": "API Key",
    "base_url": "Base URL",
    "draft_model": "正文模型",
    "planning_model": "规划模型（可选）",
    "concurrency": "最大同时章节任务数",
    "planning_fallback_hint": "如果“规划模型”留空，将自动回退为“正文模型”。并发数只影响正文生成阶段。",
    "latex_ready": "已检测到 LaTeX 环境：生成结束后会尝试输出 PDF 和 .tex。",
    "latex_missing": "未检测到 LaTeX 环境：生成结束后将提供 .tex 下载；如本机装有 LaTeX，才会额外输出 PDF。",
    "latex_setup_guide": (
        "如果你想让本机直接输出 PDF：\n"
        "- Windows 可安装 [MiKTeX](https://miktex.org/howto/install-miktex)；官方建议优先用私有安装，且可按需自动安装缺失宏包。\n"
        "- 也可以安装 [TeX Live](https://www.tug.org/texlive/)。\n"
        "- 如果你暂时不想折腾本地 LaTeX，可以把生成的 `.tex` 上传到 [Overleaf](https://www.overleaf.com/) 在线编译。"
    ),
    "english_recommendation": "强烈建议优先使用英文生成。当前英文模式通常更稳定，结构更自然，数学术语和长文展开效果也更好。",
    "tab_quick": "省心生成",
    "tab_custom": "自定义生成",
    "tab_continue_pdf": "从 PDF 续写",
    "tab_merge": "合并 PDF",
    "quick_help": "使用默认流程，一次完成大纲、规划、正文生成和 PDF 编译。",
    "advanced_settings": "高级设置",
    "layout_settings": "版式设置",
    "advanced_options": "高级选项（可选）",
    "mathematician": "数学家",
    "custom_topic": "自定义主题",
    "custom_topic_placeholder": "例如：Emmy Noether",
    "auto_option": "自动",
    "chinese_option": "中文",
    "english_option": "英文",
    "short_option": "短篇",
    "standard_option": "标准",
    "long_option": "长篇",
    "popular_option": "通俗",
    "undergraduate_option": "本科",
    "research_option": "研究",
    "balanced_option": "均衡",
    "biography_option": "偏生平",
    "mathematics_option": "偏数学",
    "structure_control": "结构控制",
    "more_stable": "更稳定",
    "more_free": "更自由",
    "chapter_count": "章节数",
    "layout_mode": "版式模式",
    "layout_random": "整套随机",
    "layout_manual": "手动指定",
    "template_style": "模板样式",
    "font_scheme": "字体方案",
    "spacing_mode": "版面疏密",
    "classic_style": "经典学术",
    "bookish_style": "书卷型 Essay",
    "archival_style": "档案型 Profile",
    "times_font": "经典衬线（Times）",
    "palatino_font": "现代衬线（Palatino）",
    "default_latex_font": "默认 LaTeX",
    "compact_spacing": "紧凑",
    "relaxed_spacing": "舒展",
    "start_generation": "开始生成",
    "suggested_title": "标题建议",
    "suggested_title_placeholder": "例如：黎曼：从几何到数论的革命",
    "additional_requirements": "额外要求",
    "additional_requirements_placeholder": "例如：更强调与高斯的关系",
    "custom_title_placeholder": "例如：冯·诺伊曼：跨越逻辑、计算与现代科学",
    "custom_requirements_placeholder": "例如：加强与哥德尔、图灵、博弈论的关系脉络",
    "generate_zh": "生成中文论文",
    "generate_en": "生成英文论文",
    "progress": "进度",
    "pdf_output": "PDF 输出",
    "latex_output": "LaTeX 源文件",
    "custom_progress": "生成进度",
    "resume_draft": "恢复草稿",
    "choose_draft": "选择草稿",
    "refresh": "刷新",
    "resume": "继续生成",
    "delete": "删除",
    "resume_progress": "恢复进度",
    "resumed_pdf": "恢复后的 PDF",
    "paper_language": "论文语言",
    "target_length": "目标篇幅",
    "math_depth": "数学深度",
    "focus": "侧重点",
    "extra_requirements": "额外要求",
    "extra_requirements_placeholder_1": "例如：更强调黎曼猜想的发展脉络。",
    "extra_requirements_placeholder_2": "例如：增加与同时代数学家的比较。",
    "opening_diversity": "开头多样性",
    "section_mode": "章节模式",
    "fixed_section_count": "固定章节数",
    "subsections_per_section": "每章小节数量",
    "generate_outline": "生成大纲",
    "status": "状态",
    "outline_preview": "大纲预览",
    "all_outlines_hidden": "全部候选大纲（隐藏）",
    "selected_outline": "当前选择的大纲",
    "editable_outline_json": "可编辑的大纲 JSON",
    "generate_paper_from_outline": "根据大纲生成论文",
    "generation_progress": "生成进度",
    "existing_pdf": "已有 PDF",
    "generate_expanded_outline": "生成扩展大纲",
    "generate_paper_from_pdf_outline": "根据 PDF 大纲生成论文",
    "merge_help": "上传多个 PDF 文件，并按上传顺序填写要合并的页码范围。\n\n页码范围示例：\n- `1-5`\n- `1,3,5`\n- `1-5,8-10`\n- `all` 或留空表示整份文件",
    "pdf_files": "PDF 文件",
    "page_ranges": "页码范围（每个文件一行，顺序与上传顺序一致）",
    "page_ranges_placeholder": "all\n1-5\n3,7-10",
    "merge_pdfs": "合并 PDF",
    "footer_notes": "---\n- API 设置会保存接口地址、正文模型、规划模型和并发数偏好。\n- 自定义生成会在开始前接收你的内容与版式约束，然后直接走完整生成流程。\n- 生成时间取决于章节数量和模型速度。",
    "please_provide_api_key": "请先填写 API Key。",
    "please_upload_pdf": "请先上传 PDF。",
    "extracting_pdf": "正在提取上传 PDF 的文本……",
    "could_not_extract_pdf": "无法从该 PDF 中提取文本。",
    "analyzing_pdf": "正在分析上传的 PDF（共 {pages} 页）……",
    "generating_outline_candidate": "正在生成大纲候选 {index}/3……",
    "generated_outline_candidates": "已生成 3 份大纲候选，默认随机选中第 {index} 份，你也可以手动切换。",
    "outline_generation_failed": "大纲生成失败：{error}",
    "generating_expanded_outline_candidate": "正在生成扩展大纲候选 {index}/3……",
    "detected_mathematician": "识别出的数学家：{name}。已生成 3 份扩展大纲，默认选中第 {index} 份。",
    "pdf_outline_generation_failed": "PDF 大纲生成失败：{error}",
    "selecting_outline_variant": "正在随机选择一个大纲提示词变体并生成大纲……",
    "selected_outline_variant": "已选择第 {index}/{count} 个大纲提示词变体。",
    "critiquing_outline": "正在审阅大纲……",
    "outline_critique_completed": "大纲审阅完成。",
    "repairing_outline": "正在修订大纲……",
    "selecting_brief_variant": "正在随机选择一个 brief 提示词变体并生成规划……",
    "selected_brief_variant": "已选择第 {index}/{count} 个 brief 提示词变体。",
    "critiquing_brief": "正在审阅规划……",
    "brief_critique_completed": "规划审阅完成。",
    "repairing_brief": "正在修订规划……",
    "frozen_final_outline": "最终冻结的大纲：",
    "starting_generation_sections": "开始生成正文，共 {count} 个章节。",
    "quick_generation_failed": "省心生成失败：{error}\n追踪日志：{trace}",
    "generate_or_paste_outline": "请先生成或粘贴大纲。",
    "invalid_outline_json": "大纲 JSON 无效。",
    "paper_generation_failed": "论文生成失败：{error}",
    "please_choose_draft": "请选择一个草稿。",
    "please_upload_pdf_files": "请至少上传一个 PDF 文件。",
    "preparing_merge_job": "正在准备合并任务：",
    "merging_pdfs": "正在合并 PDF……",
    "saved_to": "{message}\n已保存到：{path}",
    "merge_failed": "合并失败：{message}",
}


def _tr(key: str, **kwargs) -> str:
    return TEXT[key].format(**kwargs)


def _rt(lang: str, key: str, **kwargs) -> str:
    return TEXT[key].format(**kwargs)


def _latex_runtime_notice() -> str:
    return _tr("latex_ready") if find_latex_engine() else _tr("latex_missing")


def _button_states():
    return gr.update(interactive=False), gr.update(interactive=True)


def _topic_from_choice(topic_choice: str, custom_topic: str) -> str:
    if topic_choice == CUSTOM_TOPIC_CHOICE:
        return custom_topic.strip() if custom_topic.strip() else "Bernhard Riemann"
    return topic_choice.split(" - ")[0]


def _detect_language_from_outline(outline: dict) -> str:
    title = outline.get("title", "")
    return "zh" if any("\u4e00" <= ch <= "\u9fff" for ch in title) else "en"


def _resolve_models(draft_model: str, planning_model: str | None) -> tuple[str, str]:
    resolved_draft = (draft_model or "").strip() or config.MODEL
    resolved_planning = (planning_model or "").strip() or resolved_draft
    return resolved_draft, resolved_planning


_LENS_GUIDANCE = {
    "life_arc": "Use a life-arc lens, but avoid turning the paper into a cradle-to-legacy checklist. Keep clear selectivity and emphasis.",
    "idea_arc": "Use an idea-arc lens. Organize around the development of a few central mathematical ideas rather than trying to narrate the entire life evenly.",
    "problem_arc": "Use a problem-centered lens. Let one or two mathematical problems anchor the paper, with biography included only where it sharpens the argument.",
    "network_arc": "Use a network lens. Emphasize correspondences, collaborators, rivals, institutions, and influence chains rather than a full life survey.",
    "period_arc": "Use a period lens. Give priority to one especially decisive phase and let other phases remain lighter if that produces a stronger paper.",
}


def _pick_internal_lens(focus: str, structure_control: str) -> str:
    if focus == "biography":
        return _weighted_choice({"life_arc": 4, "network_arc": 2, "period_arc": 2})
    if focus == "mathematics":
        return _weighted_choice({"idea_arc": 4, "problem_arc": 3, "period_arc": 1})
    if structure_control == "more_free":
        return _weighted_choice({"idea_arc": 2, "problem_arc": 2, "network_arc": 2, "period_arc": 2, "life_arc": 1})
    return _weighted_choice({"life_arc": 2, "idea_arc": 2, "network_arc": 1, "period_arc": 1, "problem_arc": 1})


def _weighted_choice(options: dict[str, int]) -> str:
    population = list(options.keys())
    weights = list(options.values())
    return random.choices(population, weights=weights, k=1)[0]


def _resolve_auto_setting(value: str, default_weights: dict[str, int]) -> str:
    if value != "auto":
        return value
    return _weighted_choice(default_weights)


def _combine_requirements(*parts: str) -> str:
    normalized = [part.strip() for part in parts if part and part.strip()]
    return "\n\n".join(normalized)


def _resolve_guided_settings(
    *,
    length: str,
    depth: str,
    focus: str,
    structure_control: str,
    section_mode: str,
    fixed_section_count: int | float | None,
    custom_requirements: str,
) -> dict:
    resolved_length = _resolve_auto_setting(length, {"standard": 4, "long": 1, "short": 1})
    resolved_depth = _resolve_auto_setting(depth, {"undergraduate": 4, "popular": 1, "research": 1})
    resolved_focus = _resolve_auto_setting(focus, {"balanced": 4, "biography": 1, "mathematics": 1})
    resolved_structure = _resolve_auto_setting(structure_control, {"more_stable": 3, "more_free": 1})

    section_count = 0
    if section_mode == "fixed" and fixed_section_count:
        section_count = int(fixed_section_count)

    subsection_range = "3-4" if resolved_structure == "more_stable" else "3-5"
    structure_hint = ""
    if resolved_structure == "more_stable":
        structure_hint = "Prefer a stable, conventionally structured paper. Keep chapter progression even and avoid abrupt jumps in scope."
    elif resolved_structure == "more_free":
        structure_hint = "Allow a slightly more flexible structure and livelier section titles, while remaining academically grounded."

    internal_lens = _pick_internal_lens(resolved_focus, resolved_structure)
    lens_hint = _LENS_GUIDANCE[internal_lens]
    asymmetry_hint = (
        "Allow uneven chapter density. Some sections may be broader, others narrower; do not force every chapter into the same narrative weight or subsection count."
    )
    planning_requirements = _combine_requirements(custom_requirements, structure_hint, lens_hint, asymmetry_hint)
    return {
        "length": resolved_length,
        "depth": resolved_depth,
        "focus": resolved_focus,
        "structure_control": resolved_structure,
        "lens": internal_lens,
        "section_count": section_count,
        "subsection_range": subsection_range,
        "planning_requirements": planning_requirements,
    }


def _build_guided_template_profile(
    language: str,
    *,
    layout_mode: str,
    template_style: str,
    font_scheme: str,
    spacing_mode: str,
) -> dict:
    effective_layout = layout_mode if layout_mode in {"auto", "random", "manual"} else "auto"
    effective_style = template_style if template_style in {"classic", "bookish", "archival"} else "auto"
    effective_font = font_scheme if language == "en" else "auto"
    effective_spacing = spacing_mode if spacing_mode in {"auto", "compact", "standard", "relaxed"} else "auto"
    return build_template_profile(
        language,
        layout_mode=effective_layout,
        style=effective_style,
        font_scheme=effective_font,
        spacing_mode=effective_spacing,
    )


def _set_topic_choice_from_custom(text: str):
    return gr.update(value=CUSTOM_TOPIC_CHOICE) if (text or "").strip() else gr.update()


def _clear_custom_topic_if_preset(choice: str):
    return gr.update(value="") if choice != CUSTOM_TOPIC_CHOICE else gr.update()


def _toggle_fixed_section_count(mode: str):
    return gr.update(visible=mode == "fixed")


def _toggle_manual_layout_controls(mode: str):
    visible = mode == "manual"
    return gr.update(visible=visible), gr.update(visible=visible), gr.update(visible=visible)


def format_outline_preview(outline: dict) -> str:
    sections = outline.get("sections", [])
    lines = [
        f"# {outline.get('title', '未命名大纲')}",
        "",
        f"- 数学家：{outline.get('mathematician', '未知')}",
        f"- 生卒年：{outline.get('birth_year', '?')} - {outline.get('death_year', '?')}",
        f"- 国籍：{outline.get('nationality', '未知')}",
    ]

    abstract = outline.get("abstract", "").strip()
    if abstract:
        lines.extend(["", "## 摘要", abstract])

    keywords = outline.get("keywords", [])
    if keywords:
        lines.extend(["", f"- 关键词：{', '.join(keywords)}"])

    lines.extend(["", "## 章节"])
    for index, section in enumerate(sections, start=1):
        lines.append(f"### {index}. {section.get('title', '未命名章节')}")
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
        blocks.append(f"## 候选大纲 {idx}\n{format_outline_preview(outline)}")
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


def _run_guided_generation(
    *,
    run_prefix: str,
    run_label: str,
    topic_choice,
    custom_topic,
    suggested_title,
    custom_requirements,
    language,
    length,
    depth,
    focus,
    structure_control,
    section_mode,
    fixed_section_count,
    layout_mode,
    template_style,
    font_scheme,
    spacing_mode,
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
    resolved = _resolve_guided_settings(
        length=length,
        depth=depth,
        focus=focus,
        structure_control=structure_control,
        section_mode=section_mode,
        fixed_section_count=fixed_section_count,
        custom_requirements=custom_requirements or "",
    )
    template_profile = _build_guided_template_profile(
        language,
        layout_mode=layout_mode,
        template_style=template_style,
        font_scheme=font_scheme,
        spacing_mode=spacing_mode,
    )

    trace_path = build_trace_path(f"{run_prefix}_{int(time.time())}_{safe_filename(topic)}")
    progress_log = [f"追踪日志：{trace_path}"]
    append_trace_event(
        trace_path,
        f"{run_prefix}_run_started",
        topic=topic,
        language=language,
        length=resolved["length"],
        depth=resolved["depth"],
        focus=resolved["focus"],
        structure_control=resolved["structure_control"],
        lens=resolved["lens"],
        section_count=resolved["section_count"],
        draft_model=resolved_draft_model,
        planning_model=resolved_planning_model,
        concurrency=int(concurrency),
        cache_enabled=bool(cache_enabled),
        template_family=template_profile.get("family"),
        template_layout_mode=layout_mode,
        font_scheme=template_profile.get("font_scheme"),
        spacing_mode=template_profile.get("spacing_mode"),
    )

    try:
        progress_log.append(_rt(ui_language, "selecting_outline_variant"))
        append_trace_event(trace_path, "outline_variant_selected_started", variant_count=3)
        yield "\n".join(progress_log), None, None, btn_disabled, btn_disabled

        selected_outline, selected_idx, outline_variant_count = generate_single_outline_candidate(
            client,
            topic,
            language=language,
            length=resolved["length"],
            focus=resolved["focus"],
            section_count=resolved["section_count"],
            subsection_range=resolved["subsection_range"],
            model=resolved_planning_model,
            variant_count=3,
            custom_requirements=resolved["planning_requirements"],
            suggested_title=suggested_title or "",
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
            focus=resolved["focus"],
            model=resolved_planning_model,
            custom_requirements=resolved["planning_requirements"],
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
            focus=resolved["focus"],
            model=resolved_planning_model,
            custom_requirements=resolved["planning_requirements"],
            suggested_title=suggested_title or "",
        )
        append_trace_event(trace_path, "outline_repair_finished", section_count=len(repaired_outline.get("sections", [])))

        planning_options = GenerationOptions(
            topic=topic,
            language=language,
            depth=resolved["depth"],
            focus=resolved["focus"],
            custom_prompt=resolved["planning_requirements"],
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
            depth=resolved["depth"],
            custom_prompt=resolved["planning_requirements"],
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
            depth=resolved["depth"],
            focus=resolved["focus"],
            custom_prompt=resolved["planning_requirements"],
            diversity_count=0,
            model=resolved_draft_model,
            planning_model=resolved_planning_model,
            existing_context="",
            initial_lines=progress_log,
            ui_language=ui_language,
        )
    except Exception as exc:
        append_trace_event(trace_path, f"{run_prefix}_run_failed", error=str(exc))
        yield f"{run_label}失败：{exc}\n追踪日志：{trace_path}", None, None, btn_enabled, btn_enabled


def easy_mode_generate(
    topic_choice,
    custom_topic,
    suggested_title,
    custom_requirements,
    language,
    api_key,
    base_url,
    draft_model,
    planning_model,
    concurrency,
    cache_enabled,
    ui_language,
):
    yield from _run_guided_generation(
        run_prefix="quick",
        run_label="省心生成",
        topic_choice=topic_choice,
        custom_topic=custom_topic,
        suggested_title=suggested_title,
        custom_requirements=custom_requirements,
        language=language,
        length="standard",
        depth="undergraduate",
        focus="balanced",
        structure_control="auto",
        section_mode="auto",
        fixed_section_count=0,
        layout_mode="random",
        template_style="auto",
        font_scheme="auto",
        spacing_mode="auto",
        api_key=api_key,
        base_url=base_url,
        draft_model=draft_model,
        planning_model=planning_model,
        concurrency=concurrency,
        cache_enabled=cache_enabled,
        ui_language=ui_language,
    )


def easy_mode_generate_zh(
    topic_choice,
    custom_topic,
    suggested_title,
    custom_requirements,
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
        suggested_title,
        custom_requirements,
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
    suggested_title,
    custom_requirements,
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
        suggested_title,
        custom_requirements,
        "en",
        api_key,
        base_url,
        draft_model,
        planning_model,
        concurrency,
        cache_enabled,
        ui_language,
    )


def custom_mode_generate(
    topic_choice,
    custom_topic,
    language,
    length,
    depth,
    focus,
    structure_control,
    section_mode,
    fixed_section_count,
    suggested_title,
    custom_requirements,
    layout_mode,
    template_style,
    font_scheme,
    spacing_mode,
    api_key,
    base_url,
    draft_model,
    planning_model,
    concurrency,
    cache_enabled,
    ui_language,
):
    yield from _run_guided_generation(
        run_prefix="custom",
        run_label="自定义生成",
        topic_choice=topic_choice,
        custom_topic=custom_topic,
        suggested_title=suggested_title,
        custom_requirements=custom_requirements,
        language=language,
        length=length,
        depth=depth,
        focus=focus,
        structure_control=structure_control,
        section_mode=section_mode,
        fixed_section_count=fixed_section_count,
        layout_mode=layout_mode,
        template_style=template_style,
        font_scheme=font_scheme,
        spacing_mode=spacing_mode,
        api_key=api_key,
        base_url=base_url,
        draft_model=draft_model,
        planning_model=planning_model,
        concurrency=concurrency,
        cache_enabled=cache_enabled,
        ui_language=ui_language,
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
            focus="balanced",
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


def save_api_auto(key, url, draft_mdl, planning_mdl, concurrency, ui_language):
    prefs.update(
        {
            "api_key": key,
            "base_url": url,
            "draft_model": draft_mdl,
            "planning_model": planning_mdl,
            "concurrency": int(concurrency),
            "ui_language": ui_language,
        }
    )
    save_preferences(prefs)


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


with gr.Blocks(title="MathHistoria") as app:
    gr.Markdown(f"# {_tr('app_title')}\n{_tr('app_subtitle')}")
    gr.Markdown(_tr("integrity_note"))

    with gr.Accordion(_tr("api_settings"), open=False):
        ui_language = gr.State("zh")
        runtime_cache = gr.State(False)
        gr.Markdown(_tr("api_guide"))
        gr.Markdown(f"> {_latex_runtime_notice()}")
        gr.Markdown(_tr("latex_setup_guide"))
        api_key = gr.Textbox(
            label=_tr("api_key"),
            type="password",
            value=prefs["api_key"],
            placeholder="填写你的 Gemini API Key",
        )
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
        gr.Markdown(_tr("planning_fallback_hint"))

        for component in [api_key, base_url, draft_model, planning_model, runtime_concurrency]:
            component.change(
                save_api_auto,
                inputs=[api_key, base_url, draft_model, planning_model, runtime_concurrency, ui_language],
                outputs=[],
            )


    with gr.Tabs():
        with gr.Tab(_tr("tab_quick")):
            gr.Markdown(_tr("quick_help"))
            gr.Markdown(f"> {_tr('english_recommendation')}")

            with gr.Row():
                easy_topic = gr.Dropdown(choices=topic_choices, label=_tr("mathematician"), value=default_topic_choice)
                easy_custom = gr.Textbox(label=_tr("custom_topic"), placeholder=_tr("custom_topic_placeholder"))

            with gr.Accordion(_tr("advanced_options"), open=False):
                easy_suggested_title = gr.Textbox(
                    label=_tr("suggested_title"),
                    placeholder=_tr("suggested_title_placeholder"),
                    lines=1,
                )
                easy_custom_requirements = gr.Textbox(
                    label=_tr("additional_requirements"),
                    placeholder=_tr("additional_requirements_placeholder"),
                    lines=2,
                )

            with gr.Row():
                easy_generate_btn_zh = gr.Button(_tr("generate_zh"), variant="primary", size="lg")
                easy_generate_btn_en = gr.Button(_tr("generate_en"), variant="primary", size="lg")

            easy_status = gr.Textbox(label=_tr("progress"), lines=8)
            easy_pdf = gr.File(label=_tr("pdf_output"))
            easy_latex = gr.File(label=_tr("latex_output"))

            easy_custom.change(_set_topic_choice_from_custom, inputs=[easy_custom], outputs=[easy_topic])
            easy_topic.change(_clear_custom_topic_if_preset, inputs=[easy_topic], outputs=[easy_custom])

            easy_generate_btn_zh.click(
                easy_mode_generate_zh,
                inputs=[
                    easy_topic,
                    easy_custom,
                    easy_suggested_title,
                    easy_custom_requirements,
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
                    easy_suggested_title,
                    easy_custom_requirements,
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

        with gr.Tab(_tr("tab_custom")):
            gr.Markdown(f"> {_tr('english_recommendation')}")
            with gr.Row():
                with gr.Column(scale=2):
                    topic_dropdown = gr.Dropdown(choices=topic_choices, label=_tr("mathematician"), value=default_topic_choice)
                    custom_topic_input = gr.Textbox(label=_tr("custom_topic"), placeholder=_tr("custom_topic_placeholder"))
                    language1 = gr.Radio(
                        choices=[(_tr("chinese_option"), "zh"), (_tr("english_option"), "en")],
                        value=prefs["language"] if prefs["language"] in {"zh", "en"} else "zh",
                        label=_tr("paper_language"),
                    )
                with gr.Column(scale=2):
                    length1 = gr.Radio(
                        choices=[(_tr("short_option"), "short"), (_tr("standard_option"), "standard"), (_tr("long_option"), "long")],
                        value="standard",
                        label=_tr("target_length"),
                    )
                    depth1 = gr.Radio(
                        choices=[(_tr("popular_option"), "popular"), (_tr("undergraduate_option"), "undergraduate"), (_tr("research_option"), "research")],
                        value="undergraduate",
                        label=_tr("math_depth"),
                    )
                    focus1 = gr.Radio(
                        choices=[(_tr("balanced_option"), "balanced"), (_tr("biography_option"), "biography"), (_tr("mathematics_option"), "mathematics")],
                        value="balanced",
                        label=_tr("focus"),
                    )

            with gr.Accordion(_tr("advanced_settings"), open=False):
                structure_control1 = gr.Radio(
                    choices=[(_tr("more_stable"), "more_stable"), (_tr("more_free"), "more_free")],
                    value="more_stable",
                    label=_tr("structure_control"),
                )
                with gr.Row():
                    section_mode1 = gr.Radio(
                        choices=[(_tr("auto_option"), "auto"), (_tr("fixed_section_count"), "fixed")],
                        value="auto",
                        label=_tr("chapter_count"),
                    )
                    section_count1 = gr.Number(label=_tr("fixed_section_count"), value=12, minimum=5, maximum=20, step=1, visible=False)

                suggested_title1 = gr.Textbox(
                    label=_tr("suggested_title"),
                    placeholder=_tr("custom_title_placeholder"),
                    lines=1,
                )
                custom_prompt1 = gr.Textbox(
                    label=_tr("extra_requirements"),
                    placeholder=_tr("custom_requirements_placeholder"),
                    lines=3,
                )

            with gr.Accordion(_tr("layout_settings"), open=False):
                layout_mode1 = gr.Radio(
                    choices=[(_tr("auto_option"), "auto"), (_tr("layout_random"), "random"), (_tr("layout_manual"), "manual")],
                    value="auto",
                    label=_tr("layout_mode"),
                )
                template_style1 = gr.Dropdown(
                    choices=[
                        (_tr("classic_style"), "classic"),
                        (_tr("bookish_style"), "bookish"),
                        (_tr("archival_style"), "archival"),
                    ],
                    value="classic",
                    label=_tr("template_style"),
                    visible=False,
                )
                font_scheme1 = gr.Dropdown(
                    choices=[
                        (_tr("auto_option"), "auto"),
                        (_tr("times_font"), "times"),
                        (_tr("palatino_font"), "palatino"),
                        (_tr("default_latex_font"), "default"),
                    ],
                    value="auto",
                    label=_tr("font_scheme"),
                    visible=False,
                )
                spacing_mode1 = gr.Radio(
                    choices=[(_tr("compact_spacing"), "compact"), (_tr("standard_option"), "standard"), (_tr("relaxed_spacing"), "relaxed")],
                    value="standard",
                    label=_tr("spacing_mode"),
                    visible=False,
                )

            custom_generate_btn = gr.Button(_tr("start_generation"), variant="primary", size="lg")
            custom_hidden_btn = gr.Button(visible=False)
            status_output1_final = gr.Textbox(label=_tr("custom_progress"), lines=12)
            pdf_output1 = gr.File(label=_tr("pdf_output"))
            latex_output1 = gr.File(label=_tr("latex_output"))

            custom_topic_input.change(_set_topic_choice_from_custom, inputs=[custom_topic_input], outputs=[topic_dropdown])
            topic_dropdown.change(_clear_custom_topic_if_preset, inputs=[topic_dropdown], outputs=[custom_topic_input])
            section_mode1.change(_toggle_fixed_section_count, inputs=[section_mode1], outputs=[section_count1])
            layout_mode1.change(
                _toggle_manual_layout_controls,
                inputs=[layout_mode1],
                outputs=[template_style1, font_scheme1, spacing_mode1],
            )

            custom_generate_btn.click(
                custom_mode_generate,
                inputs=[
                    topic_dropdown,
                    custom_topic_input,
                    language1,
                    length1,
                    depth1,
                    focus1,
                    structure_control1,
                    section_mode1,
                    section_count1,
                    suggested_title1,
                    custom_prompt1,
                    layout_mode1,
                    template_style1,
                    font_scheme1,
                    spacing_mode1,
                    api_key,
                    base_url,
                    draft_model,
                    planning_model,
                    runtime_concurrency,
                    runtime_cache,
                    ui_language,
                ],
                outputs=[status_output1_final, pdf_output1, latex_output1, custom_generate_btn, custom_hidden_btn],
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

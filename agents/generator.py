import re
import random
from openai import OpenAI
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

import config
from domain.models import DocumentBrief, GenerationOptions, SectionBrief
from services.assembly import assemble_document, build_title_page
from services.cache import (
    build_bibliography_cache_key,
    build_section_cache_key,
    load_bibliography_cache,
    load_section_cache,
    save_bibliography_cache,
    save_section_cache,
)
from services.generation import SectionGenerationResult, generate_sections
from services.planning import build_generation_plan, generation_plan_from_payload
from services.retrieval import retrieve_section_context

console = Console()

LATEX_PREAMBLE_EN = r"""\documentclass[14pt,a4paper]{extarticle}

%% Page geometry
\usepackage[top=1in,bottom=1in,left=1.25in,right=1.25in,headheight=14pt]{geometry}

%% Font and encoding
\usepackage[T1]{fontenc}
\usepackage[utf8]{inputenc}
\usepackage{times}

%% Line spacing
\usepackage{setspace}
\setstretch{1.3}

%% URL handling
\usepackage[hyphens]{url}
\usepackage{breakurl}
\sloppy

%% Mathematics
\usepackage{amsmath}
\usepackage{amssymb}
\usepackage{amsthm}
\usepackage{mathtools}

%% Theorem environments
\newtheorem{theorem}{Theorem}[section]
\newtheorem{lemma}[theorem]{Lemma}
\newtheorem{proposition}[theorem]{Proposition}
\newtheorem{corollary}[theorem]{Corollary}
\theoremstyle{definition}
\newtheorem{definition}[theorem]{Definition}
\newtheorem{example}[theorem]{Example}
\theoremstyle{remark}
\newtheorem{remark}[theorem]{Remark}
\newtheorem{note}[theorem]{Note}

%% Other packages
\usepackage{graphicx}
\usepackage[colorlinks=true,linkcolor=blue,citecolor=blue,urlcolor=blue]{hyperref}
\usepackage{fancyhdr}
\usepackage[expansion=false]{microtype}
\usepackage{enumitem}
\usepackage{booktabs}
\usepackage{longtable}
\usepackage{array}
\usepackage{epigraph}

%% Header and footer
\pagestyle{fancy}
\fancyhf{}
\fancyhead[L]{\small\nouppercase{\leftmark}}
\fancyhead[R]{\small\thepage}
\renewcommand{\headrulewidth}{0.4pt}
\fancypagestyle{plain}{
  \fancyhf{}
  \fancyfoot[C]{\thepage}
  \renewcommand{\headrulewidth}{0pt}
}
"""

LATEX_PREAMBLE_EN_MODERN = r"""\documentclass[14pt,a4paper]{extarticle}

%% Page geometry
\usepackage[top=1in,bottom=1in,left=1in,right=1in,headheight=14pt]{geometry}

%% Font and encoding
\usepackage[T1]{fontenc}
\usepackage[utf8]{inputenc}
\usepackage{mathpazo}

%% Line spacing
\usepackage{setspace}
\setstretch{1.3}

%% URL handling
\usepackage[hyphens]{url}
\usepackage{breakurl}
\sloppy

%% Mathematics
\usepackage{amsmath}
\usepackage{amssymb}
\usepackage{amsthm}
\usepackage{mathtools}

%% Theorem environments
\newtheorem{theorem}{Theorem}[section]
\newtheorem{lemma}[theorem]{Lemma}
\newtheorem{proposition}[theorem]{Proposition}
\newtheorem{corollary}[theorem]{Corollary}
\theoremstyle{definition}
\newtheorem{definition}[theorem]{Definition}
\newtheorem{example}[theorem]{Example}
\theoremstyle{remark}
\newtheorem{remark}[theorem]{Remark}
\newtheorem{note}[theorem]{Note}

%% Other packages
\usepackage{graphicx}
\usepackage[colorlinks=true,linkcolor=darkgray,citecolor=darkgray,urlcolor=darkgray]{hyperref}
\usepackage{fancyhdr}
\usepackage[expansion=false]{microtype}
\usepackage{enumitem}
\usepackage{booktabs}

%% Header and footer
\pagestyle{fancy}
\fancyhf{}
\fancyhead[R]{\small\thepage}
\renewcommand{\headrulewidth}{0pt}
\fancypagestyle{plain}{
  \fancyhf{}
  \fancyfoot[C]{\thepage}
}
"""

LATEX_PREAMBLE_EN_MINIMAL = r"""\documentclass[14pt,a4paper]{extarticle}

%% Page geometry
\usepackage[top=1.2in,bottom=1.2in,left=1.5in,right=1.5in,headheight=14pt]{geometry}

%% Font and encoding
\usepackage[T1]{fontenc}
\usepackage[utf8]{inputenc}

%% Line spacing
\usepackage{setspace}
\setstretch{1.3}

%% URL handling
\usepackage[hyphens]{url}
\usepackage{breakurl}
\sloppy

%% Mathematics
\usepackage{amsmath}
\usepackage{amssymb}
\usepackage{amsthm}

%% Theorem environments
\newtheorem{theorem}{Theorem}[section]
\newtheorem{lemma}[theorem]{Lemma}
\newtheorem{definition}[theorem]{Definition}

%% Other packages
\usepackage{graphicx}
\usepackage[colorlinks=true,linkcolor=black,citecolor=black,urlcolor=black]{hyperref}
\usepackage{enumitem}

%% Simple page style
\pagestyle{plain}
"""

LATEX_PREAMBLE_ZH = r"""\documentclass[18pt,a4paper]{ctexart}

%% Page geometry
\usepackage[top=1in,bottom=1in,left=1.25in,right=1.25in,headheight=14pt]{geometry}

%% Line spacing
\usepackage{setspace}
\setstretch{1.8}

%% URL handling
\usepackage[hyphens]{url}
\usepackage{breakurl}
\sloppy

%% Mathematics
\usepackage{amsmath}
\usepackage{amssymb}
\usepackage{amsthm}
\usepackage{mathtools}

%% Theorem environments
\newtheorem{theorem}{定理}[section]
\newtheorem{lemma}[theorem]{引理}
\newtheorem{proposition}[theorem]{命题}
\newtheorem{corollary}[theorem]{推论}
\theoremstyle{definition}
\newtheorem{definition}[theorem]{定义}
\newtheorem{example}[theorem]{例}
\theoremstyle{remark}
\newtheorem{remark}[theorem]{注}
\newtheorem{note}[theorem]{注记}

%% Other packages
\usepackage{graphicx}
\usepackage[colorlinks=true,linkcolor=blue,citecolor=blue,urlcolor=blue]{hyperref}
\usepackage{fancyhdr}
\usepackage[expansion=false]{microtype}
\usepackage{enumitem}
\usepackage{booktabs}
\usepackage{longtable}
\usepackage{array}

%% Header and footer
\pagestyle{fancy}
\fancyhf{}
\fancyhead[L]{\small\nouppercase{\leftmark}}
\fancyhead[R]{\small\thepage}
\renewcommand{\headrulewidth}{0.4pt}
\fancypagestyle{plain}{
  \fancyhf{}
  \fancyfoot[C]{\thepage}
  \renewcommand{\headrulewidth}{0pt}
}
"""

LATEX_PREAMBLE_ZH_MODERN = r"""\documentclass[18pt,a4paper]{ctexart}

%% Page geometry
\usepackage[top=1in,bottom=1in,left=1in,right=1in,headheight=14pt]{geometry}

%% Line spacing
\usepackage{setspace}
\setstretch{1.8}

%% URL handling
\usepackage[hyphens]{url}
\usepackage{breakurl}
\sloppy

%% Mathematics
\usepackage{amsmath}
\usepackage{amssymb}
\usepackage{amsthm}

%% Theorem environments
\newtheorem{theorem}{定理}[section]
\newtheorem{lemma}[theorem]{引理}
\newtheorem{definition}[theorem]{定义}

%% Other packages
\usepackage{graphicx}
\usepackage[colorlinks=true,linkcolor=darkgray,citecolor=darkgray,urlcolor=darkgray]{hyperref}
\usepackage{fancyhdr}
\usepackage{enumitem}

%% Header and footer
\pagestyle{fancy}
\fancyhf{}
\fancyhead[R]{\small\thepage}
\renewcommand{\headrulewidth}{0pt}
\fancypagestyle{plain}{
  \fancyhf{}
  \fancyfoot[C]{\thepage}
}
"""

LATEX_PREAMBLE_ZH_MINIMAL = r"""\documentclass[18pt,a4paper]{ctexart}

%% Page geometry
\usepackage[top=1.2in,bottom=1.2in,left=1.5in,right=1.5in,headheight=14pt]{geometry}

%% Line spacing
\usepackage{setspace}
\setstretch{1.8}

%% URL handling
\usepackage[hyphens]{url}
\usepackage{breakurl}
\sloppy

%% Mathematics
\usepackage{amsmath}
\usepackage{amssymb}
\usepackage{amsthm}

%% Theorem environments
\newtheorem{theorem}{定理}[section]
\newtheorem{definition}[theorem]{定义}

%% Other packages
\usepackage{graphicx}
\usepackage[colorlinks=true,linkcolor=black,citecolor=black,urlcolor=black]{hyperref}

%% Simple page style
\pagestyle{plain}
"""

def _get_default_preamble(language: str) -> str:
    """随机选择一个LaTeX模板"""
    return LATEX_PREAMBLE_ZH if language == "zh" else LATEX_PREAMBLE_EN


_TEMPLATE_FAMILIES = {
    "en": {
        "classic": LATEX_PREAMBLE_EN,
        "bookish": LATEX_PREAMBLE_EN_MINIMAL,
        "archival": LATEX_PREAMBLE_EN_MODERN,
    },
    "zh": {
        "classic": LATEX_PREAMBLE_ZH,
        "bookish": LATEX_PREAMBLE_ZH_MINIMAL,
        "archival": LATEX_PREAMBLE_ZH_MODERN,
    },
}

_TEMPLATE_BASE_PARAMS = {
    "en": {
        "classic": {"top": 1.00, "bottom": 1.00, "left": 1.25, "right": 1.25, "line_stretch": 1.32, "headrule": 0.40},
        "bookish": {"top": 1.18, "bottom": 1.18, "left": 1.42, "right": 1.42, "line_stretch": 1.36, "headrule": 0.00},
        "archival": {"top": 1.00, "bottom": 1.00, "left": 1.02, "right": 1.02, "line_stretch": 1.28, "headrule": 0.00},
    },
    "zh": {
        "classic": {"top": 1.00, "bottom": 1.00, "left": 1.25, "right": 1.25, "line_stretch": 1.80, "headrule": 0.40},
        "bookish": {"top": 1.18, "bottom": 1.18, "left": 1.42, "right": 1.42, "line_stretch": 1.86, "headrule": 0.00},
        "archival": {"top": 1.00, "bottom": 1.00, "left": 1.02, "right": 1.02, "line_stretch": 1.72, "headrule": 0.00},
    },
}

_TEMPLATE_FAMILY_ALIASES = {
    "modern": "archival",
    "minimal": "bookish",
    "compact": "archival",
}

_SPACING_PRESETS = {
    "en": {
        "compact": 1.22,
        "standard": 1.32,
        "relaxed": 1.45,
    },
    "zh": {
        "compact": 1.62,
        "standard": 1.78,
        "relaxed": 1.90,
    },
}


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _normalize_template_family(language: str, family: str | None) -> str:
    normalized = _TEMPLATE_FAMILY_ALIASES.get(family or "", family or "classic")
    if normalized not in _TEMPLATE_FAMILIES[language]:
        return "classic"
    return normalized


def sample_template_profile(language: str, rng: random.Random | None = None) -> dict:
    rng = rng or random
    family = rng.choice(list(_TEMPLATE_FAMILIES[language].keys()))
    base = _TEMPLATE_BASE_PARAMS[language][family]
    spacing_limits = (1.18, 1.50) if language == "en" else (1.58, 1.92)

    overall_margin_shift = rng.uniform(-0.04, 0.04)
    vertical_skew = rng.uniform(-0.03, 0.03)
    horizontal_skew = rng.uniform(-0.04, 0.04)

    return {
        "version": 1,
        "language": language,
        "family": family,
        "top_margin_in": round(_clamp(base["top"] + overall_margin_shift + vertical_skew, 0.90, 1.60), 2),
        "bottom_margin_in": round(_clamp(base["bottom"] + overall_margin_shift - vertical_skew, 0.90, 1.60), 2),
        "left_margin_in": round(_clamp(base["left"] + overall_margin_shift + horizontal_skew, 0.90, 1.80), 2),
        "right_margin_in": round(_clamp(base["right"] + overall_margin_shift - horizontal_skew, 0.90, 1.80), 2),
        "line_stretch": round(_clamp(base["line_stretch"] + rng.uniform(-0.04, 0.04), spacing_limits[0], spacing_limits[1]), 2),
        "headrule_width_pt": round(_clamp(base["headrule"] + rng.uniform(-0.04, 0.04), 0.00, 0.45), 2),
        "font_scheme": "auto",
        "spacing_mode": "auto",
    }


def build_template_profile(
    language: str,
    *,
    layout_mode: str = "auto",
    style: str = "auto",
    font_scheme: str = "auto",
    spacing_mode: str = "auto",
    rng: random.Random | None = None,
) -> dict:
    rng = rng or random

    if layout_mode == "random":
        profile = sample_template_profile(language, rng=rng)
        profile["font_scheme"] = font_scheme
        profile["spacing_mode"] = spacing_mode
        return profile

    family = _normalize_template_family(language, style)
    base = _TEMPLATE_BASE_PARAMS[language][family]
    profile = {
        "version": 1,
        "language": language,
        "family": family,
        "top_margin_in": round(base["top"], 2),
        "bottom_margin_in": round(base["bottom"], 2),
        "left_margin_in": round(base["left"], 2),
        "right_margin_in": round(base["right"], 2),
        "line_stretch": round(base["line_stretch"], 2),
        "headrule_width_pt": round(base["headrule"], 2),
        "font_scheme": font_scheme,
        "spacing_mode": spacing_mode,
    }

    if layout_mode == "manual":
        if spacing_mode in _SPACING_PRESETS[language]:
            profile["line_stretch"] = _SPACING_PRESETS[language][spacing_mode]
        profile["top_margin_in"] = round(_clamp(base["top"] + rng.uniform(-0.02, 0.02), 0.90, 1.60), 2)
        profile["bottom_margin_in"] = round(_clamp(base["bottom"] + rng.uniform(-0.02, 0.02), 0.90, 1.60), 2)
        profile["left_margin_in"] = round(_clamp(base["left"] + rng.uniform(-0.03, 0.03), 0.90, 1.80), 2)
        profile["right_margin_in"] = round(_clamp(base["right"] + rng.uniform(-0.03, 0.03), 0.90, 1.80), 2)

    return profile


def _apply_font_scheme(preamble: str, language: str, font_scheme: str) -> str:
    if language != "en" or font_scheme == "auto":
        return preamble

    preamble = re.sub(r"^\\usepackage\{times\}\n?", "", preamble, flags=re.MULTILINE)
    preamble = re.sub(r"^\\usepackage\{mathpazo\}\n?", "", preamble, flags=re.MULTILINE)

    package_line = ""
    if font_scheme == "times":
        package_line = "\\usepackage{times}\n"
    elif font_scheme == "palatino":
        package_line = "\\usepackage{mathpazo}\n"
    elif font_scheme == "default":
        package_line = ""

    if not package_line:
        return preamble

    return re.sub(
        r"(\\usepackage\[utf8\]\{inputenc\}\n)",
        r"\1" + package_line,
        preamble,
        count=1,
    )


def _render_preamble(language: str, template_profile: dict | None) -> str:
    profile = template_profile or sample_template_profile(language)
    family = _normalize_template_family(language, profile.get("family", "classic"))
    base_preamble = _TEMPLATE_FAMILIES[language].get(family, _get_default_preamble(language))
    base_preamble = _apply_font_scheme(base_preamble, language, profile.get("font_scheme", "auto"))

    geometry = (
        "\\usepackage[top="
        f"{profile.get('top_margin_in', 1.0):.2f}in,"
        f"bottom={profile.get('bottom_margin_in', 1.0):.2f}in,"
        f"left={profile.get('left_margin_in', 1.25):.2f}in,"
        f"right={profile.get('right_margin_in', 1.25):.2f}in,headheight=14pt"
        "]{geometry}"
    )
    preamble = re.sub(r"\\usepackage\[top=[^\]]+\]\{geometry\}", lambda _match: geometry, base_preamble, count=1)
    preamble = re.sub(
        r"\\setstretch\{[0-9.]+\}",
        lambda _match: f"\\setstretch{{{profile.get('line_stretch', 1.8):.2f}}}",
        preamble,
        count=1,
    )
    if "\\renewcommand{\\headrulewidth}" in preamble:
        preamble = re.sub(
            r"\\renewcommand\{\\headrulewidth\}\{[0-9.]+pt\}",
            lambda _match: f"\\renewcommand{{\\headrulewidth}}{{{profile.get('headrule_width_pt', 0.0):.2f}pt}}",
            preamble,
            count=1,
        )
    return preamble


def _get_system_prompt(language: str, depth: str) -> str:
    """生成系统提示词"""
    lang_map = {"en": "English", "zh": "Chinese"}
    output_lang = lang_map.get(language, "English")

    # 根据语言设置字数要求
    if language == "zh":
        length_note = "CRITICAL: Count Chinese characters (汉字), NOT English words. Each subsection must contain substantial content with multiple paragraphs."
    else:
        length_note = "CRITICAL: Each subsection must contain substantial content with multiple paragraphs and detailed explanations."

    depth_instruction = {
        "popular": "Write in an accessible style suitable for general readers. Use minimal technical jargon and explain concepts clearly.",
        "undergraduate": "Write at university undergraduate level. Include standard mathematical notation, theorems, and moderate proofs.",
        "research": "Write at graduate/research level. Include complete proofs, technical details, and advanced mathematical analysis."
    }.get(depth, "Write at university undergraduate level.")

    return (
        f"You are an expert mathematician and historian of mathematics writing a comprehensive "
        f"academic paper in {output_lang}.\n\n"
        f"CRITICAL RULES:\n"
        f"- ALL content must be in {output_lang}\n"
        f"- Output ONLY pure LaTeX — no markdown, no code fences\n"
        r"- Do NOT include \documentclass, \usepackage, \begin{document}, \end{document}" + "\n"
        r"- Use \section{} and \subsection{} for structure" + "\n"
        f"- For inline math use $...$\n"
        r"- For display math use \begin{equation*}...\end{equation*} or \begin{align*}...\end{align*}" + "\n"
        r"- ALWAYS close every environment: \begin{theorem}...\end{theorem}, \begin{proof}...\end{proof}" + "\n"
        f"- {depth_instruction}\n\n"
        f"LENGTH REQUIREMENTS (STRICTLY ENFORCE):\n"
        f"- {length_note}\n"
        f"- Write extensive, detailed content for EVERY subsection\n"
        f"- Include multiple examples, explanations, and historical details\n"
        f"- Do NOT write short paragraphs — expand every point thoroughly\n\n"
        f"CONTENT QUALITY REQUIREMENTS:\n"
        f"- FORBIDDEN: Elementary/middle school mathematics (triangle angles, basic geometry, etc.)\n"
        f"- FORBIDDEN: Undergraduate basics unrelated to the mathematician (set theory definitions, etc.)\n"
        f"- REQUIRED: All theorems, definitions, proofs must relate to the mathematician's actual work\n"
        f"- REQUIRED: Focus on historical context and the mathematician's specific contributions\n"
        f"- REQUIRED: Use advanced mathematics appropriate to the mathematician's field"
        f"\n\n"
        f"WRITING STYLE REQUIREMENTS:\n"
        f"- Write in a natural, scholarly voice that sounds human-written\n"
        f"- FORBIDDEN: AI-like phrases such as \"It is worth noting that\", \"It should be emphasized that\", \"One might observe that\"\n"
        f"- FORBIDDEN: Overly formal transitions like \"Furthermore\", \"Moreover\", \"In addition to the aforementioned\"\n"
        f"- REQUIRED: Use varied sentence structures and natural academic prose\n"
        f"- REQUIRED: Write as if you are a knowledgeable historian telling a compelling story\n"
        f"- REQUIRED: Balance technical precision with narrative flow"
    )


SYSTEM_PROMPT = _get_system_prompt("en", "undergraduate")


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


def _call_llm_streaming(client: OpenAI, messages: list, max_tokens: int = 4096, max_retries: int = 3, model: str = None) -> str:
    """Call LLM with streaming, return full content string."""
    import time

    if model is None:
        model = config.MODEL

    for attempt in range(max_retries):
        try:
            content = ""
            stream = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                stream=True,
                timeout=120.0,
            )
            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta.content
                if delta:
                    content += delta
            return content
        except Exception as e:
            if attempt < max_retries - 1:
                wait_time = (attempt + 1) * 2
                console.print(f"[yellow]API调用失败，{wait_time}秒后重试... (尝试 {attempt + 1}/{max_retries})[/yellow]")
                time.sleep(wait_time)
            else:
                raise Exception(f"API调用失败（已重试{max_retries}次）: {str(e)}")


def _clean_latex(content: str) -> str:
    """Strip markdown artifacts, fix over-escaped commands, and remove stray document-level commands."""
    # Remove markdown code fences
    content = re.sub(r"```(?:latex|tex|plaintext)?\n?", "", content)
    content = re.sub(r"\n?```", "", content)
    # Fix over-escaped display math delimiters (\\[ → \[, \\] → \])
    content = content.replace("\\\\[", "\\[").replace("\\\\]", "\\]")
    content = content.replace("\\\\(", "\\(").replace("\\\\)", "\\)")
    # Remove document-level commands the model should not emit
    for pattern in [
        r"\\documentclass[^\n]*\n?",
        r"\\usepackage[^\n]*\n?",
        r"\\begin\{document\}",
        r"\\end\{document\}",
        r"\\maketitle\s*",
    ]:
        content = re.sub(pattern, "", content)
    return content.strip()


def _balance_braces(content: str) -> str:
    """Append missing closing braces so LaTeX doesn't error on truncated output."""
    open_count = content.count("{")
    close_count = content.count("}")
    missing = open_count - close_count
    if missing > 0:
        content = content.rstrip() + "}" * missing
    return content



def _close_open_environments(content: str) -> str:
    """Close any LaTeX environments that were opened but not closed (stack-based)."""
    stack = []
    for m in re.finditer(r"\\(begin|end)\{([^}]+)\}", content):
        cmd, env = m.group(1), m.group(2)
        if cmd == "begin":
            stack.append(env)
        elif cmd == "end" and stack and stack[-1] == env:
            stack.pop()
        # Ignore mismatched \end without corresponding \begin

    if stack:
        closing = "\n".join(f"\\end{{{env}}}" for env in reversed(stack))
        content = content.rstrip() + "\n" + closing

    return content


def _fix_bibliography(content: str) -> str:
    """Ensure bibliography is well-formed: balanced braces and properly closed."""
    content = _balance_braces(content)
    # Ensure \end{thebibliography} is present
    if r"\end{thebibliography}" not in content:
        # Remove stray \begin if present without \end
        content = re.sub(r"\\begin\{thebibliography\}\{[^}]*\}", "", content)
        content = (
            r"\begin{thebibliography}{99}" + "\n"
            + content.strip() + "\n"
            + r"\end{thebibliography}"
        )
    return content


def _call_text_completion(
    client: OpenAI,
    messages: list[dict],
    *,
    max_tokens: int,
    model: str | None,
    max_retries: int = 2,
) -> str:
    model_name = model or config.MODEL
    last_error: Exception | None = None
    for _ in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=messages,
                max_tokens=max_tokens,
            )
            raw = (response.choices[0].message.content or "").strip()
            if not raw:
                raise RuntimeError("Model returned empty content")
            return raw
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"Failed to obtain valid text completion: {last_error}")


def _generate_section_summary(client: OpenAI, section_title: str, section_content: str, language: str, model: str = None) -> str:
    """生成章节摘要（100-150词）"""
    if model is None:
        model = config.MODEL

    lang_instruction = "in English" if language == "en" else "in Chinese (中文)"

    console.print(f"[dim]  📊 生成摘要 - 标题: {section_title[:50]}..., 内容长度: {len(section_content)} 字符[/dim]")

    prompt = f"""Summarize the following section in 100-150 words {lang_instruction}.
Focus on: main ideas, key concepts, important theorems/definitions mentioned.

NOTE: The content contains LaTeX code and mathematical notation. Focus on the mathematical and historical content, ignore LaTeX formatting commands.

Section title: {section_title}

Section content:
{section_content}

Provide a concise summary that captures the essence of this section."""

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": f"You are a mathematics historian. Provide concise summaries {lang_instruction}. Always generate a summary even if the content contains LaTeX code."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=16000,
        )
        summary = response.choices[0].message.content.strip()

        # 检测拒绝回复
        refusal_keywords = ["抱歉", "无法", "cannot", "unable", "sorry", "can't", "I cannot"]
        if any(keyword in summary for keyword in refusal_keywords):
            console.print(f"[yellow]  ⚠ LLM拒绝生成摘要，返回: {summary[:100]}...[/yellow]")
            console.print(f"[dim]  提示：内容前100字符: {section_content[:100]}...[/dim]")
        else:
            console.print(f"[dim]  ✓ 摘要生成成功，长度: {len(summary)} 字符[/dim]")

        return summary
    except Exception as e:
        console.print(f"[yellow]  ⚠ 摘要生成失败: {type(e).__name__}: {str(e)}[/yellow]")
        return f"Summary of {section_title}"


def _build_planned_summary(brief: SectionBrief, content: str) -> str:
    if brief.summary:
        return brief.summary
    preview = content[:200].replace("\n", " ").strip()
    return preview or f"Summary of {brief.title}"


def _parse_opening_candidates(text: str) -> list[str]:
    openings = []
    for match in re.finditer(r"OPENING\s+\d+:\s*\n([\s\S]*?)(?=\nOPENING\s+\d+:\s*\n|\Z)", text):
        candidate = match.group(1).strip()
        if candidate:
            openings.append(candidate)
    return openings


def _generate_opening_paragraphs(client: OpenAI, section_title: str, mathematician: str, language: str, count: int = 5, model: str = None) -> list:
    """生成多个不同的开头段落供随机选择"""
    if model is None:
        model = config.MODEL

    lang_instruction = "in English" if language == "en" else "in Chinese (中文)"

    prompt = f"""Generate {count} different opening paragraphs for a section titled "{section_title}" about {mathematician}.

Each paragraph should:
- Be 100-150 words
- Take a different narrative approach or angle
- Be written {lang_instruction}
- Be in LaTeX format (plain text, can include math with $...$)

Return ONLY plain text in this structure:

OPENING 1:
paragraph 1

OPENING 2:
paragraph 2"""

    try:
        content = _call_text_completion(
            client,
            [
                {"role": "system", "content": f"You are a mathematics historian. Output plain text only {lang_instruction}."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=16000,
            model=model,
        )
        return _parse_opening_candidates(content)
    except Exception:
        return []


def _get_word_count(language: str, depth: str) -> str:
    if language == "zh":
        return {"popular": "3000", "undergraduate": "3500", "research": "4500"}.get(depth, "3500")
    return {"popular": "1500", "undergraduate": "1800", "research": "2200"}.get(depth, "1800")


def _build_existing_context_block(existing_context: str, brief: SectionBrief) -> tuple[str, str]:
    if not existing_context:
        return "", ""

    excerpt = retrieve_section_context(existing_context, brief)
    if not excerpt:
        return "", ""

    excerpt = excerpt[:8000] + ("...[truncated]" if len(excerpt) > 8000 else "")
    context_block = (
        "\n\nEXISTING PAPER CONTENT TO REWRITE AND EXPAND:\n"
        "The following is the most relevant text extracted from the existing PDF for this section. "
        "Your job is to rewrite, reorganise, and greatly expand any parts of it that are "
        "relevant to this section — preserving all key ideas and facts but adding far more "
        "mathematical depth, proofs, historical context, and scholarly analysis.\n\n"
        f"{excerpt}\n"
    )
    expand_instruction = (
        "- Rewrite and greatly expand any relevant content from the existing paper above\n"
        "- Preserve all key ideas, theorems, and historical facts from the original\n"
        "- Add significantly more mathematical detail, proofs, and analysis than the original\n"
    )
    return context_block, expand_instruction


def _generate_section(
    client: OpenAI,
    outline: dict,
    brief: SectionBrief,
    document_brief: DocumentBrief,
    total: int,
    options: GenerationOptions,
) -> str:
    """Generate LaTeX content for one section."""
    language = options.language
    depth = options.depth
    model = options.model
    word_count = _get_word_count(language, depth)
    mathematician = document_brief.mathematician or outline.get("mathematician", options.topic)

    # Optional: Generate multiple opening paragraphs and randomly select one
    chosen_opening = ""
    if options.diversity_count > 0:
        openings = _generate_opening_paragraphs(
            client,
            brief.title,
            mathematician,
            language,
            options.diversity_count,
            model,
        )
        chosen_opening = random.choice(openings) if openings else ""

    context_block, expand_instruction = _build_existing_context_block(options.existing_context, brief)
    custom_block = f"\n\nADDITIONAL REQUIREMENTS:\n{options.custom_prompt}\n" if options.custom_prompt else ""

    opening_block = ""
    if chosen_opening:
        opening_block = f"\n\nOPENING PARAGRAPH (use this to start the section):\n{chosen_opening}\n"
    elif brief.opening_hint:
        opening_block = f"\n\nOPENING GUIDANCE:\n{brief.opening_hint}\n"

    document_brief_block = document_brief.to_prompt_block()
    brief_block = brief.to_prompt_block()
    subsections = ", ".join(brief.subsections)

    user_prompt = f"""Write Section {brief.index} of {total} for the academic paper:
{document_brief_block}
{context_block}{opening_block}

{brief_block}

Requirements:
- Start with \\section{{{brief.title}}}
{"- Begin with the provided opening paragraph, then continue naturally" if chosen_opening else ""}
- Create a \\subsection{{}} for each subsection listed in the section brief
- Write at least {word_count} words of scholarly content in each subsection
{expand_instruction}- Include relevant mathematical theorems, definitions, and proofs
- Include historical context and analysis
- Use displayed equations, aligned environments, and theorem blocks extensively
- Let different subsections carry different weights when appropriate; some may be broader and others more concentrated
- The chapter does not need to feel perfectly even or mechanically complete
- Avoid unnecessary repetition across sections
- Keep terminology and tone consistent with the document brief
- Write in a natural, engaging academic style — avoid AI-like phrasing
- Vary your sentence structure and paragraph openings
- Let the narrative flow naturally rather than following a rigid template
- Do not make the chapter read like one installment in a perfectly uniform life-by-life checklist
- If this chapter is more historical, analytical, or technical than others, let that difference remain visible{custom_block}"""

    system_prompt = _get_system_prompt(language, depth)

    console.print(f"[dim]  🔧 调用LLM生成章节 {brief.index}/{total}: {brief.title[:50]}[/dim]")
    console.print(f"[dim]     语言={language}, 深度={depth}, 字数要求={word_count}[/dim]")
    console.print(f"[dim]     使用规划摘要: {len(document_brief.section_summaries)} 个章节[/dim]")

    raw = _call_llm_streaming(
        client,
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=64000,
        model=model
    )

    console.print(f"[dim]  📥 LLM返回内容长度: {len(raw)} 字符[/dim]")
    raw_preview = raw[:150].replace('\n', ' ')
    console.print(f"[dim]     预览: {raw_preview}...[/dim]")

    # 检测拒绝回复
    refusal_keywords = ["sorry", "can't", "cannot", "unable", "抱歉", "无法"]
    if len(raw) < 200 and any(keyword in raw.lower() for keyword in refusal_keywords):
        console.print(f"[red]  ❌ 警告：LLM拒绝生成章节内容！[/red]")
        console.print(f"[yellow]     完整回复: {raw}[/yellow]")
        console.print(f"[yellow]     提示词前500字符: {user_prompt[:500]}...[/yellow]")

    cleaned = _clean_latex(raw)
    cleaned = _close_open_environments(cleaned)
    return _balance_braces(cleaned)


def _planning_model(options: GenerationOptions) -> str | None:
    return options.planning_model or options.model


def _parse_section_review(text: str) -> dict:
    verdict = _extract_single_line(text, "VERDICT:").upper()
    feedback = _extract_block(text, "FEEDBACK:", "END FEEDBACK")
    if not feedback:
        feedback = text.strip()
    if verdict not in {"PASS", "REVISE"}:
        verdict = "PASS" if not feedback else "REVISE"
    return {"pass": verdict == "PASS", "feedback": feedback}


def _critique_section(
    client: OpenAI,
    brief: SectionBrief,
    document_brief: DocumentBrief,
    section_content: str,
    options: GenerationOptions,
) -> dict:
    excerpt = section_content[:18000]
    if len(section_content) > 18000:
        excerpt += "\n...[truncated]"

    try:
        raw = _call_text_completion(
            client,
            [
                {
                    "role": "system",
                    "content": "You are a rigorous reviewer for section-level academic writing and LaTeX prose. Return plain text only.",
                },
                {
                    "role": "user",
                    "content": f"""Review this generated LaTeX section against its section brief.

Language: {options.language}
Depth: {options.depth}

{document_brief.to_prompt_block()}

{brief.to_prompt_block()}

Generated section:
{excerpt}

Return ONLY plain text in this structure:

VERDICT: PASS or REVISE
FEEDBACK:
Explain the review briefly. If revisions are needed, list the concrete problems and fixes.
END FEEDBACK
""",
                },
            ],
            max_tokens=3000,
            model=_planning_model(options),
        )
        return _parse_section_review(raw)
    except Exception as exc:
        return {"pass": True, "feedback": f"Review skipped: {exc}"}


def _repair_section(
    client: OpenAI,
    brief: SectionBrief,
    document_brief: DocumentBrief,
    section_content: str,
    critique: dict,
    options: GenerationOptions,
) -> str:
    try:
        raw = _call_llm_streaming(
            client,
            [
                {"role": "system", "content": _get_system_prompt(options.language, options.depth)},
                {
                    "role": "user",
                    "content": f"""Revise the following LaTeX section using the critique below.

{document_brief.to_prompt_block()}

{brief.to_prompt_block()}

Critique:
{critique.get("feedback", "")}

Original section:
{section_content}

Revision rules:
- Output ONLY pure LaTeX for this section
- Preserve the section's overall structure and good material
- Apply the minimum necessary changes to resolve the critique
- Keep the same \\section{{{brief.title}}} heading
- Ensure every listed subsection is properly covered
- Preserve mathematical and historical specificity
""",
                },
            ],
            max_tokens=64000,
            model=_planning_model(options),
        )
    except Exception:
        return section_content

    cleaned = _clean_latex(raw)
    cleaned = _close_open_environments(cleaned)
    return _balance_braces(cleaned)


def _build_global_overview(briefs: list[SectionBrief], summaries: list[str | None]) -> str:
    lines = []
    for brief in briefs:
        summary = summaries[brief.index - 1] or brief.summary or ""
        lines.append(f"{brief.index}. {brief.title}: {summary}")
    return "\n".join(lines)


def _harmonize_section(
    client: OpenAI,
    brief: SectionBrief,
    document_brief: DocumentBrief,
    section_content: str,
    all_briefs: list[SectionBrief],
    section_summaries: list[str | None],
    options: GenerationOptions,
) -> str:
    overview = _build_global_overview(all_briefs, section_summaries)
    raw = _call_llm_streaming(
        client,
        [
            {"role": "system", "content": _get_system_prompt(options.language, options.depth)},
            {
                "role": "user",
                "content": f"""Polish this LaTeX section so it fits the full paper more consistently.

{document_brief.to_prompt_block()}

Paper overview:
{overview}

Current section brief:
{brief.to_prompt_block()}

Current section:
{section_content}

Revision goals:
- Output ONLY pure LaTeX for this section
- Preserve the section's structure, substance, and mathematical detail
- Make only light-to-moderate edits
- Improve terminology consistency with the rest of the paper
- Reduce obvious overlap with other sections
- Strengthen transitions into and out of this section when helpful
- Keep the same \\section{{{brief.title}}} heading
""",
            },
        ],
        max_tokens=64000,
        model=_planning_model(options),
    )

    cleaned = _clean_latex(raw)
    cleaned = _close_open_environments(cleaned)
    return _balance_braces(cleaned)


def _latex_escape(text: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
    }
    escaped = text or ""
    for source, target in replacements.items():
        escaped = escaped.replace(source, target)
    return escaped


def _sanitize_bib_key(value: str, fallback_index: int) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "", value or "")
    return cleaned or f"Ref{fallback_index}"


def _render_bibliography_from_plan(plan: dict) -> str:
    entries = plan.get("entries", [])

    if not entries:
        # 生成带警告的空白参考文献页
        error_msg = plan.get("error", "Unknown error")
        return (
            r"\begin{thebibliography}{99}" + "\n\n"
            r"\bibitem{placeholder}" + "\n"
            r"\textit{[Bibliography generation failed: " + error_msg[:100] + r". Please add references manually.]}" + "\n\n"
            r"\end{thebibliography}"
        )

    parts = [r"\begin{thebibliography}{99}", ""]

    for index, entry in enumerate(entries, 1):
        key = _sanitize_bib_key(entry.get("key", ""), index)
        author = _latex_escape(entry.get("author", "Unknown author"))
        year = _latex_escape(str(entry.get("year", "n.d.")))
        title = _latex_escape(entry.get("title", "Untitled work"))
        container = _latex_escape(entry.get("container", ""))
        publisher = _latex_escape(entry.get("publisher", ""))
        location = _latex_escape(entry.get("location", ""))
        note = _latex_escape(entry.get("note", ""))

        detail_parts = [f"{author} ({year}).", rf"\textit{{{title}}}."]
        if container:
            detail_parts.append(f"{container}.")
        if publisher and location:
            detail_parts.append(f"{publisher}, {location}.")
        elif publisher:
            detail_parts.append(f"{publisher}.")
        elif location:
            detail_parts.append(f"{location}.")
        if note:
            detail_parts.append(note)

        parts.append(rf"\bibitem{{{key}}}")
        parts.append(" ".join(detail_parts).strip())
        parts.append("")

    parts.append(r"\end{thebibliography}")
    return "\n".join(parts)


def _plan_bibliography(
    client: OpenAI,
    outline: dict,
    document_brief: DocumentBrief,
    section_briefs: list[SectionBrief],
    language: str = "en",
    model: str = None,
) -> dict:
    mathematician = outline.get("mathematician", document_brief.mathematician or "the mathematician")
    title = outline.get("title", document_brief.title or "")
    section_lines = "\n".join(f"- {brief.index}. {brief.title}: {brief.summary}" for brief in section_briefs)

    max_retries = 3
    last_error = None

    for attempt in range(max_retries):
        try:
            raw = _call_text_completion(
                client,
                [
                    {
                        "role": "system",
                        "content": "You are planning the bibliography for an academic paper. Return plain text only.",
                    },
                    {
                        "role": "user",
                        "content": f"""Plan a bibliography for the academic paper "{title}" about {mathematician}.

Language of paper: {language}

Document brief:
{document_brief.to_prompt_block()}

Sections:
{section_lines}

Return ONLY plain text in this structure:

ENTRY 1:
KEY: AuthorYYYY
CATEGORY: primary|biography|history|article
AUTHOR: ...
YEAR: ...
TITLE: ...
CONTAINER: ...
PUBLISHER: ...
LOCATION: ...
NOTE: ...

Rules:
- Return exactly 25 entries
- Include a balanced mix of primary sources, biographies, history texts, and research articles
- Keep titles and author names in their original languages
- Make keys compact and citation-friendly
- Keep note short and factual
""",
                    },
                ],
                max_tokens=8000,
                model=model,
            )
            entries: list[dict] = []
            for match in re.finditer(r"ENTRY\s+\d+:\s*\n([\s\S]*?)(?=\nENTRY\s+\d+:\s*\n|\Z)", raw):
                block = match.group(1)
                entries.append(
                    {
                        "key": _extract_single_line(block, "KEY:"),
                        "category": _extract_single_line(block, "CATEGORY:"),
                        "author": _extract_single_line(block, "AUTHOR:"),
                        "year": _extract_single_line(block, "YEAR:"),
                        "title": _extract_single_line(block, "TITLE:"),
                        "container": _extract_single_line(block, "CONTAINER:"),
                        "publisher": _extract_single_line(block, "PUBLISHER:"),
                        "location": _extract_single_line(block, "LOCATION:"),
                        "note": _extract_single_line(block, "NOTE:"),
                    }
                )
            filtered_entries = [entry for entry in entries if entry.get("title")]
            if filtered_entries:
                return {"entries": filtered_entries}
            else:
                raise ValueError("No valid entries parsed")
        except Exception as e:
            last_error = e
            console.print(f"[yellow]参考文献生成失败 (尝试 {attempt+1}/{max_retries}): {e}[/yellow]")

    console.print(f"[red]警告：参考文献生成失败，将生成空白参考文献页[/red]")
    return {"entries": [], "error": str(last_error)}


def _generate_bibliography(
    client: OpenAI,
    outline: dict,
    document_brief: DocumentBrief,
    section_briefs: list[SectionBrief],
    language: str = "en",
    model: str = None,
) -> str:
    """Plan references first, then render bibliography LaTeX deterministically."""
    plan = _plan_bibliography(client, outline, document_brief, section_briefs, language, model)
    rendered = _render_bibliography_from_plan(plan)
    return _fix_bibliography(rendered)


def generate_paper(client: OpenAI, topic: str, outline: dict, existing_context: str = "",
                   language: str = "en", depth: str = "undergraduate", focus: str = "balanced",
                   custom_prompt: str = "", diversity_count: int = 0, progress_callback=None,
                   draft_callback=None, resume_from: int = 0,
                   resume_sections: list[str | None] = None, resume_summaries: list[str | None] = None, model: str = None,
                   planning_model: str | None = None,
                   concurrency: int = 4, cache_enabled: bool = True, prepared_plan_payload: dict | None = None,
                   template_profile: dict | None = None, trace_callback=None):
    """Iteratively generate the full LaTeX paper."""
    options = GenerationOptions(
        topic=topic,
        language=language,
        depth=depth,
        focus=focus,
        custom_prompt=custom_prompt,
        diversity_count=diversity_count,
        existing_context=existing_context,
        model=model,
        planning_model=planning_model or model,
        concurrency=concurrency,
        cache_enabled=cache_enabled,
    )
    template_profile = template_profile or sample_template_profile(language)

    if progress_callback:
        progress_callback("Building the writing plan...")
    yield ("progress", None)

    if prepared_plan_payload:
        plan = generation_plan_from_payload(prepared_plan_payload, options, topic)
    else:
        plan = build_generation_plan(topic, outline, options, client=client)
    total = len(plan.section_briefs)
    if trace_callback:
        trace_callback(
            "plan_ready",
            total_sections=total,
            used_prepared_plan=bool(prepared_plan_payload),
            template_family=template_profile.get("family"),
        )

    section_contents: list[str | None] = [None] * total
    section_summaries: list[str | None] = [None] * total
    if resume_sections:
        for index, content in enumerate(resume_sections[:total]):
            if content is not None:
                section_contents[index] = content
    if resume_summaries:
        for index, summary in enumerate(resume_summaries[:total]):
            if summary is not None:
                section_summaries[index] = summary

    completed_count = sum(content is not None for content in section_contents)

    def report_result(result: SectionGenerationResult, *, reported_results: set[int]) -> None:
        if result.index in reported_results:
            return

        reported_results.add(result.index)
        section_contents[result.index - 1] = result.content
        section_summaries[result.index - 1] = result.summary

        console.print(f"[dim]  Section ready: {result.title} ({len(result.content)} chars)[/dim]")
        content_preview = result.content[:200].replace("\n", " ")
        console.print(f"[dim]  Preview: {content_preview}...[/dim]")

        if not result.from_cache and options.cache_enabled:
            cache_key = build_section_cache_key(
                outline,
                plan.section_briefs[result.index - 1],
                plan.document_brief,
                options,
            )
            save_section_cache(cache_key, result.content, result.summary)

        if draft_callback:
            draft_callback(result.index - 1, result.content, result.summary or "")
        if trace_callback:
            trace_callback(
                "section_completed",
                section_index=result.index,
                title=result.title,
                from_cache=result.from_cache,
                content_length=len(result.content),
            )

        if progress_callback:
            prefix = "[cache]" if result.from_cache else "[done]"
            cache_note = " (cache)" if result.from_cache else ""
            progress_callback(
                f"{prefix} [{result.index}/{total}] {result.title}{cache_note}\n"
                f"[summary] {result.summary}\n"
            )

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
        transient=False,
    ) as progress:
        task = progress.add_task("Generating sections...", total=total + 1, completed=completed_count)
        pending_briefs = [brief for brief in plan.section_briefs if section_contents[brief.index - 1] is None]

        cached_results: dict[int, SectionGenerationResult] = {}
        for brief in pending_briefs:
            if progress_callback:
                progress_callback(f"[queued] [{brief.index}/{total}] {brief.title}")
                if diversity_count > 0:
                    progress_callback(
                        f"[queued] [{brief.index}/{total}] {brief.title}\n"
                        f"   |- Generating {diversity_count} opening candidates..."
                    )
            yield ("progress", None)

            if not options.cache_enabled:
                if trace_callback:
                    trace_callback("section_cache_skipped", section_index=brief.index, title=brief.title)
                continue

            cache_key = build_section_cache_key(outline, brief, plan.document_brief, options)
            cached_payload = load_section_cache(cache_key)
            if not cached_payload:
                if trace_callback:
                    trace_callback("section_cache_miss", section_index=brief.index, title=brief.title)
                continue
            if trace_callback:
                trace_callback("section_cache_hit", section_index=brief.index, title=brief.title)

            cached_results[brief.index] = SectionGenerationResult(
                index=brief.index,
                title=brief.title,
                content=cached_payload["content"],
                summary=cached_payload.get("summary") or brief.summary,
                from_cache=True,
            )

        reported_results: set[int] = set()

        def worker(brief: SectionBrief):
            if trace_callback:
                trace_callback("section_generation_started", section_index=brief.index, title=brief.title)
            content = _generate_section(
                client,
                outline,
                brief,
                plan.document_brief,
                total,
                options,
            )
            if trace_callback:
                trace_callback(
                    "section_generation_finished",
                    section_index=brief.index,
                    title=brief.title,
                    content_length=len(content),
                )
            return content

        def summary_builder(brief: SectionBrief, content: str) -> str:
            return _build_planned_summary(brief, content)

        for cached_result in sorted(cached_results.values(), key=lambda item: item.index):
            report_result(cached_result, reported_results=reported_results)
            progress.advance(task)
            yield ("progress", None)

        uncached_briefs = [brief for brief in pending_briefs if brief.index not in cached_results]
        for result in generate_sections(
            uncached_briefs,
            worker=worker,
            summary_builder=summary_builder,
            concurrency=options.concurrency,
        ):
            report_result(result, reported_results=reported_results)
            progress.advance(task)
            yield ("progress", None)

        progress.update(task, description="[cyan]Generating bibliography...[/cyan]")
        if progress_callback:
            progress_callback("Generating bibliography...")
        yield ("progress", None)

        bibliography_cache_key = build_bibliography_cache_key(
            outline,
            plan.document_brief,
            plan.section_briefs,
            options,
        )
        cached_bibliography = load_bibliography_cache(bibliography_cache_key) if options.cache_enabled else None
        if cached_bibliography:
            if trace_callback:
                trace_callback("bibliography_cache_hit")
            bibliography = cached_bibliography["content"]
        else:
            if trace_callback:
                trace_callback("bibliography_cache_miss")
            bibliography_plan = _plan_bibliography(
                client,
                outline,
                plan.document_brief,
                plan.section_briefs,
                language,
                _planning_model(options),
            )
            if trace_callback:
                trace_callback("bibliography_plan_ready", entry_count=len(bibliography_plan.get("entries", [])))
            bibliography = _fix_bibliography(_render_bibliography_from_plan(bibliography_plan))
            if options.cache_enabled:
                save_bibliography_cache(bibliography_cache_key, bibliography_plan, bibliography)
        if trace_callback:
            trace_callback("bibliography_ready", content_length=len(bibliography))
        progress.advance(task)

    abstract_page = build_title_page(outline, language, template_profile)
    preamble = _render_preamble(language, template_profile)
    latex_content = assemble_document(
        preamble,
        abstract_page,
        [content for content in section_contents if content is not None],
        bibliography,
    )
    if trace_callback:
        trace_callback("document_assembled", content_length=len(latex_content))
    yield ("done", latex_content)

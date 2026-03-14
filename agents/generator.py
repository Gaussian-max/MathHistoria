import re
from openai import OpenAI
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

import config

console = Console()

LATEX_PREAMBLE = r"""\documentclass[12pt,a4paper]{article}

%% Page geometry
\usepackage[top=1in,bottom=1in,left=1.25in,right=1.25in]{geometry}

%% Font and encoding
\usepackage[T1]{fontenc}
\usepackage[utf8]{inputenc}
\usepackage{times}

%% Line spacing
\usepackage{setspace}
\onehalfspacing

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
\usepackage{microtype}
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

SYSTEM_PROMPT = (
    "You are an expert mathematician and historian of mathematics writing a comprehensive "
    "university-level academic paper in English.\n\n"
    "CRITICAL RULES:\n"
    "- ALL content must be in English\n"
    "- Output ONLY pure LaTeX — no markdown, no code fences\n"
    r"- Do NOT include \documentclass, \usepackage, \begin{document}, \end{document}" + "\n"
    r"- Use \section{} and \subsection{} for structure" + "\n"
    "- For inline math use $...$\n"
    r"- For display math use \begin{equation*}...\end{equation*} or \begin{align*}...\end{align*}" + "\n"
    r"- ALWAYS close every environment: \begin{theorem}...\end{theorem}, \begin{proof}...\end{proof}" + "\n"
    r"- Use \cite{AuthorYear} for citations" + "\n"
    "- Write detailed, scholarly English prose — at least 1,000 words per section"
)


def _call_llm_streaming(client: OpenAI, messages: list, max_tokens: int = 4096) -> str:
    """Call LLM with streaming, return full content string."""
    content = ""
    stream = client.chat.completions.create(
        model=config.MODEL,
        messages=messages,
        max_tokens=max_tokens,
        temperature=0.7,
        stream=True,
    )
    for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta.content
        if delta:
            content += delta
    return content


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


def _generate_section(
    client: OpenAI,
    topic: str,
    outline: dict,
    section: dict,
    section_num: int,
    total: int,
    existing_context: str = "",
) -> str:
    """Generate LaTeX content for one section."""
    subsections = ", ".join(section.get("subsections", []))
    mathematician = outline.get("mathematician", topic)
    birth = outline.get("birth_year", "")
    death = outline.get("death_year", "")
    lifespan = f"({birth}--{death})" if birth else ""

    context_block = ""
    expand_instruction = ""
    if existing_context:
        # Pass a generous excerpt so the model can rewrite and expand existing content
        excerpt = existing_context[:8000] + ("...[truncated]" if len(existing_context) > 8000 else "")
        context_block = (
            f"\n\nEXISTING PAPER CONTENT TO REWRITE AND EXPAND:\n"
            f"The following is the raw text extracted from the existing PDF. "
            f"Your job is to rewrite, reorganise, and greatly expand any parts of it that are "
            f"relevant to this section — preserving all key ideas and facts but adding far more "
            f"mathematical depth, proofs, historical context, and scholarly analysis.\n\n"
            f"{excerpt}\n"
        )
        expand_instruction = (
            "- Rewrite and greatly expand any relevant content from the existing paper above\n"
            "- Preserve all key ideas, theorems, and historical facts from the original\n"
            "- Add significantly more mathematical detail, proofs, and analysis than the original\n"
        )

    user_prompt = f"""Write Section {section_num} of {total} for the academic paper:
Title: "{outline.get('title', topic)}"
Subject: {mathematician} {lifespan}
{context_block}
Section title: {section['title']}
Subsections to cover: {subsections}

Requirements:
- Start with \\section{{{section['title']}}}
- Create a \\subsection{{}} for each subsection listed above
- Write at least 1,500 words of scholarly content in each subsection
{expand_instruction}- Include relevant mathematical theorems, definitions, and proofs
- Include historical context and analysis
- Use \\cite{{}} for references (use author-year keys like \\cite{{Gauss1801}})
- Use displayed equations, aligned environments, and theorem blocks extensively
- Every subsection should be rich with mathematical detail and historical narrative"""

    raw = _call_llm_streaming(
        client,
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=6000,
    )
    cleaned = _clean_latex(raw)
    cleaned = _close_open_environments(cleaned)
    return _balance_braces(cleaned)


def _generate_abstract_page(outline: dict) -> str:
    """Build the title page and abstract LaTeX block."""
    title = outline.get("title", "Mathematical Legacy").replace("&", r"\&")
    mathematician = outline.get("mathematician", "").replace("&", r"\&")
    birth = outline.get("birth_year", "")
    death = outline.get("death_year", "")
    lifespan = f"{birth}--{death}" if birth and death else birth
    abstract = outline.get("abstract", "").replace("&", r"\&").replace("%", r"\%")

    keywords = ", ".join(outline.get("keywords", []))

    return rf"""
\begin{{titlepage}}
  \centering
  \vspace*{{\fill}}
  {{\fontsize{{20}}{{24}}\selectfont\bfseries {title} \par}}
  \vspace{{1.5cm}}
  {{\large A Study in the History of Mathematics \par}}
  \vspace{{1cm}}
  {{\large {mathematician} ({lifespan}) \par}}
  \vspace{{3cm}}
  {{\normalsize\today \par}}
  \vspace*{{\fill}}
\end{{titlepage}}

\begin{{abstract}}
{abstract}

\medskip
\noindent\textbf{{Keywords:}} {keywords}
\end{{abstract}}

\newpage
\tableofcontents
\newpage
"""


def _generate_bibliography(client: OpenAI, outline: dict) -> str:
    """Generate a bibliography section with ~25 entries."""
    mathematician = outline.get("mathematician", "the mathematician")
    title = outline.get("title", "")

    user_prompt = f"""Generate a bibliography for the academic paper "{title}" about {mathematician}.

Provide exactly 25 realistic bibliography entries in LaTeX \\bibitem format.
Use this exact format (no markdown, pure LaTeX):

\\begin{{thebibliography}}{{99}}

\\bibitem{{AuthorYYYY}}
Author, F. N. (YYYY). \\textit{{Title of Work}}. Publisher, City.

\\bibitem{{...}}
...

\\end{{thebibliography}}

Include primary sources (original works by {mathematician}), contemporary biographies,
mathematical history textbooks, and journal articles. Make the keys and content realistic."""

    raw = _call_llm_streaming(
        client,
        [
            {"role": "system", "content": "Output only valid LaTeX bibliography code. No markdown."},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=4096,
    )
    cleaned = _clean_latex(raw)
    return _fix_bibliography(cleaned)


def generate_paper(client: OpenAI, topic: str, outline: dict, existing_context: str = "") -> str:
    """
    Iteratively generate the full LaTeX paper.
    existing_context: text extracted from an existing PDF, used as reference for each section.
    Returns the complete LaTeX document as a string.
    """
    sections = outline.get("sections", [])
    total = len(sections)

    section_contents = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
        transient=False,
    ) as progress:
        task = progress.add_task("Generating sections...", total=total + 1)

        for i, section in enumerate(sections, 1):
            progress.update(
                task,
                description=f"[cyan]Section {i}/{total}:[/cyan] {section['title'][:55]}",
            )
            content = _generate_section(
                client, topic, outline, section, i, total, existing_context
            )
            section_contents.append(content)
            progress.advance(task)

        # Bibliography
        progress.update(task, description="[cyan]Generating bibliography...[/cyan]")
        bibliography = _generate_bibliography(client, outline)
        progress.advance(task)

    # Assemble full document
    abstract_page = _generate_abstract_page(outline)

    doc_parts = [
        LATEX_PREAMBLE,
        "\n\\begin{document}\n",
        abstract_page,
    ]

    for content in section_contents:
        doc_parts.append("\n\n" + content + "\n")

    doc_parts.append("\n\\newpage\n" + bibliography + "\n")
    doc_parts.append("\n\\end{document}\n")

    return "".join(doc_parts)

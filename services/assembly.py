def _latex_escape(text: str) -> str:
    escaped = text or ""
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    for source, target in replacements.items():
        escaped = escaped.replace(source, target)
    return escaped


def build_title_page(outline: dict, language: str = "en", template_profile: dict | None = None) -> str:
    """Build the title page LaTeX block."""
    title = _latex_escape(outline.get("title", "Mathematical Legacy"))
    mathematician = _latex_escape(outline.get("mathematician", ""))
    birth = _latex_escape(outline.get("birth_year", ""))
    death = _latex_escape(outline.get("death_year", ""))
    lifespan = f"{birth}--{death}" if birth and death else birth
    family = (template_profile or {}).get("family", "classic")

    if family == "bookish":
        return rf"""
\begin{{titlepage}}
  \centering
  \vspace*{{1.8cm}}
  {{\small\itshape A Mathematical-Historical Essay \par}}
  \vspace{{1.2cm}}
  {{\fontsize{{22}}{{28}}\selectfont\bfseries {title} \par}}
  \vspace{{0.8cm}}
  {{\large {mathematician} ({lifespan}) \par}}
  \vspace{{1cm}}
  \rule{{0.55\textwidth}}{{0.4pt}}\par
  \vspace{{1.8cm}}
  {{\normalsize\today \par}}
  \vspace*{{\fill}}
\end{{titlepage}}

\newpage
\tableofcontents
\newpage
"""

    if family == "archival":
        return rf"""
\begin{{titlepage}}
  \raggedright
  \vspace*{{1.2cm}}
  {{\small\scshape Mathematical History Profile \par}}
  \vspace{{1.4cm}}
  {{\fontsize{{22}}{{28}}\selectfont\bfseries {title} \par}}
  \vspace{{1.6cm}}
  {{\large Subject: {mathematician} \par}}
  {{\normalsize Dates: {lifespan} \par}}
  \vspace{{1.2cm}}
  \rule{{0.75\textwidth}}{{0.6pt}}\par
  \vspace{{0.8cm}}
  {{\small Compiled on \today \par}}
  \vspace*{{\fill}}
\end{{titlepage}}

\newpage
\tableofcontents
\newpage
"""

    return rf"""
\begin{{titlepage}}
  \centering
  \vspace*{{\fill}}
  {{\fontsize{{20}}{{24}}\selectfont\bfseries {title} \par}}
  \vspace{{2cm}}
  {{\large {mathematician} ({lifespan}) \par}}
  \vspace{{3cm}}
  {{\normalsize\today \par}}
  \vspace*{{\fill}}
\end{{titlepage}}

\newpage
\tableofcontents
\newpage
"""


def assemble_document(
    preamble: str,
    title_page: str,
    section_contents: list[str],
    bibliography: str,
) -> str:
    parts = [preamble, "\n\\begin{document}\n", title_page]
    for content in section_contents:
        parts.append("\n\n" + content + "\n")
    parts.append("\n\\newpage\n" + bibliography + "\n")
    parts.append("\n\\end{document}\n")
    return "".join(parts)

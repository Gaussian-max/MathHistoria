def build_title_page(outline: dict, language: str = "en") -> str:
    """Build the title page LaTeX block."""
    title = outline.get("title", "Mathematical Legacy").replace("&", r"\&")
    mathematician = outline.get("mathematician", "").replace("&", r"\&")
    birth = outline.get("birth_year", "")
    death = outline.get("death_year", "")
    lifespan = f"{birth}--{death}" if birth and death else birth

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

import os

import config
from agents.compiler import compile_pdf, count_pdf_pages
from utils.security import safe_filename


def get_output_paths(topic: str, language: str = "en") -> tuple[str, str]:
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    safe_name = safe_filename(topic)
    suffix = "_zh" if language == "zh" else ""
    latex_path = os.path.join(config.OUTPUT_DIR, f"{safe_name}{suffix}.tex")
    pdf_path = os.path.splitext(latex_path)[0] + ".pdf"
    return latex_path, pdf_path


def write_latex_output(latex_content: str, topic: str, language: str = "en") -> str:
    latex_path, _ = get_output_paths(topic, language)
    with open(latex_path, "w", encoding="utf-8") as f:
        f.write(latex_content)
    return latex_path


def compile_latex_output(latex_path: str) -> tuple[str | None, int | None, str]:
    outcome = compile_pdf(latex_path)
    if not outcome.pdf_path:
        return None, None, outcome.status
    return outcome.pdf_path, count_pdf_pages(outcome.pdf_path), outcome.status


def persist_and_compile_output(
    latex_content: str,
    topic: str,
    language: str = "en",
) -> tuple[str, str | None, int | None, str]:
    """Persist LaTeX content and compile the corresponding PDF when possible."""
    latex_path = write_latex_output(latex_content, topic, language)
    pdf_path, pages, compile_status = compile_latex_output(latex_path)
    return latex_path, pdf_path, pages, compile_status

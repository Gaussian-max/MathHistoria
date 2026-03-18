import os
import shutil
import subprocess
from dataclasses import dataclass

from rich.console import Console

console = Console()


@dataclass(frozen=True)
class CompileOutcome:
    pdf_path: str | None
    status: str


def find_latex_engine() -> str | None:
    """Find an available LaTeX engine: pdflatex preferred, then xelatex."""
    for engine in ("pdflatex", "xelatex"):
        if shutil.which(engine):
            return engine
    return None


def compile_pdf(latex_file: str) -> CompileOutcome:
    """
    Compile a .tex file to PDF (runs the engine twice for cross-references).
    Returns a compile outcome describing whether PDF compilation succeeded.
    """
    engine = find_latex_engine()
    if not engine:
        console.print(
            "[yellow]No LaTeX engine found. Skipping PDF compilation.[/yellow]\n"
            "Please install MacTeX (macOS) or TeX Live (Linux):\n"
            "  macOS:  brew install --cask mactex\n"
            "  Linux:  sudo apt install texlive-full"
        )
        return CompileOutcome(pdf_path=None, status="missing_engine")

    latex_dir = os.path.dirname(os.path.abspath(latex_file))
    latex_filename = os.path.basename(latex_file)
    base_name = os.path.splitext(latex_filename)[0]
    pdf_path = os.path.join(latex_dir, base_name + ".pdf")
    log_path = os.path.join(latex_dir, base_name + ".log")

    cmd = [
        engine,
        "-interaction=nonstopmode",
        "-no-shell-escape",  # 🔒 安全修复：禁用 shell 命令执行
        "-output-directory", latex_dir,
        latex_filename,
    ]

    for pass_num in (1, 2):
        console.print(f"  [dim]Pass {pass_num}/2 ({engine})...[/dim]")
        result = subprocess.run(
            cmd,
            cwd=latex_dir,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='ignore',
            timeout=300,  # 🔒 安全修复：添加5分钟超时限制
        )
        if result.returncode != 0:
            # Check if PDF was still generated despite errors (warnings are common)
            if not os.path.exists(pdf_path):
                console.print(f"[red]Compilation failed (pass {pass_num}).[/red]")
                console.print(f"[dim]Log file: {log_path}[/dim]")
                # Show last 20 lines of stdout for debugging
                lines = (result.stdout or "").strip().split("\n")
                for line in lines[-20:]:
                    if line.strip():
                        console.print(f"  [dim]{line}[/dim]")
                return CompileOutcome(pdf_path=None, status="compile_failed")

    if os.path.exists(pdf_path):
        return CompileOutcome(pdf_path=pdf_path, status="compiled")
    return CompileOutcome(pdf_path=None, status="compile_failed")


def count_pdf_pages(pdf_path: str) -> int | None:
    """Count pages in PDF using pdfinfo if available."""
    if not shutil.which("pdfinfo"):
        return None
    try:
        result = subprocess.run(
            ["pdfinfo", pdf_path],
            capture_output=True,
            text=True,
            timeout=10,
        )
        for line in result.stdout.split("\n"):
            if line.startswith("Pages:"):
                return int(line.split(":")[1].strip())
    except Exception:
        pass
    return None

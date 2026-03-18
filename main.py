import os
import sys
import re

from openai import OpenAI
from rich.console import Console
from rich.panel import Panel
from rich.prompt import IntPrompt, Prompt
from rich.table import Table
from rich import box

import config
from app.pipeline import persist_and_compile_output
from agents.suggester import get_suggestions
from agents.outline import generate_outline, generate_outline_from_pdf
from agents.generator import generate_paper
from agents.pdf_reader import extract_text_from_pdf, analyze_pdf
from utils.security import validate_pdf_path  # 🔒 安全修复

console = Console()


def display_suggestions(suggestions: list[dict]) -> None:
    table = Table(box=box.ROUNDED, show_header=True, header_style="bold cyan")
    table.add_column("#", style="dim", width=4)
    table.add_column("Mathematician", style="bold")
    table.add_column("Years", style="dim")
    table.add_column("Focus Areas")
    for i, s in enumerate(suggestions, 1):
        table.add_row(str(i), s["name"], s["years"], s["description"])
    table.add_row("0", "[italic]Custom topic[/italic]", "", "Enter your own mathematician")
    console.print(table)


def display_outline(outline: dict) -> None:
    console.print("\n[bold]Paper Outline:[/bold]")
    for i, section in enumerate(outline.get("sections", []), 1):
        console.print(f"  [cyan]{i}.[/cyan] {section['title']}")
        for sub in section.get("subsections", []):
            console.print(f"      [dim]•[/dim] {sub}")
    console.print()


def save_and_compile(latex_content: str, topic: str, language: str = "en") -> None:
    """Save LaTeX to file and compile to PDF."""
    latex_path, pdf_path, pages, compile_status = persist_and_compile_output(latex_content, topic, language)

    console.print(f"\n[green]✓[/green] LaTeX saved: [bold]{latex_path}[/bold]")

    console.rule("[bold]Step 3 / 3 — Compiling PDF[/bold]")
    if pdf_path:
        page_info = f" ([bold]{pages} pages[/bold])" if pages else ""
        console.print(
            Panel(
                f"[bold green]PDF generated successfully![/bold green]{page_info}\n"
                f"[dim]{pdf_path}[/dim]",
                border_style="green",
            )
        )
    else:
        message = (
            "[yellow]No LaTeX engine detected - LaTeX source is ready:[/yellow]\n"
            if compile_status == "missing_engine"
            else "[yellow]PDF compilation failed - LaTeX source is ready:[/yellow]\n"
        )
        console.print(
            Panel(
                message
                +
                f"[bold]{latex_path}[/bold]\n\n"
                "[dim]You can still download or compile the .tex file manually:[/dim]\n"
                f"  pdflatex -output-directory {config.OUTPUT_DIR} {latex_path}\n"
                f"  pdflatex -output-directory {config.OUTPUT_DIR} {latex_path}",
                border_style="yellow",
            )
        )


def collect_generated_paper(*args, **kwargs) -> str:
    """Consume the paper generator and return the final LaTeX document."""
    latex_content = None
    for status, payload in generate_paper(*args, **kwargs):
        if status == "done":
            latex_content = payload

    if latex_content is None:
        raise RuntimeError("Paper generation finished without producing LaTeX output.")

    return latex_content


def prompt_runtime_options() -> tuple[int, bool]:
    """Collect runtime settings for concurrency and local caching."""
    concurrency = IntPrompt.ask("Concurrent section jobs", default=4)
    cache_answer = Prompt.ask("Enable local section cache? (y/n)", default="y").strip().lower()
    cache_enabled = cache_answer not in {"n", "no"}
    return max(1, concurrency), cache_enabled


# ── Mode A: start from scratch ────────────────────────────────────────────────

def flow_fresh(client: OpenAI) -> None:
    suggestions = get_suggestions()
    console.print("[bold]Suggested topics (mathematicians after Euler, 1707–1783):[/bold]\n")
    display_suggestions(suggestions)

    choice = IntPrompt.ask("\nSelect a topic number (0 for custom)", default=5)
    if choice == 0:
        topic = Prompt.ask("Enter mathematician name / topic")
    elif 1 <= choice <= len(suggestions):
        topic = suggestions[choice - 1]["name"]
    else:
        console.print("[yellow]Invalid choice — defaulting to Bernhard Riemann.[/yellow]")
        topic = "Bernhard Riemann"

    console.print(f"\n[green]Selected:[/green] [bold]{topic}[/bold]\n")

    console.rule("[bold]Step 1 / 3 — Generating Outline[/bold]")
    with console.status("Calling LLM for outline...", spinner="dots"):
        outline = generate_outline(client, topic)

    console.print(f"[green]✓[/green] Outline ready — [bold]{len(outline.get('sections', []))}[/bold] sections\n")
    display_outline(outline)

    console.rule("[bold]Step 2 / 3 — Generating Paper Content[/bold]")
    concurrency, cache_enabled = prompt_runtime_options()
    console.print(f"[dim]Generating {len(outline.get('sections', []))} sections + bibliography…[/dim]\n")
    latex_content = collect_generated_paper(
        client,
        topic,
        outline,
        concurrency=concurrency,
        cache_enabled=cache_enabled,
    )

    save_and_compile(latex_content, topic, "en")


# ── Mode B: continue / expand from existing PDF ───────────────────────────────

def flow_from_pdf(client: OpenAI) -> None:
    pdf_path = Prompt.ask("Path to your existing PDF").strip()

    # Validate the user-supplied PDF, but don't restrict it to a few hardcoded
    # directories. CLI users commonly work with PDFs outside the repo/home/output.
    is_valid, error_msg = validate_pdf_path(pdf_path)
    if not is_valid:
        console.print(f"[red]安全错误:[/red] {error_msg}")
        sys.exit(1)

    # Step 1: read + analyse
    console.rule("[bold]Step 1 / 3 — Analysing Existing PDF[/bold]")
    with console.status("Extracting text from PDF…", spinner="dots"):
        pdf_text, page_count = extract_text_from_pdf(pdf_path)

    if not pdf_text.strip():
        console.print("[red]Could not extract text from this PDF (possibly scanned image).[/red]")
        sys.exit(1)

    with console.status("Analysing content with LLM…", spinner="dots"):
        analysis = analyze_pdf(client, pdf_text, page_count)

    mathematician = analysis.get("mathematician", "Unknown")
    console.print(f"\n[green]✓[/green] Detected: [bold]{mathematician}[/bold] | {page_count} pages")
    console.print(f"  [dim]Already covered:[/dim] {', '.join(analysis.get('covered_sections', []))}")
    console.print(f"  [dim]Missing areas:[/dim]   {', '.join(analysis.get('missing_areas', []))}\n")

    # Step 2: generate expanded outline
    console.rule("[bold]Step 2 / 3 — Building Expanded Outline & Content[/bold]")
    with console.status("Generating expanded outline…", spinner="dots"):
        outline = generate_outline_from_pdf(client, analysis, pdf_text, existing_pages=page_count)

    console.print(f"[green]✓[/green] Outline ready — [bold]{len(outline.get('sections', []))}[/bold] sections\n")
    display_outline(outline)

    console.print(f"[dim]Generating {len(outline.get('sections', []))} sections + bibliography…[/dim]\n")
    concurrency, cache_enabled = prompt_runtime_options()
    latex_content = collect_generated_paper(
        client,
        mathematician,
        outline,
        existing_context=pdf_text,
        concurrency=concurrency,
        cache_enabled=cache_enabled,
    )

    save_and_compile(latex_content, mathematician, "en")


# ── Entry point ───────────────────────────────────────────────────────────────

def confirm_academic_integrity() -> None:
    """Display an academic integrity warning and require the user to type 'yes' to proceed."""
    console.print(
        Panel(
            "[bold yellow]⚠  学术诚信警告 / Academic Integrity Warning[/bold yellow]\n\n"
            "本工具生成的内容（.tex / .pdf）[bold red]严禁[/bold red]直接复制或简单转述后提交为课程作业。\n"
            "The content generated by this tool (.tex / .pdf) must [bold red]NOT[/bold red] be submitted\n"
            "as coursework by direct copying or paraphrasing.\n\n"
            "[dim]• 禁止将 AI 输出作为论文主体直接提交\n"
            "• 禁止使用 AI 编造的文献（请自行核实所有参考文献）\n"
            "• 如在学习中使用了 AI，必须在附录中注明工具、用途与核验方式\n"
            "• Fabricated references must be independently verified before any academic use\n"
            "• Any legitimate AI-assisted academic work requires a disclosure appendix[/dim]",
            border_style="yellow",
        )
    )
    console.print("[dim]本项目仅供娱乐与技术学习。/ This project is for entertainment and technical learning only.[/dim]\n")
    answer = Prompt.ask(
        "输入 [bold]yes[/bold] 表示你承诺不将生成内容违规用于学术提交，否则退出\n"
        "[dim]Type [bold]yes[/bold] to confirm you will not misuse generated content for academic submission[/dim]"
    )
    if answer.strip().lower() != "yes":
        console.print("[yellow]已退出。/ Aborted.[/yellow]")
        sys.exit(0)
    console.print()


def main() -> None:
    console.print(
        Panel.fit(
            "[bold blue]MathHistoria[/bold blue]\n"
            "[dim]AI-Powered Mathematics History Paper Generator[/dim]",
            border_style="blue",
        )
    )

    confirm_academic_integrity()

    if not config.API_KEY:
        console.print(
            "[red]Error:[/red] API_KEY is not set.\n"
            "Copy [bold].env.example[/bold] to [bold].env[/bold] and fill in your credentials."
        )
        sys.exit(1)

    client = OpenAI(api_key=config.API_KEY, base_url=config.BASE_URL)
    console.print(f"[dim]Model: {config.MODEL}  |  Endpoint: {config.BASE_URL}[/dim]\n")

    # Mode selection
    mode_table = Table(box=box.SIMPLE, show_header=False)
    mode_table.add_column("#", style="cyan bold", width=4)
    mode_table.add_column("Mode")
    mode_table.add_column("Description", style="dim")
    mode_table.add_row("1", "Start fresh", "Pick a mathematician and generate a full 50+ page paper")
    mode_table.add_row("2", "Expand from PDF", "Upload an existing outline or partial paper — the agent continues and expands it")
    console.print(mode_table)

    mode = IntPrompt.ask("Select mode", default=1)

    try:
        if mode == 2:
            flow_from_pdf(client)
        else:
            flow_fresh(client)
    except KeyboardInterrupt:
        console.print("\n[yellow]Aborted.[/yellow]")
        sys.exit(0)
    except Exception as e:
        console.print(f"\n[red]Error:[/red] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

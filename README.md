# MathHistoria

> [!NOTE]
> 本项目仅供娱乐与技术学习，不对任何实际使用场景负责。

> [!WARNING]
> **学术诚信声明 / Academic Integrity Notice**
>
> 本工具生成的任何内容（包括但不限于 `.tex` 文件、`.pdf` 文件）**不得**直接复制或简单转述后用于提交数学史课程作业。根据通行的课程 AI 使用规范：
> - **禁止**：将 AI 输出直接复制或简单转述后作为论文主体提交；使用 AI 编造的文献、引文或参考文献（请务必核实所有参考文献的真实性）
> - **允许**：选题头脑风暴、提纲建议、文献关键词建议；仅限表达层面的语言润色与格式检查
> - **附录要求**：凡使用了 AI 工具，**必须**在论文附录中创建《AI 使用情况》附录，注明所用工具名称/版本、用途、AI 参与的范围，以及你如何核验与修改，并附上与 AI 的完整对话记录。
>
> 直接提交 AI 生成内容是**严重的学术不端行为**，后果由使用者自行承担。

> [!TIP]
> **btw 友情提示**：本工具生成的论文页数可能偏多、参考文献可能存在编造或错误、行文风格也未必符合真正数学史论文的学术规范。请把它当成一份**需要认真删节和修改的草稿**，出于基本的学术素养，你务必人工审核并逐条核实所有引用文献的真实性。
>
> **btw — a friendly reminder:** The generated paper may be too long, references may be fabricated or inaccurate, and the writing style may not match the conventions of a real history-of-mathematics paper. Treat it as **a draft that needs serious editing and trimming**. As a matter of basic academic integrity, you must review it manually and verify every cited reference independently.


An AI-powered command-line tool that automatically generates comprehensive, **50+ page academic papers** on the history of mathematics. Pick a mathematician, and the agent iteratively calls a remote LLM to produce a fully formatted LaTeX document — then compiles it into a PDF.

## Features

- **15 built-in topic suggestions** covering major post-Euler mathematicians (Gauss, Riemann, Cantor, Noether, Turing, …), plus free-form input
- **Structured generation pipeline**: outline → section-by-section content → bibliography → PDF
- **Any OpenAI-compatible API** — works with Claude, Gemini, GPT-4, and any proxy that speaks the OpenAI protocol
- **Rich CLI** with progress bars and live feedback
- **Auto-compiled PDF** via `pdflatex` / `xelatex` (if installed)

## Demo

```
╭────────────────────────────────────────────────╮
│ MathHistoria                                   │
│ AI-Powered Mathematics History Paper Generator │
╰────────────────────────────────────────────────╯

Suggested topics (mathematicians after Euler, 1707–1783):

 #    Mathematician             Years       Focus Areas
 1    Carl Friedrich Gauss      1777–1855   Number theory, Gaussian curvature, …
 2    Augustin-Louis Cauchy     1789–1857   Complex analysis, rigorous calculus, …
 5    Bernhard Riemann          1826–1866   Riemann hypothesis, differential geometry, …
 …
 0    Custom topic              —           Enter your own mathematician

Select a topic number (0 for custom) (5): 5

Step 1 / 3 — Generating Outline
✓ Outline ready — 12 sections

Step 2 / 3 — Generating Paper Content
  Section 12/12: Modern Legacy …  ━━━━━━━━━━━━━━━━━━━━━━━━━━  100%

Step 3 / 3 — Compiling PDF
  Pass 1/2 (pdflatex)…
  Pass 2/2 (pdflatex)…
╭─────────────────────────────────────────╮
│ PDF generated successfully! (71 pages)  │
│ output/Bernhard_Riemann.pdf             │
╰─────────────────────────────────────────╯
```

## Prerequisites

| Requirement | Notes |
|---|---|
| Python ≥ 3.10 | |
| [uv](https://docs.astral.sh/uv/) | Dependency & venv manager |
| An OpenAI-compatible API key | Claude, Gemini, GPT-4, or any proxy |
| LaTeX (optional) | For PDF compilation. Install [MacTeX](https://tug.org/mactex/) (macOS) or `texlive-full` (Linux). Without it, a `.tex` file is still produced. |

## Installation

```bash
# 1. Clone the repository
git clone https://github.com/YOUR_USERNAME/MathHistoria.git
cd MathHistoria

# 2. Create virtual environment and install dependencies
uv sync

# 3. Configure your API credentials
cp .env.example .env
# Edit .env and fill in your API_KEY, BASE_URL, and MODEL
```

## Configuration

Copy `.env.example` to `.env` and set the following variables:

```env
# Your API key (OpenAI-compatible)
API_KEY=sk-...

# Base URL of your provider (examples below)
BASE_URL=https://api.openai.com/v1          # OpenAI
# BASE_URL=https://api.anthropic.com/v1     # Anthropic (via proxy)
# BASE_URL=https://your-proxy.com/v1        # Any OpenAI-compatible proxy

# Model name as your provider calls it
MODEL=gpt-4o
# MODEL=gemini-2.5-pro
# MODEL=claude-sonnet-4-5-20250929

# Output directory (default: output/)
OUTPUT_DIR=output
```

> **Tip:** To see which models your provider offers, run:
> ```bash
> uv run python -c "
> from openai import OpenAI
> import config
> client = OpenAI(api_key=config.API_KEY, base_url=config.BASE_URL)
> for m in sorted(client.models.list().data, key=lambda x: x.id):
>     print(m.id)
> "
> ```

## Usage

```bash
uv run python main.py
```

Follow the interactive prompts:

1. **Select a topic** — choose a number from the suggestion table, or enter `0` for a custom mathematician
2. **Wait** — the agent generates the outline, then each section in sequence (this takes a few minutes)
3. **Get your PDF** — the compiled paper is saved to `output/<Mathematician_Name>.pdf`

If LaTeX is not installed, the `.tex` source file is saved and you can compile it manually:

```bash
pdflatex -output-directory output output/Bernhard_Riemann.tex
pdflatex -output-directory output output/Bernhard_Riemann.tex  # run twice for cross-references
```

## Project Structure

```
MathHistoria/
├── main.py               # Entry point — CLI orchestration
├── config.py             # Loads .env configuration
├── agents/
│   ├── suggester.py      # Hardcoded list of 15 mathematician topics
│   ├── outline.py        # LLM call: generates structured JSON outline
│   ├── generator.py      # LLM calls: generates LaTeX section by section
│   └── compiler.py       # Runs pdflatex/xelatex to produce the PDF
├── pyproject.toml        # uv project config & dependencies
├── .env.example          # Configuration template
└── README.md
```

## Model Recommendations

| Model | Quality | Speed | Notes |
|---|---|---|---|
| `claude-opus-4-6` | ★★★★★ | Slow | Best academic prose |
| `gpt-4o` | ★★★★☆ | Medium | Reliable LaTeX output |
| `gemini-2.5-pro` | ★★★★☆ | Medium | Good for long documents |
| `gemini-3-flash` | ★★★☆☆ | Fast | Budget option |

## License

MIT

---

# MathHistoria（中文说明）

> **本项目仅供娱乐与技术学习，不对任何实际使用场景负责。**

> [!WARNING]
> **学术诚信警告**
>
> 本工具生成的任何内容（包括但不限于 `.tex` 文件、`.pdf` 文件）**严禁**直接复制或简单转述后用于提交数学史课程作业，此类行为构成**严重学术不端**，后果由使用者自行承担。
>
> 根据课程 AI 使用规范：
> - ❌ **禁止**：让 AI 代写论文主体后直接提交；将 AI 输出直接复制或简单转述后作为论文内容提交；使用 AI 编造的文献、引文或参考文献（**请务必核实所有参考文献的真实性**）；在 AI 工具中输入敏感信息或涉密材料。
> - ✅ **允许**：选题头脑风暴、提纲建议、文献关键词建议；仅限表达层面的语言润色与格式检查。
> - 📋 **附录要求（只要用了 AI 就必须做）**：在论文附录中创建《AI 使用情况》附录，第一段为"AI 使用声明"，需说明：① 使用了哪些工具（名称/版本）及用途；② AI 参与的范围（哪些段落或环节）；③ 你如何核验与修改。并附上与 AI 的完整对话记录（截图或复制粘贴均可，包含日期、问题、回复、最终采用/未采用的部分）。附录不计入篇幅。

> **btw 友情提示**：本工具生成的论文页数可能偏多、参考文献可能存在编造或错误、行文风格也未必符合真正数学史论文的学术规范。请把它当成一份**需要认真删节和修改的草稿**，出于基本的学术素养，你务必人工审核并逐条核实所有引用文献的真实性。

一款 AI 驱动的命令行工具，能自动生成 **50 页以上的数学史学术论文**。选择一位数学家，智能体就会逐节调用大语言模型（LLM），生成完整的 LaTeX 文档并编译为 PDF。

## 功能特性

- **15 个内置选题**，涵盖欧拉之后的主要数学家（高斯、黎曼、康托尔、诺特、图灵……），也支持自由输入
- **结构化生成流程**：大纲 → 逐节内容 → 参考文献 → PDF
- **任意 OpenAI 兼容 API**——支持 Claude、Gemini、GPT-4 及任何兼容 OpenAI 协议的代理接口
- **续写已有 PDF**——上传已有大纲或不完整论文，智能体自动续写并扩展至 50 页以上
- **富文本命令行界面**，带进度条和实时反馈
- **自动编译 PDF**（需安装 `pdflatex` / `xelatex`；未安装时仍会生成 `.tex` 源文件）

## 使用演示

```
╭────────────────────────────────────────────────╮
│ MathHistoria                                   │
│ AI-Powered Mathematics History Paper Generator │
╰────────────────────────────────────────────────╯

  1   从头生成     选择一位数学家，生成完整 50+ 页论文
  2   基于 PDF 续写   上传已有大纲或部分论文，智能体继续并扩展

Select mode (1): 1

Suggested topics (mathematicians after Euler, 1707–1783):

 #    Mathematician             Years       Focus Areas
 5    Bernhard Riemann          1826–1866   Riemann hypothesis, differential geometry, …
 …
Select a topic number (0 for custom) (5): 5

Step 1 / 3 — Generating Outline
✓ Outline ready — 12 sections

Step 2 / 3 — Generating Paper Content
  Section 12/12: Modern Legacy …  ━━━━━━━━━━━━━━━━━━━━━━━━━━  100%

Step 3 / 3 — Compiling PDF
╭─────────────────────────────────────────╮
│ PDF generated successfully! (71 pages)  │
│ output/Bernhard_Riemann.pdf             │
╰─────────────────────────────────────────╯
```

## 环境要求

| 依赖 | 说明 |
|---|---|
| Python ≥ 3.10 | |
| [uv](https://docs.astral.sh/uv/) | 依赖与虚拟环境管理 |
| OpenAI 兼容的 API Key | Claude、Gemini、GPT-4 或任意代理均可 |
| LaTeX（可选） | 用于编译 PDF。macOS 安装 [MacTeX](https://tug.org/mactex/)，Linux 安装 `texlive-full`。未安装时仍生成 `.tex` 文件 |

## 安装步骤

```bash
# 1. 克隆仓库
git clone https://github.com/YOUR_USERNAME/MathHistoria.git
cd MathHistoria

# 2. 创建虚拟环境并安装依赖
uv sync

# 3. 配置 API 凭据
cp .env.example .env
# 编辑 .env，填写 API_KEY、BASE_URL 和 MODEL
```

## 配置说明

将 `.env.example` 复制为 `.env`，填写以下变量：

```env
# 你的 API Key（OpenAI 兼容格式）
API_KEY=sk-...

# 提供商的 Base URL（示例）
BASE_URL=https://api.openai.com/v1          # OpenAI 官方
# BASE_URL=https://your-proxy.com/v1        # 任意 OpenAI 兼容代理

# 模型名称（与提供商保持一致）
MODEL=gpt-4o
# MODEL=gemini-2.5-pro
# MODEL=claude-opus-4-6

# 输出目录（默认：output/）
OUTPUT_DIR=output
```

> **提示：** 查看当前提供商支持的模型列表：
> ```bash
> uv run python -c "
> from openai import OpenAI
> import config
> client = OpenAI(api_key=config.API_KEY, base_url=config.BASE_URL)
> for m in sorted(client.models.list().data, key=lambda x: x.id):
>     print(m.id)
> "
> ```

## 使用方法

```bash
uv run python main.py
```

按照交互提示操作：

**模式一：从头生成**
1. 选择选题——从建议列表中选号，或输入 `0` 自定义数学家
2. 等待——智能体先生成大纲，再逐节生成内容（通常需要几分钟）
3. 获取 PDF——编译完成的论文保存在 `output/<数学家名>.pdf`

**模式二：基于已有 PDF 续写**
1. 输入你的 PDF 文件路径（大纲或不完整论文均可）
2. 智能体自动分析现有内容，识别已覆盖的章节和缺失的主题
3. 基于分析结果生成扩展大纲并续写，产出完整的 50+ 页论文

若未安装 LaTeX，`.tex` 源文件会保存在本地，可手动编译：

```bash
pdflatex -output-directory output output/Bernhard_Riemann.tex
pdflatex -output-directory output output/Bernhard_Riemann.tex  # 运行两次以生成目录和交叉引用
```

## 项目结构

```
MathHistoria/
├── main.py               # 入口文件——CLI 交互与流程调度
├── config.py             # 读取 .env 配置
├── agents/
│   ├── suggester.py      # 15 位数学家的内置建议列表
│   ├── outline.py        # LLM 调用：生成结构化 JSON 大纲
│   ├── generator.py      # LLM 调用：逐节生成 LaTeX 内容
│   ├── pdf_reader.py     # 从已有 PDF 提取文本并分析
│   └── compiler.py       # 调用 pdflatex/xelatex 生成 PDF
├── pyproject.toml        # uv 项目配置与依赖声明
├── .env.example          # 配置模板
└── README.md
```

## 模型推荐

| 模型 | 质量 | 速度 | 备注 |
|---|---|---|---|
| `claude-opus-4-6` | ★★★★★ | 较慢 | 学术写作质量最佳 |
| `gpt-4o` | ★★★★☆ | 中等 | LaTeX 输出稳定 |
| `gemini-2.5-pro` | ★★★★☆ | 中等 | 适合长文档生成 |
| `gemini-3-flash` | ★★★☆☆ | 较快 | 经济实惠的选择 |

## 许可证

MIT

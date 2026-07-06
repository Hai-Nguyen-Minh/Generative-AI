"""
ui/app.py
---------
Gradio-based web interface for UTcoder.

Features:
- Drag-and-drop or click-to-upload source file
- Auto-detected language badge
- Streaming LLM output rendered as a code block
- One-click download of the generated test file
- Live status bar with model name and ChromaDB state
"""

from __future__ import annotations

import logging
import os
import tempfile
import time
from pathlib import Path

import gradio as gr

from core.code_parser import LANGUAGE_ICONS, detect_language
from core.config import get_config
from core.generator import generate_unit_tests
from core.llm import get_model_name
from core.runner import run_test_suite, check_environment, bootstrap_environment

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _lang_badge(file_name: str) -> str:
    lang = detect_language(file_name)
    cfg  = get_config().get("languages", {}).get(lang, {})
    icon = LANGUAGE_ICONS.get(lang, "📄")
    display = cfg.get("display", lang.title())
    framework = cfg.get("test_framework", "")
    return f"{icon} **{display}**  ·  framework: `{framework}`"


def _output_filename(original: str) -> str:
    lang = detect_language(original)
    cfg  = get_config().get("languages", {}).get(lang, {})
    suffix = cfg.get("file_suffix", "_test" + Path(original).suffix)
    stem = Path(original).stem
    return f"{stem}{suffix}"


def _write_temp(content: str, filename: str) -> str:
    """Write content to a named temp file and return its path."""
    suffix = Path(filename).suffix
    fd, path = tempfile.mkstemp(suffix=suffix, prefix=Path(filename).stem + "_")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def get_envs_status_html() -> str:
    html_lines = []
    html_lines.append('<div class="env-status-list" style="margin-top: 16px; display: flex; flex-direction: column; gap: 8px;">')
    html_lines.append('<span style="color:#64748b;font-size:.72rem;text-transform:uppercase;letter-spacing:.07em">RUNNER ENVIRONMENTS</span>')
    for lang in ["python", "java", "csharp", "javascript"]:
        res = check_environment(lang)
        status = res.get("status", "missing")
        details = res.get("details", "")
        
        status_color = "var(--success)" if status == "ready" else "var(--danger)"
        display_name = {"python": "Python", "java": "Java", "csharp": "C#", "javascript": "JavaScript"}[lang]
        
        html_lines.append(
            f'<div class="info-tile" style="display: flex; justify-content: space-between; align-items: center; padding: 8px 12px !important;">'
            f'<div>'
            f'<span style="font-weight: 600; font-size: 0.82rem; color: var(--text-1);">{display_name}</span><br>'
            f'<span style="font-size: 0.72rem; color: var(--text-3); display: inline-block; max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="{details}">{details}</span>'
            f'</div>'
            f'<span style="font-size: 0.8rem; font-weight: bold; color: {status_color};">{status.upper()}</span>'
            f'</div>'
        )
    html_lines.append('</div>')
    return "\n".join(html_lines)


def generate_coverage_html(source_code: str, covered_lines: list[int], uncovered_lines: list[int]) -> str:
    if not source_code:
        return "<div style='color: var(--text-3); text-align: center; padding: 40px;'>Upload a file and run tests to view code coverage.</div>"
    
    import html
    lines = source_code.splitlines()
    
    html_lines = []
    html_lines.append('<div class="coverage-container">')
    for i, line in enumerate(lines, 1):
        line_class = ""
        badge = ""
        if i in covered_lines:
            line_class = "line-covered"
            badge = '<span class="cov-badge covered">✓</span>'
        elif i in uncovered_lines:
            line_class = "line-uncovered"
            badge = '<span class="cov-badge uncovered">✗</span>'
        else:
            line_class = "line-neutral"
            badge = '<span class="cov-badge neutral"></span>'
            
        escaped_line = html.escape(line)
        if not escaped_line:
            escaped_line = "&nbsp;"
            
        html_lines.append(
            f'<div class="cov-line {line_class}">'
            f'<span class="cov-ln">{i}</span>'
            f'{badge}'
            f'<pre class="cov-code"><code>{escaped_line}</code></pre>'
            f'</div>'
        )
    html_lines.append('</div>')
    return "\n".join(html_lines)


# ---------------------------------------------------------------------------
# Event handlers
# ---------------------------------------------------------------------------

def on_file_upload(file_obj):
    """React to file upload: detect language, show info badge, and store source code."""
    if file_obj is None:
        return gr.update(value="", visible=False), gr.update(interactive=False), "", ""
    badge = _lang_badge(Path(file_obj.name).name)
    file_path = Path(file_obj.name)
    try:
        source_code = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        source_code = f"Error reading file: {exc}"
    return gr.update(value=badge, visible=True), gr.update(interactive=True), source_code, file_path.name


def on_generate(file_obj):
    """
    Streaming generator that:
    1. Reads the uploaded file
    2. Calls generate_unit_tests() which indexes to ChromaDB and streams LLM
    3. Yields (accumulated_code, status_text, download_update, state_code, run_btn_update) progressively
    """
    if file_obj is None:
        yield "", "⚠️ Please upload a source file first.", gr.update(visible=False), "", gr.update(interactive=False)
        return

    file_path = Path(file_obj.name)
    file_name = file_path.name

    try:
        source_code = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        yield "", f"❌ Could not read file: {exc}", gr.update(visible=False), "", gr.update(interactive=False)
        return

    lang = detect_language(file_name)
    cfg  = get_config().get("languages", {}).get(lang, {})
    framework = cfg.get("test_framework", "")
    model = get_model_name()

    accumulated = ""
    out_filename = _output_filename(file_name)

    yield accumulated, f"⚙️ Indexing `{file_name}` into ChromaDB…", gr.update(visible=False), "", gr.update(interactive=False)

    try:
        for token in generate_unit_tests(file_name, source_code):
            accumulated += token
            yield (
                accumulated,
                f"🤖 Generating `{out_filename}` with **{model}** ({framework})…",
                gr.update(visible=False),
                "",
                gr.update(interactive=False),
            )
    except Exception as exc:
        logger.exception("Generation failed")
        yield accumulated, f"❌ Generation error: {exc}", gr.update(visible=False), "", gr.update(interactive=False)
        return

    # Write temp file for download
    tmp_path = _write_temp(accumulated, out_filename)
    yield (
        accumulated,
        f"✅ Done! Generated **{out_filename}** · {len(accumulated.splitlines())} lines",
        gr.update(visible=True, value=tmp_path, label=f"⬇ Download  {out_filename}"),
        accumulated,
        gr.update(interactive=True),
    )


def on_run_tests(source_code, generated_code, source_filename):
    if not source_code or not generated_code or not source_filename:
        yield (
            "⚠️ Missing code. Please upload a source file and generate unit tests first.",
            "<div style='color: var(--text-3); text-align: center; padding: 20px;'>Missing source or test files.</div>",
            "<div style='color: var(--text-3); text-align: center; padding: 20px;'>Missing source or test files.</div>",
            ""
        )
        return
        
    lang = detect_language(source_filename)
    test_filename = _output_filename(source_filename)
    
    yield (
        f"🏃 Running compilation & unit tests for `{source_filename}`...",
        "<div class='metric-card'><span class='metric-val'>Running...</span></div>",
        "<div style='color: var(--text-3); text-align: center; padding: 20px;'>Executing runner...</div>",
        ""
    )
    
    start_time = time.time()
    try:
        result = run_test_suite(lang, source_code, generated_code, source_filename, test_filename)
        duration = time.time() - start_time
    except Exception as exc:
        duration = time.time() - start_time
        logger.exception("Failed executing test suite")
        yield (
            f"❌ Execution error: {exc}",
            f"<div class='metric-card' style='border-color: var(--danger);'><span class='metric-val' style='color: var(--danger);'>Error</span><div class='metric-details'>{exc}</div></div>",
            "<div style='color: var(--text-3); text-align: center; padding: 20px;'>Execution failed. Check console.</div>",
            f"Error running test suite: {exc}"
        )
        return
        
    # Build summary dashboard
    pct = result.coverage_summary.get("pct", 0.0)
    passed = result.test_summary.get("passed", 0)
    failed = result.test_summary.get("failed", 0)
    total = result.test_summary.get("total", 0)
    
    test_status_class = "test-status-pass" if failed == 0 and total > 0 else "test-status-fail"
    compilation_status = "success" if result.compilation_success else "failed"
    
    dashboard_html = f"""
    <div class="metrics-grid">
      <div class="metric-card coverage-card">
        <div class="metric-val">{pct}%</div>
        <div class="metric-lbl">CODE COVERAGE</div>
        <div class="progress-bar-container">
          <div class="progress-bar-fill" style="width: {pct}%"></div>
        </div>
      </div>
      <div class="metric-card test-card {test_status_class}">
        <div class="metric-val">{passed}/{total}</div>
        <div class="metric-lbl">TESTS PASSED</div>
        <div class="metric-details">{failed} failed</div>
      </div>
      <div class="metric-card duration-card">
        <div class="metric-val">{duration:.2f}s</div>
        <div class="metric-lbl">EXECUTION TIME</div>
        <div class="metric-details">compiler: {compilation_status}</div>
      </div>
    </div>
    """
    
    # Generate coverage visualization
    if result.compilation_success:
        coverage_html = generate_coverage_html(source_code, result.covered_lines, result.uncovered_lines)
    else:
        coverage_html = f"""
        <div style="color: var(--danger); border: 1px solid rgba(239,68,68,0.2); background: rgba(239,68,68,0.05); padding: 20px; border-radius: 8px; font-family: 'Inter', sans-serif;">
          <h3 style="margin-top: 0; color: var(--danger);">❌ Compilation Failed</h3>
          <p style="color: var(--text-2); font-size: 0.9rem;">The code failed to compile. Please inspect the Compilation Error in the Console Output below.</p>
        </div>
        """
        
    status_msg = f"✅ Done! Coverage: {pct}% · Passed: {passed}/{total}"
    if not result.compilation_success:
        status_msg = "❌ Compilation failed."
        
    yield (
        status_msg,
        dashboard_html,
        coverage_html,
        result.test_output
    )


def on_bootstrap_env():
    """Sequentially bootstrap any missing runner environments."""
    yield gr.update(interactive=False, value="⚙️ Bootstrapping..."), get_envs_status_html()
    
    for lang in ["python", "java", "csharp", "javascript"]:
        status_res = check_environment(lang)
        if status_res.get("status") == "missing":
            yield gr.update(value=f"⚙️ Setting up {lang.title()}..."), get_envs_status_html()
            try:
                bootstrap_environment(lang)
            except Exception as e:
                logger.error(f"Failed to bootstrap {lang}: {e}")
                
    yield gr.update(interactive=True, value="🔧 Bootstrap Runner Environments"), get_envs_status_html()


def on_clear():
    return (
        "", # code_output
        "", # status_bar
        gr.update(visible=False), # btn_download
        gr.update(visible=False), # lang_badge
        gr.update(interactive=False), # btn_generate
        gr.update(interactive=False), # btn_run_tests
        "<div style='color: var(--text-3); text-align: center; padding: 20px;'>Run tests to view coverage statistics.</div>", # coverage_dashboard
        "<div style='color: var(--text-3); text-align: center; padding: 20px;'>Run tests to see highlighted covered lines.</div>", # coverage_code_view
        "", # console_output
        "Ready.", # run_status_bar
        "", # source_code_state
        "", # generated_code_state
        ""  # source_filename_state
    )


# ---------------------------------------------------------------------------
# Custom CSS — dark premium theme
# ---------------------------------------------------------------------------

CUSTOM_CSS = """
/* ── Google Font ── */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

/* ── Root variables ── */
:root {
    --bg-root:    #0b0d17;
    --bg-panel:   #111320;
    --bg-card:    #161929;
    --bg-input:   #1c2035;
    --border:     #252a45;
    --border-glow:#4f46e5;
    --primary:    #6366f1;
    --primary-h:  #818cf8;
    --accent:     #06b6d4;
    --success:    #10b981;
    --warning:    #f59e0b;
    --danger:     #ef4444;
    --text-1:     #e2e8f0;
    --text-2:     #94a3b8;
    --text-3:     #64748b;
    --radius:     12px;
    --shadow:     0 4px 24px rgba(0,0,0,.5);
}

/* ── Global ── */
body, .gradio-container {
    background: var(--bg-root) !important;
    font-family: 'Inter', sans-serif !important;
    color: var(--text-1) !important;
}

/* ── Header gradient ── */
#utcoder-header {
    background: linear-gradient(135deg, #1e1b4b 0%, #0f172a 50%, #0c1a2e 100%);
    border-bottom: 1px solid var(--border);
    padding: 28px 36px 20px;
    border-radius: var(--radius) var(--radius) 0 0;
    margin-bottom: 4px;
}
#utcoder-header h1 {
    font-size: 2rem;
    font-weight: 700;
    background: linear-gradient(90deg, #818cf8, #06b6d4);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    margin: 0 0 4px 0;
}
#utcoder-header p {
    color: var(--text-2);
    font-size: 0.9rem;
    margin: 0;
}

/* ── Panels ── */
.panel-card {
    background: var(--bg-card) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--radius) !important;
    box-shadow: var(--shadow);
}

/* ── Upload area ── */
#upload-box .wrap {
    border: 2px dashed var(--border) !important;
    border-radius: var(--radius) !important;
    background: var(--bg-input) !important;
    transition: border-color .2s, background .2s;
    min-height: 140px !important;
}
#upload-box .wrap:hover {
    border-color: var(--primary) !important;
    background: rgba(99,102,241,.06) !important;
}

/* ── Buttons ── */
#btn-generate {
    background: linear-gradient(135deg, #4f46e5, #06b6d4) !important;
    border: none !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    font-size: 1rem !important;
    letter-spacing: .03em;
    transition: opacity .2s, transform .1s !important;
    color: #fff !important;
}
#btn-generate:hover { opacity: .9; transform: translateY(-1px); }
#btn-generate:active { transform: translateY(0); }

#btn-clear {
    background: transparent !important;
    border: 1px solid var(--border) !important;
    border-radius: 8px !important;
    color: var(--text-2) !important;
    font-weight: 500 !important;
    transition: border-color .2s, color .2s !important;
}
#btn-clear:hover {
    border-color: var(--primary-h) !important;
    color: var(--primary-h) !important;
}

/* ── Download button ── */
#btn-download {
    background: linear-gradient(135deg, #059669, #10b981) !important;
    border: none !important;
    border-radius: 8px !important;
    color: #fff !important;
    font-weight: 600 !important;
    transition: opacity .2s !important;
}
#btn-download:hover { opacity: .85; }

/* ── Status bar ── */
#status-bar, #run-status-bar {
    font-size: 0.82rem !important;
    color: var(--text-2) !important;
    background: var(--bg-panel) !important;
    border: 1px solid var(--border) !important;
    border-radius: 8px !important;
    padding: 6px 14px !important;
}

/* ── Language badge ── */
#lang-badge {
    background: rgba(99,102,241,.12) !important;
    border: 1px solid rgba(99,102,241,.35) !important;
    border-radius: 8px !important;
    padding: 6px 14px !important;
    font-size: 0.85rem !important;
    color: var(--primary-h) !important;
}

/* ── Code output ── */
#code-output {
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.83rem !important;
    background: #090c18 !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--radius) !important;
    min-height: 420px !important;
}
#code-output textarea {
    background: transparent !important;
    color: #c9d1d9 !important;
    font-family: 'JetBrains Mono', monospace !important;
}

/* ── Info tiles ── */
.info-tile {
    background: var(--bg-input) !important;
    border: 1px solid var(--border) !important;
    border-radius: 10px !important;
    padding: 12px 16px !important;
}

/* ── Labels ── */
label span, .label-wrap span {
    color: var(--text-2) !important;
    font-size: 0.8rem !important;
    font-weight: 500 !important;
    text-transform: uppercase;
    letter-spacing: .06em;
}

/* ── Scrollbar ── */
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: var(--bg-root); }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: var(--primary); }

/* ── Metrics Grid & Cards ── */
.metrics-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 12px;
    margin-bottom: 16px;
    margin-top: 8px;
}
.metric-card {
    background: var(--bg-input) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--radius) !important;
    padding: 16px !important;
    display: flex;
    flex-direction: column;
    align-items: center;
    text-align: center;
}
.metric-val {
    font-size: 1.8rem;
    font-weight: 700;
    line-height: 1.2;
    margin-bottom: 4px;
}
.coverage-card .metric-val {
    background: linear-gradient(90deg, #10b981, #06b6d4);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
}
.progress-bar-container {
    width: 100%;
    height: 6px;
    background: rgba(255,255,255,0.05);
    border-radius: 3px;
    margin-top: 8px;
    overflow: hidden;
}
.progress-bar-fill {
    height: 100%;
    background: linear-gradient(90deg, #10b981, #06b6d4);
    border-radius: 3px;
}
.test-status-pass .metric-val {
    color: var(--success) !important;
}
.test-status-fail .metric-val {
    color: var(--danger) !important;
}
.metric-lbl {
    font-size: 0.65rem;
    font-weight: 600;
    color: var(--text-3);
    text-transform: uppercase;
    letter-spacing: 0.08em;
}
.metric-details {
    font-size: 0.78rem;
    color: var(--text-2);
    margin-top: 4px;
}

/* ── Coverage Code Highlight ── */
.coverage-container {
    background: #090c18 !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--radius) !important;
    padding: 8px 0;
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.83rem !important;
    max-height: 480px;
    overflow-y: auto;
    white-space: pre;
    width: 100%;
}
.cov-line {
    display: flex;
    align-items: center;
    padding: 1px 8px;
    border-left: 3px solid transparent;
}
.cov-line:hover {
    background: rgba(255,255,255,0.03) !important;
}
.line-covered {
    background: rgba(16, 185, 129, 0.08) !important;
    border-left-color: var(--success) !important;
}
.line-uncovered {
    background: rgba(239, 68, 68, 0.08) !important;
    border-left-color: var(--danger) !important;
}
.cov-ln {
    color: var(--text-3);
    width: 40px;
    text-align: right;
    padding-right: 12px;
    user-select: none;
    font-size: 0.78rem;
}
.cov-badge {
    width: 18px;
    height: 18px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 0.7rem;
    font-weight: bold;
    border-radius: 50%;
    margin-right: 12px;
    user-select: none;
}
.cov-badge.covered {
    background: rgba(16, 185, 129, 0.2);
    color: #10b981;
}
.cov-badge.uncovered {
    background: rgba(239, 68, 68, 0.2);
    color: #ef4444;
}
.cov-badge.neutral {
    background: transparent;
}
.cov-code {
    margin: 0 !important;
    padding: 0 !important;
    background: transparent !important;
    color: var(--text-1) !important;
    overflow: visible !important;
    font-family: inherit !important;
}

/* ── Bootstrap Button ── */
#btn-bootstrap {
    background: var(--bg-input) !important;
    border: 1px solid var(--border) !important;
    color: var(--text-2) !important;
    font-weight: 500 !important;
    transition: all .2s !important;
    margin-top: 12px;
}
#btn-bootstrap:hover {
    border-color: var(--primary) !important;
    color: var(--text-1) !important;
}
#btn-run-tests {
    background: linear-gradient(135deg, #4f46e5, #06b6d4) !important;
    color: #fff !important;
    font-weight: 600 !important;
    border: none !important;
}
"""


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app() -> gr.Blocks:
    cfg   = get_config()
    model = get_model_name()
    chroma_dir = cfg["vectorstore"]["chroma_dir"]

    _theme = gr.themes.Base(
        primary_hue=gr.themes.colors.indigo,
        neutral_hue=gr.themes.colors.slate,
        font=["Inter", "sans-serif"],
    )

    with gr.Blocks(title="UTcoder — AI Unit Test Generator") as demo:
        # States
        source_code_state = gr.State(value="")
        generated_code_state = gr.State(value="")
        source_filename_state = gr.State(value="")

        # ── Header ────────────────────────────────────────────────────────
        gr.HTML(f"""
        <div id="utcoder-header">
            <h1>🧪 UTcoder</h1>
            <p>AI-powered unit test generator · <strong>{model}</strong> via Ollama · ChromaDB RAG</p>
        </div>
        """)

        # ── Main layout ────────────────────────────────────────────────────
        with gr.Row(equal_height=False):

            # ── Left column: inputs ──────────────────────────────────────
            with gr.Column(scale=1, min_width=320):

                gr.Markdown("### 📂 Source File", elem_classes="panel-label")

                file_input = gr.File(
                    label="Upload source file",
                    file_types=[".py", ".java", ".cs", ".js", ".jsx", ".mjs"],
                    elem_id="upload-box",
                )

                lang_badge = gr.Markdown(
                    value="",
                    visible=False,
                    elem_id="lang-badge",
                )

                with gr.Row():
                    btn_generate = gr.Button(
                        "⚡ Generate Tests",
                        variant="primary",
                        interactive=False,
                        elem_id="btn-generate",
                        scale=3,
                    )
                    btn_clear = gr.Button(
                        "✕ Clear",
                        variant="secondary",
                        elem_id="btn-clear",
                        scale=1,
                    )

                # Model info tiles
                gr.HTML(f"""
                <div style="margin-top:16px; display:flex; flex-direction:column; gap:8px;">
                  <div class="info-tile">
                    <span style="color:#64748b;font-size:.72rem;text-transform:uppercase;letter-spacing:.07em">MODEL</span><br>
                    <span style="color:#818cf8;font-weight:600;font-size:.9rem">{model}</span>
                  </div>
                  <div class="info-tile">
                    <span style="color:#64748b;font-size:.72rem;text-transform:uppercase;letter-spacing:.07em">VECTOR STORE</span><br>
                    <span style="color:#06b6d4;font-weight:600;font-size:.9rem">ChromaDB · {chroma_dir}</span>
                  </div>
                  <div class="info-tile">
                    <span style="color:#64748b;font-size:.72rem;text-transform:uppercase;letter-spacing:.07em">EMBEDDINGS</span><br>
                    <span style="color:#10b981;font-weight:600;font-size:.9rem">{model}</span>
                  </div>
                </div>
                """)

                # Runner environments
                env_status_html = gr.HTML(value=get_envs_status_html(), elem_id="env-status-panel")
                btn_bootstrap_env = gr.Button(
                    "🔧 Bootstrap Runner Environments",
                    variant="secondary",
                    elem_id="btn-bootstrap"
                )

            # ── Right column: output ─────────────────────────────────────
            with gr.Column(scale=2):
                with gr.Tabs():
                    with gr.Tab("🧪 Generated Unit Tests"):
                        code_output = gr.Code(
                            label="Test file output",
                            language="python",
                            interactive=False,
                            lines=28,
                            elem_id="code-output",
                        )

                        with gr.Row():
                            status_bar = gr.Markdown(
                                value=f"Ready · model `{model}` · ChromaDB at `{chroma_dir}`",
                                elem_id="status-bar",
                            )

                        btn_download = gr.File(
                            label="⬇ Download Test File",
                            visible=False,
                            elem_id="btn-download",
                        )

                    with gr.Tab("🏃 Test Execution & Coverage"):
                        with gr.Row():
                            btn_run_tests = gr.Button(
                                "🏃 Run Tests & Coverage",
                                variant="primary",
                                elem_id="btn-run-tests",
                                interactive=False,
                            )
                        
                        run_status_bar = gr.Markdown(
                            value="Ready to run tests.",
                            elem_id="run-status-bar",
                        )

                        gr.Markdown("### 📊 Metrics Summary")
                        coverage_dashboard = gr.HTML(
                            value="<div style='color: var(--text-3); text-align: center; padding: 20px;'>Run tests to view coverage statistics.</div>",
                            elem_id="coverage-dashboard",
                        )

                        gr.Markdown("### 🔍 Code Coverage Visualizer")
                        coverage_code_view = gr.HTML(
                            value="<div style='color: var(--text-3); text-align: center; padding: 20px;'>Run tests to see highlighted covered lines.</div>",
                            elem_id="coverage-code-view",
                        )

                        with gr.Accordion("💻 Test Execution Console Output", open=False):
                            console_output = gr.Code(
                                label="Terminal stdout/stderr",
                                interactive=False,
                                lines=15,
                            )

        # ── Event wiring ───────────────────────────────────────────────────

        file_input.change(
            fn=on_file_upload,
            inputs=[file_input],
            outputs=[lang_badge, btn_generate, source_code_state, source_filename_state],
        )

        btn_generate.click(
            fn=on_generate,
            inputs=[file_input],
            outputs=[code_output, status_bar, btn_download, generated_code_state, btn_run_tests],
        )

        btn_clear.click(
            fn=on_clear,
            inputs=[],
            outputs=[
                code_output, status_bar, btn_download, lang_badge, btn_generate, btn_run_tests,
                coverage_dashboard, coverage_code_view, console_output, run_status_bar,
                source_code_state, generated_code_state, source_filename_state
            ],
        )

        btn_run_tests.click(
            fn=on_run_tests,
            inputs=[source_code_state, generated_code_state, source_filename_state],
            outputs=[run_status_bar, coverage_dashboard, coverage_code_view, console_output],
        )

        btn_bootstrap_env.click(
            fn=on_bootstrap_env,
            inputs=[],
            outputs=[btn_bootstrap_env, env_status_html],
        )

    return demo, _theme, CUSTOM_CSS

"""
ui/app.py
---------
Gradio-based web interface for UTcoder.

Features:
- Drag-and-drop or click-to-upload source file
- Auto-detected language badge
- Streaming LLM output rendered as a code block
- One-click download of the generated test file
- AI-based compile check (without real compiler)
- AI-based coverage analysis (without running tests)
- Live status bar with model name and ChromaDB state
- JSON export of analysis results
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

import gradio as gr

from core.code_parser import LANGUAGE_ICONS, detect_language
from core.config import get_config
from core.generator import generate_unit_tests
from core.llm import get_model_name

# ── NEW AI analysis modules ──
from core.compiler import compile_check, quick_assessment
from core.coverager import analyse_coverage, coverage_summary

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clean_generated_code(code: str) -> str:
    """Clean LLM output to extract only the test code."""
    import re

    fence_match = re.search(r"```(?:\w+)?\s*\n(.*?)\n```", code, re.DOTALL)
    if fence_match:
        code = fence_match.group(1)

    code = re.sub(r"\A(?:#.*\n?)+", "", code)
    code = re.sub(r"\A\s*/\*[\s\S]*?\*/\s*", "", code)
    while re.match(r"\s*//", code):
        code = re.sub(r"\A\s*//.*\n?", "", code)

    code = re.sub(r"(?:^#.*\n?)+$", "", code, flags=re.MULTILINE)
    code = re.sub(r"\s*/\*[\s\S]*?\*/\s*$", "", code)
    code = re.sub(r"(?:\s*//.*\n?)+$", "", code)

    return code.strip()


def _lang_badge(file_name: str) -> str:
    lang = detect_language(file_name)
    cfg = get_config().get("languages", {}).get(lang, {})
    icon = LANGUAGE_ICONS.get(lang, "📄")
    display = cfg.get("display", lang.title())
    framework = cfg.get("test_framework", "")
    return f"{icon} **{display}**  ·  framework: `{framework}`"


def _output_filename(original: str) -> str:
    lang = detect_language(original)
    cfg = get_config().get("languages", {}).get(lang, {})
    suffix = cfg.get("file_suffix", "_test" + Path(original).suffix)
    stem = Path(original).stem
    return f"{stem}{suffix}"


_EXT_TO_GRADIO_LANG = {
    ".py": "python",
    ".java": "python",
    ".cs": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".hpp": "cpp",
}


def _gradio_lang(filename: str) -> str | None:
    return _EXT_TO_GRADIO_LANG.get(Path(filename).suffix.lower())


def _write_temp(content: str, filename: str) -> str:
    suffix = Path(filename).suffix
    fd, path = tempfile.mkstemp(suffix=suffix, prefix=Path(filename).stem + "_")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def _build_compile_check_html(result: dict) -> str:
    """Build an HTML block for compile check results."""
    if not result:
        return "<div style='color:var(--text-3);padding:20px;text-align:center;'>No compile check data yet.</div>"

    has_issues = result.get("has_issues", False)
    issues = result.get("issues", [])
    assessment = result.get("overall_assessment", "")

    status_icon = "✅" if not has_issues else "⚠️"
    status_color = "var(--success)" if not has_issues else "var(--warning)"
    status_text = "No issues found" if not has_issues else f"{len(issues)} issue(s) found"

    html = f"""
    <div style="margin-bottom:12px;">
      <span style="font-size:1.4rem;color:{status_color};font-weight:700;">
        {status_icon} {status_text}
      </span>
    </div>
    """

    if assessment:
        html += f"<p style='color:var(--text-2);font-size:0.9rem;margin-bottom:16px;'>{assessment}</p>"

    if issues:
        html += '<div style="display:flex;flex-direction:column;gap:8px;">'
        for i, issue in enumerate(issues, 1):
            desc = issue.get("description", "Unknown issue")
            line_ref = issue.get("line_reference", "")
            suggestion = issue.get("suggestion", "")
            html += f"""
            <div style="background:rgba(245,158,11,0.06);border:1px solid rgba(245,158,11,0.2);border-radius:8px;padding:12px;">
              <div style="display:flex;justify-content:space-between;align-items:flex-start;">
                <strong style="color:var(--warning);font-size:0.85rem;">#{i}</strong>
                {f'<code style="font-size:0.78rem;color:var(--text-3);background:var(--bg-input);padding:2px 8px;border-radius:4px;">{line_ref}</code>' if line_ref else ''}
              </div>
              <p style="margin:6px 0;color:var(--text-1);font-size:0.88rem;">{desc}</p>
              {f'<p style="margin:0;color:var(--text-2);font-size:0.82rem;"><em>Suggestion:</em> {suggestion}</p>' if suggestion else ''}
            </div>
            """
        html += "</div>"

    return html


def _build_coverage_html(result: dict) -> str:
    """Build an HTML block for coverage analysis results."""
    if not result:
        return "<div style='color:var(--text-3);padding:20px;text-align:center;'>No coverage analysis yet.</div>"

    pct = result.get("coverage_pct", 0.0)
    covered_items = result.get("covered_items", [])
    uncovered_items = result.get("uncovered_items", [])
    suggestions = result.get("suggestions", [])

    # Determine color based on percentage
    if pct >= 80:
        color = "var(--success)"
    elif pct >= 50:
        color = "var(--warning)"
    else:
        color = "var(--danger)"

    html = f"""
    <div style="margin-bottom:16px;">
      <div style="display:flex;align-items:center;gap:16px;margin-bottom:8px;">
        <span style="font-size:2.5rem;font-weight:700;color:{color};">{pct:.0f}%</span>
        <div style="flex:1;height:10px;background:rgba(0,0,0,0.06);border-radius:5px;overflow:hidden;">
          <div style="width:{pct}%;height:100%;background:linear-gradient(90deg,{color},var(--accent));border-radius:5px;transition:width 0.5s;"></div>
        </div>
      </div>
    </div>
    """

    if covered_items:
        html += '<div style="margin-bottom:12px;">'
        html += '<span style="font-size:0.72rem;text-transform:uppercase;letter-spacing:0.07em;color:var(--success);font-weight:600;">✅ COVERED</span>'
        html += '<div style="display:flex;flex-wrap:wrap;gap:4px;margin-top:4px;">'
        for item in covered_items:
            html += f'<span style="background:rgba(5,150,105,0.1);color:var(--success);font-size:0.78rem;padding:2px 10px;border-radius:12px;border:1px solid rgba(5,150,105,0.2);">{item}</span>'
        html += '</div></div>'

    if uncovered_items:
        html += '<div style="margin-bottom:12px;">'
        html += '<span style="font-size:0.72rem;text-transform:uppercase;letter-spacing:0.07em;color:var(--danger);font-weight:600;">❌ UNCOVERED</span>'
        html += '<div style="display:flex;flex-wrap:wrap;gap:4px;margin-top:4px;">'
        for item in uncovered_items:
            html += f'<span style="background:rgba(220,38,38,0.07);color:var(--danger);font-size:0.78rem;padding:2px 10px;border-radius:12px;border:1px solid rgba(220,38,38,0.15);">{item}</span>'
        html += '</div></div>'

    if suggestions:
        html += '<div style="margin-top:12px;">'
        html += '<span style="font-size:0.72rem;text-transform:uppercase;letter-spacing:0.07em;color:var(--accent);font-weight:600;">💡 SUGGESTIONS</span>'
        html += '<ul style="margin:6px 0 0 0;padding-left:20px;">'
        for s in suggestions:
            html += f'<li style="color:var(--text-2);font-size:0.85rem;margin-bottom:4px;">{s}</li>'
        html += '</ul></div>'

    return html


# ---------------------------------------------------------------------------
# Event handlers
# ---------------------------------------------------------------------------


def on_file_upload(file_obj):
    """React to file upload: detect language, show info badge, and store source code."""
    if file_obj is None:
        return (
            gr.update(value="", visible=False),
            gr.update(interactive=False),
            "",
            "",
            gr.update(language=None),
            gr.update(interactive=False),
            gr.update(interactive=False),
        )
    badge = _lang_badge(Path(file_obj.name).name)
    file_path = Path(file_obj.name)
    try:
        source_code = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        source_code = f"Error reading file: {exc}"
    lang = _gradio_lang(file_path.name)
    return (
        gr.update(value=badge, visible=True),
        gr.update(interactive=True),
        source_code,
        file_path.name,
        gr.update(value=source_code, language=lang),
        gr.update(interactive=True),
        gr.update(interactive=True),
    )


def on_generate(file_obj):
    """
    Streaming generator that:
    1. Reads the uploaded file
    2. Calls generate_unit_tests() which indexes to ChromaDB and streams LLM
    3. Cleans generated code (strips markdown fences, prose, summary comments)
    4. Writes download file and shows download button
    """
    if file_obj is None:
        yield (
            gr.update(value="", language=None),
            "⚠️ Please upload a source file first.",
            "",
            gr.update(visible=False),
        )
        return

    file_path = Path(file_obj.name)
    file_name = file_path.name
    file_lang = _gradio_lang(file_name) or None

    try:
        source_code = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        yield (
            gr.update(value="", language=file_lang),
            f"❌ Could not read file: {exc}",
            "",
            gr.update(visible=False),
        )
        return

    model = get_model_name()
    accumulated = ""
    out_filename = _output_filename(file_name)

    # Step 1: Indexing
    yield (
        gr.update(value=accumulated, language=file_lang),
        f"⚙️ Indexing `{file_name}` into ChromaDB…",
        "",
        gr.update(visible=False),
    )

    # Step 2: Generate
    try:
        for token in generate_unit_tests(file_name, source_code):
            accumulated += token
            yield (
                gr.update(value=accumulated, language=file_lang),
                f"🤖 Generating `{out_filename}` with **{model}**…",
                "",
                gr.update(visible=False),
            )
    except Exception as exc:
        logger.exception("Generation failed")
        yield (
            gr.update(value=accumulated, language=file_lang),
            f"❌ Generation error: {exc}",
            "",
            gr.update(visible=False),
        )
        return

    # Step 3: Clean + write download
    cleaned = _clean_generated_code(accumulated)
    tmp_path = _write_temp(cleaned, out_filename)

    yield (
        gr.update(value=cleaned, language=file_lang),
        f"✅ Generated **{out_filename}** ({len(cleaned.splitlines())} lines)",
        cleaned,
        gr.update(visible=True, value=tmp_path, label=f"⬇ Download  {out_filename}"),
    )


def on_compile_check(source_code, generated_code, source_filename):
    """Run AI-based compile check on generated test code."""
    if not source_code or not generated_code or not source_filename:
        return (
            _build_compile_check_html({}),
            "⚠️ Please generate unit tests first.",
        )

    yield (
        "<div style='color:var(--text-3);padding:20px;text-align:center;'>🔍 Running AI compile check…</div>",
        "🔍 Analysing compilation correctness…",
    )

    try:
        result = compile_check(source_code, generated_code, source_filename)
        summary = quick_assessment(generated_code, source_filename)
        html = _build_compile_check_html(result)

        status = f"✅ Compile check: {summary}"
        if result.get("has_issues"):
            status = f"⚠️ Compile check found {len(result.get('issues', []))} issue(s) · {summary}"

        yield (html, status)
    except Exception as exc:
        logger.exception("Compile check failed")
        yield (
            f"<div style='color:var(--danger);padding:20px;'>❌ Error: {exc}</div>",
            f"❌ Compile check failed: {exc}",
        )


def on_coverage_analysis(source_code, generated_code, source_filename):
    """Run AI-based coverage analysis on generated test code."""
    if not source_code or not generated_code or not source_filename:
        return (
            _build_coverage_html({}),
            "⚠️ Please generate unit tests first.",
        )

    yield (
        "<div style='color:var(--text-3);padding:20px;text-align:center;'>📊 Running AI coverage analysis…</div>",
        "📊 Analysing test coverage…",
    )

    try:
        result = analyse_coverage(source_code, generated_code, source_filename)
        summary = coverage_summary(source_code, generated_code, source_filename)
        html = _build_coverage_html(result)

        yield (html, f"✅ {summary}")
    except Exception as exc:
        logger.exception("Coverage analysis failed")
        yield (
            f"<div style='color:var(--danger);padding:20px;'>❌ Error: {exc}</div>",
            f"❌ Coverage analysis failed: {exc}",
        )


def on_clear():
    """Reset all UI components to initial state."""
    return (
        gr.update(value="", language=None),  # code_output
        "",  # status_bar
        gr.update(visible=False),  # lang_badge
        gr.update(interactive=False),  # btn_generate
        "",  # source_code_state
        "",  # source_filename_state
        "",  # generated_code_state
        gr.update(interactive=False),  # btn_compile_check
        gr.update(interactive=False),  # btn_coverage
        _build_compile_check_html({}),  # compile_check_output
        _build_coverage_html({}),  # coverage_output
        "Ready.",  # analysis_status_bar
        gr.update(visible=False),  # btn_download_file
    )


# ---------------------------------------------------------------------------
# Custom CSS — bright / light theme
# ---------------------------------------------------------------------------

CUSTOM_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

:root {
    --bg-root:    #f6f8fa;
    --bg-panel:   #ffffff;
    --bg-card:    #ffffff;
    --bg-input:   #f1f3f5;
    --border:     #dde1e7;
    --border-glow:#6366f1;
    --primary:    #4f46e5;
    --primary-h:  #6366f1;
    --accent:     #0891b2;
    --success:    #059669;
    --warning:    #d97706;
    --danger:     #dc2626;
    --text-1:     #1e293b;
    --text-2:     #475569;
    --text-3:     #94a3b8;
    --radius:     12px;
    --shadow:     0 1px 3px rgba(0,0,0,.06), 0 1px 2px rgba(0,0,0,.04);
}

body, .gradio-container {
    background: var(--bg-root) !important;
    font-family: 'Inter', sans-serif !important;
    color: var(--text-1) !important;
}

#utcoder-header {
    background: linear-gradient(135deg, #eef2ff 0%, #f0fdf4 50%, #ecfeff 100%);
    border-bottom: 1px solid var(--border);
    padding: 28px 36px 20px;
    border-radius: var(--radius) var(--radius) 0 0;
    margin-bottom: 4px;
}
#utcoder-header h1 {
    font-size: 2rem;
    font-weight: 700;
    background: linear-gradient(90deg, #4f46e5, #0891b2);
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

.panel-card {
    background: var(--bg-card) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--radius) !important;
    box-shadow: var(--shadow);
}

#upload-box .wrap {
    border: 2px dashed var(--border) !important;
    border-radius: var(--radius) !important;
    background: var(--bg-input) !important;
    transition: border-color .2s, background .2s;
    min-height: 140px !important;
}
#upload-box .wrap:hover {
    border-color: var(--primary) !important;
    background: rgba(79,70,229,.04) !important;
}

#btn-generate {
    background: linear-gradient(135deg, #4f46e5, #0891b2) !important;
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

#status-bar, #analysis-status-bar {
    font-size: 0.82rem !important;
    color: var(--text-2) !important;
    background: var(--bg-panel) !important;
    border: 1px solid var(--border) !important;
    border-radius: 8px !important;
    padding: 6px 14px !important;
}

#lang-badge {
    background: rgba(79,70,229,.08) !important;
    border: 1px solid rgba(79,70,229,.25) !important;
    border-radius: 8px !important;
    padding: 6px 14px !important;
    font-size: 0.85rem !important;
    color: var(--primary) !important;
}

#code-output {
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.83rem !important;
    background: #ffffff !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--radius) !important;
    min-height: 320px !important;
}
#code-output textarea {
    background: transparent !important;
    color: var(--text-1) !important;
    font-family: 'JetBrains Mono', monospace !important;
}

.info-tile {
    background: var(--bg-panel) !important;
    border: 1px solid var(--border) !important;
    border-radius: 10px !important;
    padding: 12px 16px !important;
}

label span, .label-wrap span {
    color: var(--text-2) !important;
    font-size: 0.8rem !important;
    font-weight: 500 !important;
    text-transform: uppercase;
    letter-spacing: .06em;
}

::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: var(--bg-root); }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: var(--primary); }

#analysis-panel {
    background: var(--bg-panel) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--radius) !important;
    padding: 16px !important;
    min-height: 200px;
}

#btn-compile-check, #btn-coverage {
    background: linear-gradient(135deg, #4f46e5, #0891b2) !important;
    color: #fff !important;
    font-weight: 600 !important;
    border: none !important;
    border-radius: 8px !important;
    transition: opacity .2s !important;
}
#btn-compile-check:hover, #btn-coverage:hover { opacity: .9; }

.tabs button {
    background: var(--bg-input) !important;
    border: 1px solid var(--border) !important;
    color: var(--text-2) !important;
    font-weight: 500 !important;
    font-size: 0.85rem !important;
    border-radius: 8px 8px 0 0 !important;
    padding: 10px 18px !important;
    transition: all .15s !important;
}
.tabs button.selected {
    background: var(--bg-panel) !important;
    border-bottom-color: var(--bg-panel) !important;
    color: var(--primary) !important;
    font-weight: 600 !important;
}
.tabs button:hover:not(.selected) {
    background: rgba(79,70,229,.04) !important;
    color: var(--text-1) !important;
}

.markdown-text code {
    background: var(--bg-input) !important;
    color: var(--primary) !important;
    font-size: 0.85em !important;
    padding: 2px 6px !important;
    border-radius: 4px !important;
}

input, textarea, select {
    background: var(--bg-panel) !important;
    border: 1px solid var(--border) !important;
    color: var(--text-1) !important;
    border-radius: 8px !important;
}
input:focus, textarea:focus, select:focus {
    border-color: var(--primary) !important;
    box-shadow: 0 0 0 2px rgba(79,70,229,0.15) !important;
}

#btn-download-file {
    background: linear-gradient(135deg, #059669, #10b981) !important;
    border: none !important;
    border-radius: 8px !important;
    color: #fff !important;
    font-weight: 600 !important;
    transition: opacity .2s !important;
}
#btn-download-file:hover { opacity: .85; }
"""


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app() -> gr.Blocks:
    cfg = get_config()
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
            with gr.Column(scale=1, min_width=300):

                gr.Markdown("### 📂 Source File", elem_classes="panel-label")

                file_input = gr.File(
                    label="Upload source file",
                    file_types=[".py", ".java", ".cs", ".js", ".jsx", ".mjs",
                                ".cjs", ".ts", ".tsx"],
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
                <div style="display:flex;flex-direction:column;gap:8px;">
                  <div class="info-tile">
                    <span style="color:var(--text-3);font-size:.72rem;text-transform:uppercase;letter-spacing:.07em">MODEL</span><br>
                    <span style="color:var(--primary);font-weight:600;font-size:.9rem">{model}</span>
                  </div>
                  <div class="info-tile">
                    <span style="color:var(--text-3);font-size:.72rem;text-transform:uppercase;letter-spacing:.07em">VECTOR STORE</span><br>
                    <span style="color:var(--accent);font-weight:600;font-size:.9rem">ChromaDB · {chroma_dir}</span>
                  </div>
                  <div class="info-tile">
                    <span style="color:var(--text-3);font-size:.72rem;text-transform:uppercase;letter-spacing:.07em">EMBEDDINGS</span><br>
                    <span style="color:var(--success);font-weight:600;font-size:.9rem">{model}</span>
                  </div>
                </div>
                """)

            # ── Right column: output ─────────────────────────────────────
            with gr.Column(scale=2):
                with gr.Tabs():
                    with gr.Tab("🧪 Generated Unit Tests"):
                        code_output = gr.Code(
                            label="Test file output",
                            language=None,
                            interactive=False,
                            lines=20,
                            elem_id="code-output",
                        )

                        with gr.Row():
                            status_bar = gr.Markdown(
                                value=f"Ready · model `{model}` · ChromaDB at `{chroma_dir}`",
                                elem_id="status-bar",
                            )

                        with gr.Row():
                            btn_download_file = gr.DownloadButton(
                                "⬇ Download File",
                                elem_id="btn-download-file",
                                scale=1,
                                visible=False,
                            )

                    with gr.Tab("🔍 Compile Check (AI)"):
                        with gr.Row():
                            btn_compile_check = gr.Button(
                                "🔍 Run AI Compile Check",
                                variant="primary",
                                elem_id="btn-compile-check",
                                interactive=False,
                            )

                        compile_check_output = gr.HTML(
                            value=_build_compile_check_html({}),
                            elem_id="analysis-panel",
                        )

                    with gr.Tab("📊 Coverage (AI)"):
                        with gr.Row():
                            btn_coverage = gr.Button(
                                "📊 Run AI Coverage Analysis",
                                variant="primary",
                                elem_id="btn-coverage",
                                interactive=False,
                            )

                        coverage_output = gr.HTML(
                            value=_build_coverage_html({}),
                            elem_id="analysis-panel",
                        )

                # Status bar for analysis operations
                analysis_status_bar = gr.Markdown(
                    value="Ready.",
                    elem_id="analysis-status-bar",
                )

        # ── Event wiring ───────────────────────────────────────────────────

        file_input.change(
            fn=on_file_upload,
            inputs=[file_input],
            outputs=[
                lang_badge, btn_generate,
                source_code_state, source_filename_state,
                code_output,
                btn_compile_check, btn_coverage,
            ],
        )

        btn_generate.click(
            fn=on_generate,
            inputs=[file_input],
            outputs=[
                code_output, status_bar,
                generated_code_state,
                btn_download_file,
            ],
        )

        btn_compile_check.click(
            fn=on_compile_check,
            inputs=[source_code_state, generated_code_state, source_filename_state],
            outputs=[compile_check_output, analysis_status_bar],
        )

        btn_coverage.click(
            fn=on_coverage_analysis,
            inputs=[source_code_state, generated_code_state, source_filename_state],
            outputs=[coverage_output, analysis_status_bar],
        )

        btn_clear.click(
            fn=on_clear,
            inputs=[],
            outputs=[
                code_output, status_bar,
                lang_badge, btn_generate,
                source_code_state, source_filename_state,
                generated_code_state,
                btn_compile_check, btn_coverage,
                compile_check_output, coverage_output,
                analysis_status_bar,
                btn_download_file,
            ],
        )

    return demo, _theme, CUSTOM_CSS

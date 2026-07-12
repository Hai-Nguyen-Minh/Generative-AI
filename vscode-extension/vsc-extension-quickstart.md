# UTcoder VS Code Extension — Quick Start

> **📖 Full documentation available in [README.md](README.md)**

This guide covers the essential steps to install, configure, and start generating unit tests with UTcoder.

---

## Quick Setup

### 1. Prerequisites

- **Python 3.10+** with UTcoder installed
- **Ollama** running with a code model (`codellama`, `deepseek-coder`, etc.)
- **Language runtime** for your code (Python/Java/C#/JS)

### 2. Install the Extension

```bash
code --install-extension utcoder-vscode.vsix
```

### 3. Open VS Code Settings

Search for `utcoder` and set:

| Setting | Example Value |
|---------|-------------|
| `utcoder.pythonPath` | `C:\UTcoder\.venv\Scripts\python.exe` |
| `utcoder.utcoderProjectPath` | `C:\UTcoder` |

---

## Quick Start: Create Your First UT File

### Step 1 — Open a Source File

Open any `.py`, `.java`, `.cs`, `.js`, or `.ts` file in VS Code.

### Step 2 — Generate Tests

Press **`Ctrl+Alt+T`** (Mac: `Cmd+Alt+T`) — or right-click → "UTcoder: Generate Tests & Run"

### Step 3 — See Results

UTcoder will:
1. ✅ Generate a test file and open it beside your source
2. ✅ Compile and run the tests automatically
3. ✅ Show **green ✓** for covered lines and **red ✗** for uncovered lines
4. ✅ Display a detailed coverage webview report

---

## Commands Reference

| Command | Shortcut | What it does |
|---------|----------|-------------|
| Generate Tests & Run | `Ctrl+Alt+T` | Full pipeline |
| Generate Tests Only | `Ctrl+Alt+G` | Generate without running |
| Run Tests & Coverage | — | Run existing tests |
| Bootstrap Environment | — | Install runners |
| Clear ChromaDB Index | — | Clear vector index |

---

**📚 For full details: see [README.md](README.md)**

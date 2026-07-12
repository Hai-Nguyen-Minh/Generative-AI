# UTcoder — AI Unit Test Generator for VS Code

[![Version](https://img.shields.io/badge/version-0.2.0-blue)](https://marketplace.visualstudio.com/items?itemName=utcoder.utcoder-vscode)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**UTcoder** is a minimal VS Code extension that generates unit tests with one right-click.

Simply **right-click any source file** in the Explorer or Editor, and UTcoder sends the file to a remote UTcoder server which returns a complete unit test file. No compilation, no coverage, no runners — just test generation.

Supports **Python**, **Java**, **C#**, **JavaScript**, and **TypeScript**.

---

## How It Works

```
1. Right-click a source file → "UTcoder: Generate Unit Tests"
2. Extension reads file content
3. Sends it via HTTP POST to the UTcoder server API
4. Server generates unit tests using AI (RAG + LLM)
5. Test file is created alongside your source file
6. Test file opens automatically in a split editor
```

## Quick Start

**Step 1:** Make sure your UTcoder server is running:

```bash
# In the UTcoder project root:
python main.py
```

This starts the server on `http://localhost:8000`.

**Step 2:** Right-click any source file in VS Code and select **"UTcoder: Generate Unit Tests"**.

**Step 3:** The test file is created and opens beside your source.

---

## Installation

```bash
cd vscode-extension
npm install
npm run compile
npx @vscode/vsce package --out utcoder-vscode.vsix
code --install-extension utcoder-vscode.vsix
```

## Commands

| Command | Keybinding | Description |
|---------|-----------|-------------|
| `UTcoder: Generate Unit Tests` | `Ctrl+Alt+G` / `Cmd+Alt+G` | Generate tests for current file |
| `UTcoder: Check Server Health` | — | Check if the UTcoder server is reachable |

Access via:
- **Right-click** in editor or Explorer
- **Command Palette** (`Ctrl+Shift+P`) → type "UTcoder"
- **Keyboard shortcut** `Ctrl+Alt+G`

## Configuration

Open VS Code Settings (`Ctrl+,`) and search for `utcoder`:

| Setting | Default | Description |
|---------|---------|-------------|
| `utcoder.serverUrl` | `http://localhost:8000` | URL of the UTcoder HTTP server |
| `utcoder.serverTimeout` | `120000` | Timeout in ms for server requests |

## Server API

The extension expects the UTcoder server to expose these endpoints:

### `GET /api/health`
Returns server status:
```json
{ "ready": true, "message": "Model: ...", "version": "0.1.0" }
```

### `POST /api/generate`
Request body:
```json
{
  "file_name": "calculator.py",
  "source_code": "def add(a, b): ...",
  "language": "python"
}
```
Response:
```json
{
  "success": true,
  "code": "# Generated test code..."
}
```

## Development

```bash
cd vscode-extension
npm install
npm run compile   # TypeScript → JavaScript
npm run watch     # Auto-compile on changes
```

## Project Structure

```
vscode-extension/
├── src/
│   └── extension.ts    # Single-file extension (no other modules)
├── out/
│   └── extension.js    # Compiled output
├── package.json        # Extension manifest
└── tsconfig.json       # TypeScript config
```

## License

[MIT](LICENSE)

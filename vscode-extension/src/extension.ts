/**
 * UTcoder VS Code Extension
 *
 * Simplified version:
 *   - Right-click any supported file in Explorer or Editor
 *   - Sends file content to UTcoder HTTP server
 *   - Receives generated unit test code
 *   - Creates test file alongside source file
 *   - No compilation, coverage, bootstrap, or runners
 */

import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';

// ─── Constants ─────────────────────────────────────────────────────────────

const SUPPORTED_EXTENSIONS = new Set([
    '.py', '.java', '.cs',
    '.js', '.jsx', '.mjs', '.cjs',
    '.ts', '.tsx',
]);

const EXT_TO_LANG: Record<string, string> = {
    '.py': 'python',
    '.java': 'java',
    '.cs': 'csharp',
    '.js': 'javascript',
    '.jsx': 'javascript',
    '.mjs': 'javascript',
    '.cjs': 'javascript',
    '.ts': 'typescript',
    '.tsx': 'typescript',
};

// ─── Configuration ─────────────────────────────────────────────────────────

interface ServerConfig {
    url: string;
    timeout: number;
}

function getServerConfig(): ServerConfig {
    const cfg = vscode.workspace.getConfiguration('utcoder');
    return {
        url: cfg.get<string>('serverUrl', 'http://localhost:8000'),
        timeout: cfg.get<number>('serverTimeout', 120000),
    };
}

// ─── Helpers ───────────────────────────────────────────────────────────────

function detectLanguage(fileName: string): string {
    return EXT_TO_LANG[path.extname(fileName).toLowerCase()] || 'unknown';
}

function getTestFileName(sourceFileName: string): string {
    const ext = path.extname(sourceFileName).toLowerCase();
    const stem = path.basename(sourceFileName, ext);

    switch (ext) {
        case '.py':  return `test_${stem}.py`;
        case '.java': return `${stem}Test.java`;
        case '.cs':  return `${stem}Tests.cs`;
        case '.js': case '.jsx': case '.mjs': case '.cjs':
            return `${stem}.test.js`;
        case '.ts': case '.tsx':
            return `${stem}.test.ts`;
        default:
            return `test_${sourceFileName}`;
    }
}

async function readFileContent(filePath: string): Promise<string> {
    return fs.promises.readFile(filePath, 'utf-8');
}

function getFileToProcess(uri?: vscode.Uri): string | undefined {
    if (uri) return uri.fsPath;
    const editor = vscode.window.activeTextEditor;
    if (editor) return editor.document.uri.fsPath;
    return undefined;
}

// ─── Types ─────────────────────────────────────────────────────────────────

interface GenerateResponse {
    success: boolean;
    code?: string;
    error?: string;
}

interface HealthResponse {
    ready: boolean;
    message: string;
    version?: string;
}

// ─── HTTP client ───────────────────────────────────────────────────────────

async function callGenerateAPI(
    fileName: string,
    sourceCode: string,
    signal?: AbortSignal,
): Promise<GenerateResponse> {
    const config = getServerConfig();
    const url = `${config.url.replace(/\/+$/, '')}/api/generate`;

    const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            file_name: fileName,
            source_code: sourceCode,
            language: detectLanguage(fileName),
        }),
        signal,
    });

    if (!response.ok) {
        const text = await response.text().catch(() => 'No response body');
        return { success: false, error: `Server returned ${response.status}: ${text}` };
    }

    return (await response.json()) as GenerateResponse;
}

async function healthCheck(signal?: AbortSignal): Promise<HealthResponse> {
    const config = getServerConfig();
    const url = `${config.url.replace(/\/+$/, '')}/api/health`;

    const response = await fetch(url, { signal });
    if (!response.ok) {
        return { ready: false, message: `Server returned ${response.status}` };
    }
    return (await response.json()) as HealthResponse;
}

// ─── Main command handler ──────────────────────────────────────────────────

async function generateTestsForFile(uri?: vscode.Uri) {
    const filePath = getFileToProcess(uri);
    if (!filePath) {
        vscode.window.showWarningMessage(
            'UTcoder: No file selected. Right-click a file in the Explorer or open one in the editor.',
        );
        return;
    }

    const ext = path.extname(filePath).toLowerCase();
    if (!SUPPORTED_EXTENSIONS.has(ext)) {
        vscode.window.showWarningMessage(
            `UTcoder: Unsupported file type "${ext}". Supported: ${[...SUPPORTED_EXTENSIONS].join(', ')}`,
        );
        return;
    }

    const fileName = path.basename(filePath);

    await vscode.window.withProgress(
        {
            location: vscode.ProgressLocation.Notification,
            title: `UTcoder: Generating tests for ${fileName}...`,
            cancellable: true,
        },
        async (progress, token) => {
            progress.report({ message: 'Reading file...' });
            let sourceCode: string;
            try {
                sourceCode = await readFileContent(filePath);
            } catch (err: any) {
                vscode.window.showErrorMessage(
                    `UTcoder: Cannot read file - ${err?.message || err}`,
                );
                return;
            }

            progress.report({ message: 'Connecting to UTcoder server...' });
            try {
                const health = await healthCheck(
                    token.isCancellationRequested ? AbortSignal.abort() : undefined,
                );
                if (!health.ready) {
                    const action = await vscode.window.showErrorMessage(
                        `UTcoder server not reachable: ${health.message}`,
                        'Configure Server URL',
                        'Retry',
                    );
                    if (action === 'Configure Server URL') {
                        await vscode.commands.executeCommand(
                            'workbench.action.openSettings',
                            'utcoder.serverUrl',
                        );
                    }
                    return;
                }
            } catch {
                vscode.window.showErrorMessage(
                    'UTcoder: Cannot connect to server. Check server URL setting.',
                );
                return;
            }

            progress.report({ message: 'Generating unit tests...' });
            if (token.isCancellationRequested) return;

            let result: GenerateResponse;
            try {
                const ctrl = new AbortController();
                token.onCancellationRequested(() => ctrl.abort());
                result = await callGenerateAPI(fileName, sourceCode, ctrl.signal);
            } catch (err: any) {
                const msg =
                    err?.name === 'AbortError'
                        ? 'Request cancelled'
                        : err?.message || String(err);
                vscode.window.showErrorMessage(`UTcoder: Generation failed - ${msg}`);
                return;
            }

            if (!result.success || !result.code) {
                vscode.window.showErrorMessage(
                    `UTcoder: Generation failed - ${result.error || 'Unknown error'}`,
                );
                return;
            }

            progress.report({ message: 'Writing test file...' });
            if (token.isCancellationRequested) return;

            const testFileName = getTestFileName(fileName);
            let outputDir = path.dirname(filePath);

            // Try to use workspace tests/ directory
            const workspaceFolders = vscode.workspace.workspaceFolders;
            if (workspaceFolders && workspaceFolders.length > 0) {
                const root = workspaceFolders[0].uri.fsPath;
                if (filePath.startsWith(root)) {
                    const relPath = path.relative(root, filePath);
                    for (const testDir of ['tests', 'test', '__tests__']) {
                        const candidate = path.join(root, testDir, relPath);
                        const candidateDir = path.dirname(candidate);
                        try {
                            await fs.promises.access(candidateDir);
                            outputDir = candidateDir;
                            break;
                        } catch {
                            // dir doesn't exist, continue
                        }
                    }
                }
            }

            const testFilePath = path.join(outputDir, testFileName);

            try {
                await fs.promises.mkdir(outputDir, { recursive: true });

                try {
                    await fs.promises.access(testFilePath, fs.constants.F_OK);
                    const choice = await vscode.window.showWarningMessage(
                        `Test file already exists: ${testFileName}`,
                        { modal: true },
                        'Overwrite',
                        'Cancel',
                    );
                    if (choice !== 'Overwrite') return;
                } catch {
                    // file doesn't exist, proceed
                }

                await fs.promises.writeFile(testFilePath, result.code, 'utf-8');
            } catch (err: any) {
                vscode.window.showErrorMessage(
                    `UTcoder: Failed to write test file - ${err?.message || err}`,
                );
                return;
            }

            try {
                const doc = await vscode.workspace.openTextDocument(testFilePath);
                await vscode.window.showTextDocument(doc, vscode.ViewColumn.Beside);
            } catch {
                // ignore
            }

            vscode.window.showInformationMessage(
                `UTcoder: ✅ Tests generated → ${testFileName}`,
            );
        },
    );
}

// ─── Activation ────────────────────────────────────────────────────────────

export function activate(context: vscode.ExtensionContext) {
    console.log('[UTcoder] Activating simplified extension...');

    const generateCmd = vscode.commands.registerCommand(
        'utcoder.generateTests',
        (uri?: vscode.Uri) => generateTestsForFile(uri),
    );

    const healthCmd = vscode.commands.registerCommand(
        'utcoder.checkHealth',
        async () => {
            try {
                const health = await healthCheck();
                if (health.ready) {
                    const ver = (health as HealthResponse).version;
                    vscode.window.showInformationMessage(
                        `UTcoder server is ready. ${health.message}${ver ? ` (v${ver})` : ''}`,
                    );
                } else {
                    const action = await vscode.window.showErrorMessage(
                        `UTcoder server: ${health.message}`,
                        'Configure Server URL',
                    );
                    if (action === 'Configure Server URL') {
                        await vscode.commands.executeCommand(
                            'workbench.action.openSettings',
                            'utcoder.serverUrl',
                        );
                    }
                }
            } catch {
                const action = await vscode.window.showErrorMessage(
                    'UTcoder server: Connection failed',
                    'Configure Server URL',
                );
                if (action === 'Configure Server URL') {
                    await vscode.commands.executeCommand(
                        'workbench.action.openSettings',
                        'utcoder.serverUrl',
                    );
                }
            }
        },
    );

    context.subscriptions.push(generateCmd, healthCmd);

    // Background health check on activation
    healthCheck().then((health) => {
        if (!health.ready) {
            console.log('[UTcoder] Server not reachable on startup:', health.message);
        }
    });

    console.log('[UTcoder] Simplified extension activated.');
}

export function deactivate() {
    console.log('[UTcoder] Deactivated.');
}

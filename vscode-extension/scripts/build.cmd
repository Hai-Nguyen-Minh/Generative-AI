@echo off
REM Build script for UTcoder VS Code Extension
echo ============================================
echo  UTcoder VS Code Extension - Build Script
echo ============================================
echo.

REM Check for Node.js
where node >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Node.js is not installed. Please install Node.js from https://nodejs.org/
    exit /b 1
)

REM Check for npm
where npm >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: npm is not found even though Node.js is installed.
    exit /b 1
)

echo [1/3] Installing dependencies...
call npm install
if %errorlevel% neq 0 (
    echo ERROR: npm install failed.
    exit /b 1
)

echo [2/3] Compiling TypeScript...
call npx tsc -p tsconfig.json
if %errorlevel% neq 0 (
    echo ERROR: TypeScript compilation failed.
    exit /b 1
)

echo.
echo ============================================
echo  Build complete!
echo.
echo  To package as VSIX, run:
echo    npx @vscode/vsce package --out utcoder-vscode.vsix
echo.
echo  Or install directly with:
echo    code --install-extension utcoder-vscode.vsix
echo ============================================


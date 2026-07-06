"""
core/runner/manager.py
----------------------
Central manager to coordinate environments and trigger test runner processes.
"""

from typing import Dict, Optional
import logging

from core.runner.base_runner import BaseRunner, RunResult
from core.runner.python_runner import PythonRunner
from core.runner.js_runner import JSRunner
from core.runner.java_runner import JavaRunner
from core.runner.csharp_runner import CSharpRunner

logger = logging.getLogger(__name__)

# Cache runner instances
_RUNNERS: Dict[str, BaseRunner] = {
    "python": PythonRunner(),
    "javascript": JSRunner(),
    "java": JavaRunner(),
    "csharp": CSharpRunner(),
}

def get_runner(lang: str) -> Optional[BaseRunner]:
    """Retrieve the runner instance for a specific language."""
    return _RUNNERS.get(lang.lower())

def check_environment(lang: str) -> Dict[str, str]:
    """Check the environmental readiness for a given language."""
    runner = get_runner(lang)
    if not runner:
        return {"status": "unsupported", "details": f"No runner available for language: {lang}"}
    try:
        return runner.check_environment()
    except Exception as e:
        logger.exception("Error checking environment for %s", lang)
        return {"status": "error", "details": str(e)}

def bootstrap_environment(lang: str, status_callback=None) -> str:
    """Download dependencies and install compilers/runners for a language."""
    runner = get_runner(lang)
    if not runner:
        raise ValueError(f"No runner available for language: {lang}")
    return runner.bootstrap(status_callback)

def run_test_suite(
    lang: str,
    source_code: str,
    test_code: str,
    source_filename: str,
    test_filename: str,
) -> RunResult:
    """Compile, execute, and collect coverage for a test suite."""
    runner = get_runner(lang)
    if not runner:
        return RunResult(
            success=False,
            compilation_success=False,
            compilation_error=f"No runner registered for language: {lang}"
        )
    try:
        return runner.run_tests(source_code, test_code, source_filename, test_filename)
    except Exception as e:
        logger.exception("Runner error for %s", lang)
        return RunResult(
            success=False,
            compilation_success=False,
            compilation_error=f"Runner execution failed: {e}",
            test_output=f"Error: {e}"
        )

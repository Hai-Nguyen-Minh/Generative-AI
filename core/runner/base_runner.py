"""
core/runner/base_runner.py
-------------------------
Base abstractions for language-specific test compilation and coverage run systems.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List

@dataclass
class RunResult:
    success: bool
    compilation_success: bool = True
    compilation_error: str = ""
    test_output: str = ""
    test_summary: Dict[str, int] = field(default_factory=lambda: {"passed": 0, "failed": 0, "total": 0})
    coverage_summary: Dict[str, float] = field(default_factory=lambda: {"pct": 0.0})
    covered_lines: List[int] = field(default_factory=list)
    uncovered_lines: List[int] = field(default_factory=list)

class BaseRunner(ABC):
    @abstractmethod
    def check_environment(self) -> Dict[str, str]:
        """
        Check if the runtime environment (compilers, executors, test libraries) is ready.
        Returns a dict e.g., {"status": "ready" | "missing", "details": "description..."}
        """
        pass

    @abstractmethod
    def bootstrap(self, status_callback=None) -> str:
        """
        Bootstrap the environment (download tools, install packages, etc.).
        status_callback is a callable taking a string message to report progress.
        Returns a completion status message.
        """
        pass

    @abstractmethod
    def run_tests(
        self,
        source_code: str,
        test_code: str,
        source_filename: str,
        test_filename: str,
    ) -> RunResult:
        """
        Compile and run the generated tests against the source file,
        returning a RunResult containing test execution and coverage information.
        """
        pass

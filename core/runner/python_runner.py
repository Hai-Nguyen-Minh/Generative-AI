"""
core/runner/python_runner.py
---------------------------
Python runner using pytest and coverage libraries.
"""

import os
import sys
import subprocess
import tempfile
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict
import logging

from core.runner.base_runner import BaseRunner, RunResult

logger = logging.getLogger(__name__)

class PythonRunner(BaseRunner):
    def check_environment(self) -> Dict[str, str]:
        try:
            import pytest
            import coverage
            return {
                "status": "ready",
                "details": f"pytest ({pytest.__version__}) and coverage ({coverage.__version__}) are installed."
            }
        except ImportError as e:
            return {
                "status": "missing",
                "details": f"Required packages are missing: {e}. Please bootstrap the environment."
            }

    def bootstrap(self, status_callback=None) -> str:
        if status_callback:
            status_callback("Installing pytest and coverage...")
        
        cmd = [sys.executable, "-m", "pip", "install", "pytest", "coverage"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            return "Successfully installed pytest and coverage."
        else:
            raise RuntimeError(f"Failed to install python requirements:\n{result.stderr}")

    def run_tests(
        self,
        source_code: str,
        test_code: str,
        source_filename: str,
        test_filename: str,
    ) -> RunResult:
        # Create a temporary workspace directory
        with tempfile.TemporaryDirectory(prefix="utcoder_py_") as tmpdir:
            tmp_path = Path(tmpdir)
            src_file = tmp_path / source_filename
            tst_file = tmp_path / test_filename
            
            # Write source and test files
            src_file.write_text(source_code, encoding="utf-8")
            tst_file.write_text(test_code, encoding="utf-8")
            
            # Create an empty __init__.py so Python resolves imports in the temp directory
            (tmp_path / "__init__.py").touch()
            
            # Run coverage and pytest
            cov_file = tmp_path / ".coverage"
            report_xml = tmp_path / "results.xml"
            
            # Run command: coverage run -m pytest --junitxml=results.xml test_file.py
            # We run within the tmp_path directory to avoid import path issues
            cmd = [
                sys.executable,
                "-m", "coverage",
                "run",
                f"--data-file={cov_file}",
                "-m", "pytest",
                f"--junitxml={report_xml}",
                str(tst_file.name)
            ]
            
            env = os.environ.copy()
            # Ensure the current tmp_path is on PYTHONPATH
            env["PYTHONPATH"] = os.pathsep.join([str(tmp_path), env.get("PYTHONPATH", "")])
            
            logger.info("Executing python test: %s in %s", " ".join(cmd), tmp_path)
            res = subprocess.run(cmd, cwd=tmp_path, capture_output=True, text=True, env=env)
            
            test_output = f"=== STDOUT ===\n{res.stdout}\n=== STDERR ===\n{res.stderr}"
            
            # 1. Parse pytest outcomes
            test_summary = {"passed": 0, "failed": 0, "total": 0}
            if report_xml.exists():
                try:
                    tree = ET.parse(report_xml)
                    root = tree.getroot()
                    
                    tests = int(root.attrib.get("tests", 0))
                    failures = int(root.attrib.get("failures", 0))
                    errors = int(root.attrib.get("errors", 0))
                    skipped = int(root.attrib.get("skipped", 0))
                    
                    if tests == 0 and len(root) > 0:
                        # Sometimes values are inside the <testsuite> elements under <testsuites>
                        tests = sum(int(suite.attrib.get("tests", 0)) for suite in root)
                        failures = sum(int(suite.attrib.get("failures", 0)) for suite in root)
                        errors = sum(int(suite.attrib.get("errors", 0)) for suite in root)
                        skipped = sum(int(suite.attrib.get("skipped", 0)) for suite in root)
                        
                    passed = tests - failures - errors - skipped
                    test_summary = {
                        "passed": max(0, passed),
                        "failed": failures + errors,
                        "total": tests
                    }
                except Exception as e:
                    logger.error("Error parsing pytest results XML: %s", e)
            
            # 2. Extract coverage details
            coverage_summary = {"pct": 0.0}
            covered_lines = []
            uncovered_lines = []
            
            if cov_file.exists():
                # Export coverage to JSON
                json_report = tmp_path / "coverage.json"
                export_cmd = [
                    sys.executable,
                    "-m", "coverage",
                    "json",
                    f"--data-file={cov_file}",
                    "-o", str(json_report)
                ]
                subprocess.run(export_cmd, cwd=tmp_path, capture_output=True)
                
                if json_report.exists():
                    try:
                        cov_data = json.loads(json_report.read_text(encoding="utf-8"))
                        # Find the entry for our source file (key contains source_filename)
                        src_key = None
                        for k in cov_data.get("files", {}).keys():
                            if Path(k).name == source_filename:
                                src_key = k
                                break
                        
                        if src_key:
                            file_cov = cov_data["files"][src_key]
                            pct = file_cov["summary"].get("percent_covered", 0.0)
                            coverage_summary = {"pct": round(pct, 1)}
                            covered_lines = file_cov.get("executed_lines", [])
                            uncovered_lines = file_cov.get("missing_lines", [])
                    except Exception as e:
                        logger.error("Error reading coverage JSON: %s", e)
            
            # Success is defined as: compilation succeeded (always true for python syntax if run finishes)
            # and test runs completed without catastrophic harness crash.
            success = res.returncode in [0, 1]  # pytest returns 1 if tests failed, which is still a success run.
            
            return RunResult(
                success=success,
                compilation_success=True,
                test_output=test_output,
                test_summary=test_summary,
                coverage_summary=coverage_summary,
                covered_lines=covered_lines,
                uncovered_lines=uncovered_lines
            )

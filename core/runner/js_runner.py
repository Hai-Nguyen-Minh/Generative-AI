"""
core/runner/js_runner.py
-----------------------
JavaScript/TypeScript runner using local Jest environment.
"""

import os
import subprocess
import tempfile
import json
import shutil
from pathlib import Path
from typing import Dict
import logging

from core.runner.base_runner import BaseRunner, RunResult
from core.runner.bootstrap import get_runtime_dir

logger = logging.getLogger(__name__)

class JSRunner(BaseRunner):
    def _get_js_env_path(self) -> Path:
        return get_runtime_dir("js")

    def check_environment(self) -> Dict[str, str]:
        # 1. Check if node is in PATH
        node_check = shutil.which("node")
        if not node_check:
            return {
                "status": "missing",
                "details": "Node.js is not installed or not in PATH. Please install Node.js."
            }
        
        # 2. Check if Jest is installed in the local js_env
        js_env = self._get_js_env_path()
        jest_bin = js_env / "node_modules" / ".bin" / "jest"
        if not jest_bin.exists() and not (js_env / "node_modules" / "jest").exists():
            return {
                "status": "missing",
                "details": "Jest is not installed in the runner workspace. Please click Bootstrap/Setup."
            }
            
        return {
            "status": "ready",
            "details": f"Node.js found and Jest is installed in runner workspace ({js_env})."
        }

    def bootstrap(self, status_callback=None) -> str:
        js_env = self._get_js_env_path()
        if status_callback:
            status_callback("Checking Node.js...")
            
        if not shutil.which("node"):
            raise RuntimeError("Node.js is not installed. Please install Node.js (v16+) to run JavaScript unit tests.")
            
        if status_callback:
            status_callback("Initialising JavaScript runner package.json...")
            
        # Write minimal package.json
        package_json = js_env / "package.json"
        pkg_data = {
            "name": "utcoder-js-runner",
            "version": "1.0.0",
            "private": True,
            "dependencies": {
                "jest": "^29.7.0"
            }
        }
        package_json.write_text(json.dumps(pkg_data, indent=2), encoding="utf-8")
        
        if status_callback:
            status_callback("Installing Jest dependency (npm install)... This may take 30s...")
            
        cmd = ["npm", "install", "--no-audit", "--no-fund"]
        # Run npm install on Windows. Shell=True is necessary for npm on Windows.
        res = subprocess.run(cmd, cwd=js_env, capture_output=True, text=True, shell=True)
        if res.returncode != 0:
            raise RuntimeError(f"npm install failed:\nStdout: {res.stdout}\nStderr: {res.stderr}")
            
        return "Successfully installed Jest in local runner workspace."

    def run_tests(
        self,
        source_code: str,
        test_code: str,
        source_filename: str,
        test_filename: str,
    ) -> RunResult:
        js_env = self._get_js_env_path()
        jest_bin = js_env / "node_modules" / "jest" / "bin" / "jest.js"
        
        with tempfile.TemporaryDirectory(prefix="utcoder_js_") as tmpdir:
            tmp_path = Path(tmpdir)
            src_file = tmp_path / source_filename
            tst_file = tmp_path / test_filename
            
            src_file.write_text(source_code, encoding="utf-8")
            tst_file.write_text(test_code, encoding="utf-8")
            
            # Setup results and coverage output files
            results_json = tmp_path / "results.json"
            coverage_dir = tmp_path / "coverage"
            
            # Setup jest config JSON passed to CLI.
            # We configure rootDir to be the temp folder, testEnvironment node,
            # and coverage output folders.
            jest_config = {
                "rootDir": str(tmp_path.resolve()).replace("\\", "/"),
                "testEnvironment": "node",
                "coverageDirectory": str(coverage_dir.resolve()).replace("\\", "/"),
                "collectCoverage": True,
                "coverageReporters": ["json"]
            }
            
            cmd = [
                "node",
                str(jest_bin.resolve()),
                str(tst_file.resolve()).replace("\\", "/"),
                "--json",
                f"--outputFile={results_json.resolve()}",
                "--config",
                json.dumps(jest_config)
            ]
            
            logger.info("Executing JavaScript test: %s", " ".join(cmd))
            # On Windows, node works fine as a direct executable.
            res = subprocess.run(cmd, cwd=tmp_path, capture_output=True, text=True)
            
            test_output = f"=== STDOUT ===\n{res.stdout}\n=== STDERR ===\n{res.stderr}"
            
            # 1. Parse Jest Test results
            test_summary = {"passed": 0, "failed": 0, "total": 0}
            if results_json.exists():
                try:
                    data = json.loads(results_json.read_text(encoding="utf-8"))
                    passed = data.get("numPassedTests", 0)
                    failed = data.get("numFailedTests", 0)
                    total = data.get("numTotalTests", 0)
                    test_summary = {
                        "passed": passed,
                        "failed": failed,
                        "total": total
                    }
                except Exception as e:
                    logger.error("Failed to parse Jest results: %s", e)
            
            # 2. Parse coverage results
            coverage_summary = {"pct": 0.0}
            covered_lines = []
            uncovered_lines = []
            
            cov_final = coverage_dir / "coverage-final.json"
            if cov_final.exists():
                try:
                    cov_data = json.loads(cov_final.read_text(encoding="utf-8"))
                    cov_sets = set()
                    uncov_sets = set()
                    
                    for file_path, file_data in cov_data.items():
                        # Verify it's our source file
                        if Path(file_path).name != source_filename:
                            continue
                            
                        s_map = file_data.get("statementMap", {})
                        hits = file_data.get("s", {})
                        
                        line_to_hits = {}
                        for stmt_id, stmt_loc in s_map.items():
                            start_line = stmt_loc["start"]["line"]
                            end_line = stmt_loc["end"]["line"]
                            hit_count = hits.get(stmt_id, 0)
                            
                            for l in range(start_line, end_line + 1):
                                line_to_hits.setdefault(l, []).append(hit_count)
                                
                        for l, hit_counts in line_to_hits.items():
                            if any(hc > 0 for hc in hit_counts):
                                cov_sets.add(l)
                            else:
                                uncov_sets.add(l)
                                
                    covered_lines = sorted(list(cov_sets))
                    uncovered_lines = sorted(list(uncov_sets))
                    
                    total_lines = len(covered_lines) + len(uncovered_lines)
                    if total_lines > 0:
                        pct = (len(covered_lines) / total_lines) * 100.0
                        coverage_summary = {"pct": round(pct, 1)}
                except Exception as e:
                    logger.error("Failed to parse Jest coverage JSON: %s", e)
            
            success = res.returncode in [0, 1]  # Jest returns 1 if tests fail, which is successful execution.
            
            return RunResult(
                success=success,
                compilation_success=True,
                test_output=test_output,
                test_summary=test_summary,
                coverage_summary=coverage_summary,
                covered_lines=covered_lines,
                uncovered_lines=uncovered_lines
            )

"""
core/runner/csharp_runner.py
---------------------------
C# runner using .NET SDK (system or portable) and Coverlet.
"""

import os
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import shutil
from pathlib import Path
from typing import Dict, Optional
import logging

from core.runner.base_runner import BaseRunner, RunResult
from core.runner.bootstrap import get_runtime_dir, download_file, extract_zip

logger = logging.getLogger(__name__)

DOTNET_SDK_URL = "https://dotnetcli.azureedge.net/dotnet/Sdk/8.0.204/dotnet-sdk-8.0.204-win-x64.zip"

class CSharpRunner(BaseRunner):
    def _get_dotnet_dir(self) -> Path:
        return get_runtime_dir("dotnet")

    def _get_dotnet_executable(self) -> Optional[str]:
        """Find dotnet executable: check PATH, then C:\\Program Files\\dotnet, then portable."""
        # 1. System path
        path_dotnet = shutil.which("dotnet")
        if path_dotnet:
            return path_dotnet
            
        # 2. Standard install directory on Windows
        std_dotnet = Path("C:/Program Files/dotnet/dotnet.exe")
        if std_dotnet.exists():
            return str(std_dotnet)
            
        # 3. Local portable installation
        portable_dotnet = self._get_dotnet_dir() / "dotnet.exe"
        if portable_dotnet.exists():
            return str(portable_dotnet)
            
        return None

    def check_environment(self) -> Dict[str, str]:
        dotnet_exe = self._get_dotnet_executable()
        if dotnet_exe:
            # Verify it runs
            try:
                res = subprocess.run([dotnet_exe, "--version"], capture_output=True, text=True)
                if res.returncode == 0:
                    return {
                        "status": "ready",
                        "details": f"dotnet SDK found: {res.stdout.strip()} ({dotnet_exe})"
                    }
            except Exception:
                pass
                
        return {
            "status": "missing",
            "details": "dotnet SDK is not installed or found. Please click Bootstrap/Setup to download a portable .NET 8.0 SDK."
        }

    def bootstrap(self, status_callback=None) -> str:
        # Check if already installed
        dotnet_exe = self._get_dotnet_executable()
        if dotnet_exe:
            return f"dotnet SDK is already available at: {dotnet_exe}"
            
        dotnet_dir = self._get_dotnet_dir()
        zip_path = dotnet_dir / "dotnet-sdk.zip"
        
        # Download portable .NET SDK
        download_file(DOTNET_SDK_URL, zip_path, status_callback)
        
        # Extract ZIP
        extract_zip(zip_path, dotnet_dir, status_callback)
        
        # Clean up zip file
        try:
            zip_path.unlink()
        except Exception:
            pass
            
        # Verify extraction
        portable_dotnet = dotnet_dir / "dotnet.exe"
        if not portable_dotnet.exists():
            raise RuntimeError("Portable dotnet installation failed; dotnet.exe was not found after extraction.")
            
        return "Successfully bootstrapped portable .NET SDK."

    def run_tests(
        self,
        source_code: str,
        test_code: str,
        source_filename: str,
        test_filename: str,
    ) -> RunResult:
        dotnet_exe = self._get_dotnet_executable()
        if not dotnet_exe:
            return RunResult(
                success=False,
                compilation_success=False,
                compilation_error="dotnet SDK is not available. Please bootstrap the C# environment."
            )
            
        with tempfile.TemporaryDirectory(prefix="utcoder_cs_") as tmpdir:
            tmp_path = Path(tmpdir)
            
            # Create a new xUnit test project
            # dotnet new xunit -n TestProject -o .
            create_cmd = [dotnet_exe, "new", "xunit", "-n", "TestProject", "-o", "."]
            logger.info("Creating C# test project: %s", " ".join(create_cmd))
            create_res = subprocess.run(create_cmd, cwd=tmp_path, capture_output=True, text=True)
            
            if create_res.returncode != 0:
                return RunResult(
                    success=False,
                    compilation_success=False,
                    compilation_error=f"Failed to create new xUnit project: {create_res.stderr}"
                )
                
            # Remove default template file
            try:
                (tmp_path / "UnitTest1.cs").unlink(missing_ok=True)
            except Exception:
                pass
                
            # Write source and test files to the project directory
            src_file = tmp_path / source_filename
            tst_file = tmp_path / test_filename
            
            src_file.write_text(source_code, encoding="utf-8")
            tst_file.write_text(test_code, encoding="utf-8")
            
            # Run tests and collect coverage
            # dotnet test --collect:"XPlat Code Coverage" --logger:trx
            test_cmd = [
                dotnet_exe,
                "test",
                "--collect:XPlat Code Coverage",
                "--logger:trx"
            ]
            
            logger.info("Executing C# tests: %s", " ".join(test_cmd))
            test_res = subprocess.run(test_cmd, cwd=tmp_path, capture_output=True, text=True)
            
            test_output = f"=== STDOUT ===\n{test_res.stdout}\n=== STDERR ===\n{test_res.stderr}"
            
            # 1. Parse TRX report for test execution summary
            test_summary = {"passed": 0, "failed": 0, "total": 0}
            trx_files = list(tmp_path.glob("TestResults/*.trx"))
            if trx_files:
                trx_path = trx_files[0]
                try:
                    tree = ET.parse(trx_path)
                    root = tree.getroot()
                    
                    ns = ""
                    if root.tag.startswith("{"):
                        ns = root.tag.split("}")[0] + "}"
                        
                    counters = root.find(f".//{ns}Counters")
                    if counters is not None:
                        total = int(counters.attrib.get("total", 0))
                        passed = int(counters.attrib.get("passed", 0))
                        failed = int(counters.attrib.get("failed", 0))
                        test_summary = {
                            "passed": passed,
                            "failed": total - passed, # Covers failed + errors + aborted
                            "total": total
                        }
                except Exception as e:
                    logger.error("Failed to parse TRX file: %s", e)
            
            # 2. Parse Cobertura XML report for coverage
            coverage_summary = {"pct": 0.0}
            covered_lines = []
            uncovered_lines = []
            
            cob_files = list(tmp_path.glob("TestResults/*/coverage.cobertura.xml"))
            if cob_files:
                cob_path = cob_files[0]
                try:
                    tree = ET.parse(cob_path)
                    root = tree.getroot()
                    
                    cov_sets = set()
                    uncov_sets = set()
                    
                    # Search classes namespace-insensitively
                    class_list = []
                    test_output += f"\n\n=== COBERTURA XML CONTENT ===\n" + cob_path.read_text(encoding="utf-8")[:1000]
                    for elem in root.iter():
                        tag_name = elem.tag.split("}")[-1]
                        if tag_name == "class":
                            filename = elem.attrib.get("filename", "")
                            class_list.append(f"Name: {elem.attrib.get('name')}, File: {filename}")
                            if Path(filename).name.lower() == source_filename.lower():
                                for line in elem.iter():
                                    line_tag = line.tag.split("}")[-1]
                                    if line_tag == "line":
                                        line_num = int(line.attrib.get("number", 0))
                                        hits = int(line.attrib.get("hits", 0))
                                        if hits > 0:
                                            cov_sets.add(line_num)
                                        else:
                                            uncov_sets.add(line_num)
                                break
                    
                    test_output += f"\n\n=== COBERTURA DIAGNOSTICS ===\n" + "\n".join(class_list)
                            
                    covered_lines = sorted(list(cov_sets))
                    uncovered_lines = sorted(list(uncov_sets))
                    
                    total_lines = len(covered_lines) + len(uncovered_lines)
                    if total_lines > 0:
                        pct = (len(covered_lines) / total_lines) * 100.0
                        coverage_summary = {"pct": round(pct, 1)}
                except Exception as e:
                    logger.error("Failed to parse Cobertura coverage: %s", e)
                    test_output += f"\n\n=== COBERTURA PARSE ERROR ===\n{e}"
            
            # Success means compilation was successful and test results were generated.
            # 'dotnet test' returns 1 if tests failed, which is still successful execution.
            compilation_success = "Build FAILED" not in test_res.stdout
            success = compilation_success and (test_res.returncode in [0, 1])
            
            return RunResult(
                success=success,
                compilation_success=compilation_success,
                compilation_error="" if compilation_success else test_res.stdout,
                test_output=test_output,
                test_summary=test_summary,
                coverage_summary=coverage_summary,
                covered_lines=covered_lines,
                uncovered_lines=uncovered_lines
            )

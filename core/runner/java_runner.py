"""
core/runner/java_runner.py
-------------------------
Java runner using javac, JUnit 5 Console Launcher, and JaCoCo.
"""

import os
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import shutil
from pathlib import Path
from typing import Dict
import logging

from core.runner.base_runner import BaseRunner, RunResult
from core.runner.bootstrap import get_runtime_dir, download_file

logger = logging.getLogger(__name__)

# Constants for downloads
JUNIT_STANDALONE_URL = "https://repo1.maven.org/maven2/org/junit/platform/junit-platform-console-standalone/1.10.2/junit-platform-console-standalone-1.10.2.jar"
JACOCO_AGENT_URL = "https://repo1.maven.org/maven2/org/jacoco/org.jacoco.agent/0.8.11/org.jacoco.agent-0.8.11-runtime.jar"
JACOCO_CLI_URL = "https://repo1.maven.org/maven2/org/jacoco/org.jacoco.cli/0.8.11/org.jacoco.cli-0.8.11-nodeps.jar"

class JavaRunner(BaseRunner):
    def _get_java_libs_path(self) -> Path:
        return get_runtime_dir("java")

    def check_environment(self) -> Dict[str, str]:
        # 1. Check if javac is installed
        javac_check = shutil.which("javac")
        java_check = shutil.which("java")
        if not javac_check or not java_check:
            return {
                "status": "missing",
                "details": "Java Development Kit (JDK) compiler (javac) or runtime (java) is not in PATH. Please install JDK."
            }
            
        # 2. Check if required jars exist
        lib_dir = self._get_java_libs_path()
        junit_jar = lib_dir / "junit-platform-console-standalone.jar"
        agent_jar = lib_dir / "jacocoagent.jar"
        cli_jar = lib_dir / "jacococli.jar"
        
        if not (junit_jar.exists() and agent_jar.exists() and cli_jar.exists()):
            return {
                "status": "missing",
                "details": "Required runner JAR files are missing. Please click Bootstrap/Setup."
            }
            
        return {
            "status": "ready",
            "details": "Java JDK compiler/runtime found and helper JARs are present."
        }

    def bootstrap(self, status_callback=None) -> str:
        # Verify javac is available
        if not shutil.which("javac") or not shutil.which("java"):
            raise RuntimeError("Java 'javac' and 'java' executables must be installed and added to PATH.")
            
        lib_dir = self._get_java_libs_path()
        
        junit_jar = lib_dir / "junit-platform-console-standalone.jar"
        agent_jar = lib_dir / "jacocoagent.jar"
        cli_jar = lib_dir / "jacococli.jar"
        
        # Download files if they don't exist
        if not junit_jar.exists():
            download_file(JUNIT_STANDALONE_URL, junit_jar, status_callback)
        if not agent_jar.exists():
            download_file(JACOCO_AGENT_URL, agent_jar, status_callback)
        if not cli_jar.exists():
            download_file(JACOCO_CLI_URL, cli_jar, status_callback)
            
        return "Java runner dependencies bootstrapped successfully."

    def _detect_package(self, code: str) -> str:
        """Find the Java package declaration, returning empty string if default package."""
        match = re.search(r"package\s+([\w\.]+)\s*;", code)
        return match.group(1).strip() if match else ""

    def run_tests(
        self,
        source_code: str,
        test_code: str,
        source_filename: str,
        test_filename: str,
    ) -> RunResult:
        lib_dir = self._get_java_libs_path()
        junit_jar = lib_dir / "junit-platform-console-standalone.jar"
        agent_jar = lib_dir / "jacocoagent.jar"
        cli_jar = lib_dir / "jacococli.jar"
        
        with tempfile.TemporaryDirectory(prefix="utcoder_java_") as tmpdir:
            tmp_path = Path(tmpdir)
            
            src_pkg = self._detect_package(source_code)
            tst_pkg = self._detect_package(test_code)
            
            # Setup folders based on package structure
            src_sub_dir = tmp_path / src_pkg.replace(".", "/") if src_pkg else tmp_path
            tst_sub_dir = tmp_path / tst_pkg.replace(".", "/") if tst_pkg else tmp_path
            
            src_sub_dir.mkdir(parents=True, exist_ok=True)
            tst_sub_dir.mkdir(parents=True, exist_ok=True)
            
            src_file = src_sub_dir / source_filename
            tst_file = tst_sub_dir / test_filename
            
            src_file.write_text(source_code, encoding="utf-8")
            tst_file.write_text(test_code, encoding="utf-8")
            
            # 1. Compile Java code
            # javac -cp "junit.jar" -d . src_file tst_file
            compile_cmd = [
                "javac",
                "-cp", str(junit_jar.resolve()),
                "-d", str(tmp_path.resolve()),
                str(src_file.resolve()),
                str(tst_file.resolve())
            ]
            
            logger.info("Compiling Java files: %s", " ".join(compile_cmd))
            compile_res = subprocess.run(compile_cmd, cwd=tmp_path, capture_output=True, text=True)
            
            if compile_res.returncode != 0:
                # Compilation failed
                test_output = f"=== COMPILATION ERROR ===\n{compile_res.stderr}\n\n=== STDOUT ===\n{compile_res.stdout}"
                return RunResult(
                    success=False,
                    compilation_success=False,
                    compilation_error=compile_res.stderr,
                    test_output=test_output
                )
                
            # 2. Run Tests with JaCoCo Agent
            # java -javaagent:jacocoagent.jar=destfile=jacoco.exec -cp "junit.jar;." org.junit.platform.console.ConsoleLauncher --select-class com.example.MyTest
            exec_file = tmp_path / "jacoco.exec"
            test_class_name = Path(test_filename).stem
            full_test_class = f"{tst_pkg}.{test_class_name}" if tst_pkg else test_class_name
            
            # Classpath uses path separator according to OS (; for Windows, : for unix)
            cp_sep = ";" if os.name == "nt" else ":"
            classpath = f"{junit_jar.resolve()}{cp_sep}{tmp_path.resolve()}"
            
            agent_arg = f"-javaagent:{agent_jar.resolve()}=destfile={exec_file.resolve()},includes=*"
            
            run_cmd = [
                "java",
                agent_arg,
                "-cp", classpath,
                "org.junit.platform.console.ConsoleLauncher",
                "--select-class", full_test_class
            ]
            
            logger.info("Executing Java tests: %s", " ".join(run_cmd))
            run_res = subprocess.run(run_cmd, cwd=tmp_path, capture_output=True, text=True)
            
            test_output = f"=== STDOUT ===\n{run_res.stdout}\n=== STDERR ===\n{run_res.stderr}"
            
            # 3. Parse test counts from console launcher stdout
            test_summary = {"passed": 0, "failed": 0, "total": 0}
            passed_match = re.search(r"(\d+)\s+tests successful", run_res.stdout)
            failed_match = re.search(r"(\d+)\s+tests failed", run_res.stdout)
            total_match = re.search(r"(\d+)\s+tests found", run_res.stdout)
            
            if total_match:
                test_summary["total"] = int(total_match.group(1))
            if passed_match:
                test_summary["passed"] = int(passed_match.group(1))
            if failed_match:
                test_summary["failed"] = int(failed_match.group(1))
                
            # 4. Generate coverage XML report using jacococli.jar
            coverage_summary = {"pct": 0.0}
            covered_lines = []
            uncovered_lines = []
            
            if exec_file.exists():
                report_xml = tmp_path / "jacoco_report.xml"
                report_cmd = [
                    "java",
                    "-jar", str(cli_jar.resolve()),
                    "report", str(exec_file.resolve()),
                    "--classfiles", str(tmp_path.resolve()),
                    "--sourcefiles", str(tmp_path.resolve()),
                    "--xml", str(report_xml.resolve())
                ]
                
                logger.info("Generating JaCoCo XML report: %s", " ".join(report_cmd))
                subprocess.run(report_cmd, cwd=tmp_path, capture_output=True)
                
                if report_xml.exists():
                    try:
                        # Parse JaCoCo XML
                        tree = ET.parse(report_xml)
                        root = tree.getroot()
                        
                        cov_sets = set()
                        uncov_sets = set()
                        
                        # Search for sourcefile nodes in the XML matching our source_filename
                        for sourcefile in root.findall(".//sourcefile"):
                            if sourcefile.attrib.get("name") == source_filename:
                                for line in sourcefile.findall("line"):
                                    line_num = int(line.attrib.get("nr", 0))
                                    ci = int(line.attrib.get("ci", 0)) # Covered instructions
                                    mi = int(line.attrib.get("mi", 0)) # Missed instructions
                                    
                                    if ci > 0:
                                        cov_sets.add(line_num)
                                    elif mi > 0:
                                        uncov_sets.add(line_num)
                                        
                        covered_lines = sorted(list(cov_sets))
                        uncovered_lines = sorted(list(uncov_sets))
                        
                        total_lines = len(covered_lines) + len(uncovered_lines)
                        if total_lines > 0:
                            pct = (len(covered_lines) / total_lines) * 100.0
                            coverage_summary = {"pct": round(pct, 1)}
                    except Exception as e:
                        logger.error("Failed to parse JaCoCo XML: %s", e)
                        
            success = run_res.returncode == 0 or (test_summary["total"] > 0)
            
            return RunResult(
                success=success,
                compilation_success=True,
                test_output=test_output,
                test_summary=test_summary,
                coverage_summary=coverage_summary,
                covered_lines=covered_lines,
                uncovered_lines=uncovered_lines
            )

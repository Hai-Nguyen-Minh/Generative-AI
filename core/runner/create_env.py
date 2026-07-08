"""
core/runner/create_ env.py
-------------------------
Creates isolated Python environments for each language supported by UTcoder.

Usage:
    python core/runner/create_env.py

This will create the following environments:
- python: .venv_python
- java: .venv_java
- csharp: .venv_csharp
- javascript: .venv_javascript

Each environment contains:
- The language runtime (via uv)
- Language-specific testing tools (pytest, JUnit 5, NUnit, Jest)
- A minimal Python environment for running these tools

Each environment is isolated and can be activated using:
    uv use -p <env_dir>

See bootstrap.py for more details on environment creation.
"""

from csharp_runner import CSharpRunner
from java_runner import JavaRunner
from python_runner import PythonRunner
from js_runner import JSRunner


def main() -> None:
    """Create all language environments."""
    CSharpRunner().bootstrap()
    JavaRunner().bootstrap()
    JSRunner().bootstrap()
    PythonRunner().bootstrap()


if __name__ == "__main__":
    main()
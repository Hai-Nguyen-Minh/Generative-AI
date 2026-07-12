"""
UTcoder HTTP Server

Exposes the UTcoder test generation, compile-check, and coverage APIs.
The VS Code extension communicates with this server via REST.

Endpoints:
    GET  /api/health        → Health check
    POST /api/generate      → Generate unit tests
    POST /api/compile-check → AI-based compilation check
    POST /api/coverage      → AI-based coverage analysis
"""

import json
import logging
import re
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

# Ensure project root is on PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent))

from core.config import get_config
from core.generator import index_code, generate_unit_tests
from core.compiler import compile_check
from core.coverager import analyse_coverage
from core.llm import get_model_name

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)

logger = logging.getLogger("utcoder.server")


def _clean_generated_code(code: str) -> str:
    """Clean LLM output to extract only the test code."""
    # Strip markdown code fences
    fence_match = re.search(r'```(?:\w+)?\s*\n(.*?)\n```', code, re.DOTALL)
    if fence_match:
        code = fence_match.group(1)
    # Remove leading comment blocks
    code = re.sub(r'\A(?:#.*\n?)+', '', code)
    code = re.sub(r'\A\s*/\*[\s\S]*?\*/\s*', '', code)
    code = re.sub(r'\A\s*//.*\n?', '', code, flags=re.MULTILINE)
    return code.strip()


class UTCoderHandler(BaseHTTPRequestHandler):

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            return {}
        raw = self.rfile.read(content_length)
        return json.loads(raw.decode("utf-8"))

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            try:
                model = get_model_name()
                cfg = get_config()
                chroma_dir = cfg.get("vectorstore", {}).get("chroma_dir", "")
                self._send_json({
                    "ready": True,
                    "message": f"Model: {model}",
                    "version": "0.2.0",
                    "chroma_dir": chroma_dir,
                })
            except Exception as e:
                self._send_json({
                    "ready": False,
                    "message": str(e),
                }, status=503)
        else:
            self._send_json({"error": "Not found"}, status=404)

    def do_POST(self):
        parsed = urlparse(self.path)
        body = self._read_body()

        if parsed.path == "/api/generate":
            self._handle_generate(body)
        elif parsed.path == "/api/compile-check":
            self._handle_compile_check(body)
        elif parsed.path == "/api/coverage":
            self._handle_coverage(body)
        else:
            self._send_json({"error": "Not found"}, status=404)

    def _handle_generate(self, body: dict):
        try:
            file_name = body.get("file_name", "")
            source_code = body.get("source_code", "")
            language = body.get("language", "")

            if not file_name or not source_code:
                self._send_json({
                    "success": False,
                    "error": "Both 'file_name' and 'source_code' are required.",
                }, status=400)
                return

            logger.info(
                "Generating tests for '%s' (language=%s, %d chars)",
                file_name, language, len(source_code),
            )

            result_parts = []
            for token in generate_unit_tests(file_name, source_code):
                result_parts.append(token)
            raw_code = "".join(result_parts)
            cleaned = _clean_generated_code(raw_code)

            logger.info(
                "Generated %d lines for '%s'",
                len(cleaned.splitlines()), file_name,
            )

            self._send_json({
                "success": True,
                "code": cleaned,
                "language": language,
                "file_name": file_name,
            })

        except Exception as e:
            logger.exception("Generation failed")
            self._send_json({
                "success": False,
                "error": str(e),
            }, status=500)

    def _handle_compile_check(self, body: dict):
        try:
            source_code = body.get("source_code", "")
            test_code = body.get("test_code", "")
            file_name = body.get("file_name", "")

            if not source_code or not test_code or not file_name:
                self._send_json({
                    "success": False,
                    "error": "'source_code', 'test_code', and 'file_name' are required.",
                }, status=400)
                return

            logger.info("Running AI compile check for '%s'", file_name)
            result = compile_check(source_code, test_code, file_name)

            self._send_json({
                "success": True,
                "result": result,
            })

        except Exception as e:
            logger.exception("Compile check failed")
            self._send_json({
                "success": False,
                "error": str(e),
            }, status=500)

    def _handle_coverage(self, body: dict):
        try:
            source_code = body.get("source_code", "")
            test_code = body.get("test_code", "")
            file_name = body.get("file_name", "")

            if not source_code or not test_code or not file_name:
                self._send_json({
                    "success": False,
                    "error": "'source_code', 'test_code', and 'file_name' are required.",
                }, status=400)
                return

            logger.info("Running AI coverage analysis for '%s'", file_name)
            result = analyse_coverage(source_code, test_code, file_name)

            self._send_json({
                "success": True,
                "result": result,
            })

        except Exception as e:
            logger.exception("Coverage analysis failed")
            self._send_json({
                "success": False,
                "error": str(e),
            }, status=500)

    def log_message(self, format, *args):
        logger.info("%s - %s", self.client_address[0], format % args)


def main():
    cfg = get_config()
    server_cfg = cfg.get("server", {})
    host = server_cfg.get("host", "0.0.0.0")
    port = int(server_cfg.get("port", 8000))

    server = HTTPServer((host, port), UTCoderHandler)
    logger.info("UTcoder HTTP server started on http://%s:%d", host, port)
    logger.info("API endpoints:")
    logger.info("  GET  /api/health")
    logger.info("  POST /api/generate")
    logger.info("  POST /api/compile-check")
    logger.info("  POST /api/coverage")
    logger.info("Press Ctrl+C to stop.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        server.server_close()


if __name__ == "__main__":
    main()

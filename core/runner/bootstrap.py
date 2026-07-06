"""
core/runner/bootstrap.py
------------------------
Utility functions to download, extract, and setup runtime files.
"""

import os
import shutil
import urllib.request
import zipfile
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

RUNTIMES_DIR = Path(__file__).parent / "runtimes"

def get_runtime_dir(lang: str) -> Path:
    d = RUNTIMES_DIR / lang
    d.mkdir(parents=True, exist_ok=True)
    return d

def download_file(url: str, dest_path: Path, status_callback=None):
    """Download a file with optional progress logging."""
    logger.info("Downloading %s to %s", url, dest_path)
    if status_callback:
        status_callback(f"Downloading {dest_path.name}...")

    # Set up request with headers to avoid user agent blocking
    req = urllib.request.Request(
        url,
        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    )

    with urllib.request.urlopen(req) as response, open(dest_path, 'wb') as out_file:
        total_size = int(response.info().get('Content-Length', 0))
        downloaded = 0
        block_size = 1024 * 64
        last_pct = -1

        while True:
            buffer = response.read(block_size)
            if not buffer:
                break
            downloaded += len(buffer)
            out_file.write(buffer)
            
            if total_size > 0:
                pct = int((downloaded / total_size) * 100)
                if pct != last_pct and pct % 10 == 0:
                    last_pct = pct
                    msg = f"Downloading {dest_path.name}: {pct}% completed"
                    logger.info(msg)
                    if status_callback:
                        status_callback(msg)

    logger.info("Successfully downloaded %s", dest_path.name)

def extract_zip(zip_path: Path, extract_to: Path, status_callback=None):
    """Extract a ZIP archive to a destination folder."""
    logger.info("Extracting %s to %s", zip_path, extract_to)
    if status_callback:
        status_callback(f"Extracting {zip_path.name}...")
        
    extract_to.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(extract_to)
        
    logger.info("Successfully extracted %s", zip_path.name)

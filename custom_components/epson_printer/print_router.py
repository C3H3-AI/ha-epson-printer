"""Unified print routing for the Epson Printer integration.

This module is intentionally *homeassistant-free* so it can be unit-tested in
isolation (the test-suite loads it via importlib without importing HA).

It decides, based on the content and the printer's capabilities, which
transport (RAW 9100 or IPP 631) to use, and optionally converts Office
documents (Word / Excel / PowerPoint / ...) to PDF via LibreOffice before
submitting the job over IPP.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from typing import Optional

from .control import EpsonPrinterControl
from .ipp_client import EpsonIppClient

_LOGGER = logging.getLogger(__name__)

# Office / document formats that LibreOffice can convert to PDF.
OFFICE_EXTS = frozenset(
    {
        ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
        ".odt", ".ods", ".odp", ".rtf", ".html", ".htm", ".txt",
    }
)
IMAGE_EXTS = frozenset({".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"})
PDF_EXT = ".pdf"

MIME_MAP = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".pdf": "application/pdf",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".bmp": "image/bmp",
}

DEFAULT_SOFFICE = "soffice"
CONVERT_TIMEOUT = 120


def looks_like_path(content: str) -> bool:
    """Heuristically decide whether ``content`` is a file path, not text.

    Returns ``True`` for an existing file, a path containing a directory
    separator with a dotted filename, or a bare filename carrying a known
    document / image extension.
    """
    if not content:
        return False
    if os.path.exists(content):
        return True
    basename = os.path.basename(content)
    if ("/" in content or "\\" in content) and "." in basename:
        return True
    ext = os.path.splitext(content)[1].lower()
    if ext and (ext in OFFICE_EXTS or ext in IMAGE_EXTS or ext == PDF_EXT):
        return True
    return False


def convert_office_to_pdf(
    src_path: str, soffice: str = DEFAULT_SOFFICE
) -> Optional[str]:
    """Convert an Office document to PDF using LibreOffice headless.

    Returns the path to the generated PDF, or ``None`` on any failure
    (LibreOffice missing, conversion error, or no output produced).
    """
    if shutil.which(soffice) is None and not os.path.exists(soffice):
        _LOGGER.error(
            "LibreOffice (%s) not found; cannot convert %s", soffice, src_path
        )
        return None
    out_dir = tempfile.mkdtemp(prefix="epson_office_")
    try:
        proc = subprocess.run(
            [
                soffice,
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                out_dir,
                src_path,
            ],
            capture_output=True,
            text=True,
            timeout=CONVERT_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError) as err:
        _LOGGER.error("LibreOffice conversion failed for %s: %s", src_path, err)
        return None
    if proc.returncode != 0:
        _LOGGER.error(
            "LibreOffice returned %d for %s: %s",
            proc.returncode,
            src_path,
            proc.stderr,
        )
        return None
    pdf_path = os.path.join(
        out_dir, os.path.splitext(os.path.basename(src_path))[0] + ".pdf"
    )
    if not os.path.exists(pdf_path):
        _LOGGER.error("LibreOffice did not produce %s", pdf_path)
        return None
    return pdf_path


def route_print(
    host: str,
    content: str,
    content_type: str = "auto",
    job_name: Optional[str] = None,
    convert_office: bool = False,
    soffice: str = DEFAULT_SOFFICE,
    ipp_port: int = 631,
    raw_port: int = 9100,
) -> dict:
    """Unified print entry point with smart transport selection.

    Routing rules
    -------------
    * ``text``                  -> RAW 9100 ``print_text``
    * ``PDF`` / image file      -> IPP 631 ``print_job`` (returns job status)
    * Office file + convert     -> ``soffice`` -> PDF -> IPP 631
    * Office file (no convert)  -> error (printers cannot consume Office natively)
    * anything else             -> RAW 9100 ``print_file`` (last resort)

    Returns a result dict::

        {"ok": bool, "channel": str, "job_id": int | None, "note": str}
    """
    # ── Text path ──────────────────────────────────────────────────────────
    is_text = content_type == "text" or (
        content_type == "auto" and not looks_like_path(content)
    )
    if is_text:
        ok = EpsonPrinterControl(host, raw_port).print_text(content)
        return {"ok": ok, "channel": "raw_text", "job_id": None, "note": ""}

    # ── File path ───────────────────────────────────────────────────────────
    if not os.path.exists(content):
        return {
            "ok": False,
            "channel": "",
            "job_id": None,
            "note": f"file not found: {content}",
        }

    ext = os.path.splitext(content)[1].lower()

    # Office documents cannot be printed raw; require conversion.
    if ext in OFFICE_EXTS:
        if not convert_office:
            return {
                "ok": False,
                "channel": "",
                "job_id": None,
                "note": "Office document needs 'Convert Office documents' enabled",
            }
        pdf = convert_office_to_pdf(content, soffice)
        if pdf is None:
            return {
                "ok": False,
                "channel": "",
                "job_id": None,
                "note": "office conversion failed (LibreOffice required)",
            }
        content = pdf
        ext = PDF_EXT

    # PDF / image -> IPP (preferred: format negotiation + job status).
    if ext == PDF_EXT or ext in IMAGE_EXTS:
        try:
            with open(content, "rb") as fh:
                data = fh.read()
        except OSError as err:
            return {"ok": False, "channel": "", "job_id": None, "note": str(err)}
        doc_format = MIME_MAP.get(ext, "application/octet-stream")
        ipp = EpsonIppClient(host, ipp_port, use_ssl=True)
        res = ipp.print_job(data, doc_format, job_name)
        if res and res.get("job_id") is not None:
            return {
                "ok": True,
                "channel": "ipp",
                "job_id": res.get("job_id"),
                "note": res.get("job_state", ""),
            }
        _LOGGER.warning("IPP print failed for %s; falling back to RAW", content)

    # Last resort: RAW 9100 byte dump.
    ok = EpsonPrinterControl(host, raw_port).print_file(content)
    return {"ok": ok, "channel": "raw_file", "job_id": None, "note": ""}

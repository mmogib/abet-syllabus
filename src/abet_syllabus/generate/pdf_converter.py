"""Convert DOCX to PDF using available system tools."""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class PdfConversionError(Exception):
    """Raised when PDF conversion fails."""


def convert_to_pdf(
    docx_path: str | Path,
    pdf_path: str | Path | None = None,
) -> Path:
    """Convert a DOCX file to PDF.

    Tries conversion methods in order:
    1. docx2pdf (uses LibreOffice or MS Word)
    2. Direct LibreOffice command line

    Args:
        docx_path: Path to the input DOCX file.
        pdf_path: Optional output PDF path. Defaults to same name with .pdf extension.

    Returns:
        Path to the generated PDF file.

    Raises:
        PdfConversionError: If no conversion method is available or conversion fails.
        FileNotFoundError: If the DOCX file doesn't exist.
    """
    docx_path = Path(docx_path)
    if not docx_path.exists():
        raise FileNotFoundError(f"DOCX file not found: {docx_path}")

    if pdf_path is None:
        pdf_path = docx_path.with_suffix(".pdf")
    else:
        pdf_path = Path(pdf_path)

    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    # Try docx2pdf first
    if _try_docx2pdf(docx_path, pdf_path):
        return pdf_path

    # Try LibreOffice directly
    if _try_libreoffice(docx_path, pdf_path):
        return pdf_path

    raise PdfConversionError(
        "No PDF conversion method available. Install one of:\n"
        "  - docx2pdf (pip install docx2pdf) + LibreOffice or MS Word\n"
        "  - LibreOffice (soffice must be on PATH)"
    )


def is_pdf_available() -> bool:
    """Check if any PDF conversion method is available."""
    if _has_docx2pdf():
        return True
    if _has_libreoffice():
        return True
    return False


def _has_docx2pdf() -> bool:
    """Check if docx2pdf is importable."""
    try:
        import docx2pdf  # noqa: F401
        return True
    except ImportError:
        return False


def _has_libreoffice() -> bool:
    """Check if LibreOffice is available on PATH."""
    return shutil.which("soffice") is not None


def _try_docx2pdf(docx_path: Path, pdf_path: Path) -> bool:
    """Attempt conversion using docx2pdf."""
    try:
        import docx2pdf
        docx2pdf.convert(str(docx_path), str(pdf_path))
        return pdf_path.exists()
    except ImportError:
        logger.debug("docx2pdf not installed")
        return False
    except Exception as exc:
        logger.warning("docx2pdf conversion failed: %s", exc)
        return False


def _try_libreoffice(docx_path: Path, pdf_path: Path) -> bool:
    """Attempt conversion using LibreOffice command line."""
    soffice = shutil.which("soffice")
    if not soffice:
        logger.debug("LibreOffice (soffice) not found on PATH")
        return False

    try:
        output_dir = pdf_path.parent
        result = subprocess.run(
            [
                soffice,
                "--headless",
                "--convert-to", "pdf",
                "--outdir", str(output_dir),
                str(docx_path),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            logger.warning("LibreOffice conversion failed: %s", result.stderr)
            return False

        # LibreOffice outputs to <outdir>/<original_name>.pdf
        lo_output = output_dir / docx_path.with_suffix(".pdf").name
        if lo_output.exists() and lo_output != pdf_path:
            lo_output.rename(pdf_path)

        return pdf_path.exists()
    except subprocess.TimeoutExpired:
        logger.warning("LibreOffice conversion timed out")
        return False
    except Exception as exc:
        logger.warning("LibreOffice conversion error: %s", exc)
        return False

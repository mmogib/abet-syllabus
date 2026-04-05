"""Format detection for course specification files."""

from __future__ import annotations

from pathlib import Path

# Supported file extensions and their default format types
_EXTENSION_MAP: dict[str, str] = {
    ".pdf": "format_a_pdf",
    ".docx": "format_b_crf2",
}

SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(_EXTENSION_MAP.keys())


def detect_format(file_path: str | Path) -> str:
    """Detect the format type of a course specification file.

    Detection rules:
        - .pdf files are Format A (standard KFUPM PDF course specs)
        - .docx files are Format B (CRF2 DOCX course specs)

    Args:
        file_path: Path to the file.

    Returns:
        Format type string: "format_a_pdf" or "format_b_crf2".

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file extension is not supported.
    """
    path = Path(file_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    ext = path.suffix.lower()
    if ext not in _EXTENSION_MAP:
        raise ValueError(
            f"Unsupported file extension '{ext}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )

    return _EXTENSION_MAP[ext]


def is_supported(file_path: str | Path) -> bool:
    """Check whether a file has a supported extension.

    Args:
        file_path: Path to check.

    Returns:
        True if the file extension is supported.
    """
    ext = Path(file_path).suffix.lower()
    return ext in SUPPORTED_EXTENSIONS

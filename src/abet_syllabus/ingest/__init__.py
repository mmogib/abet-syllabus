"""Ingestion pipeline — extract, parse, and store course specifications."""

from abet_syllabus.ingest.pipeline import (
    IngestResult,
    ingest_file,
    ingest_folder,
    ingest_plos,
    prompt_plo_aliases,
)

__all__ = [
    "IngestResult",
    "ingest_file",
    "ingest_folder",
    "ingest_plos",
    "prompt_plo_aliases",
]

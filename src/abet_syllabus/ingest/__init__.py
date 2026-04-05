"""Ingestion pipeline — extract, parse, and store course specifications."""

from abet_syllabus.ingest.pipeline import (
    IngestResult,
    ingest_file,
    ingest_folder,
    ingest_plos,
)

__all__ = [
    "IngestResult",
    "ingest_file",
    "ingest_folder",
    "ingest_plos",
]

# ABET Syllabus Generator

CLI tool that converts KFUPM course specification files (PDF/DOCX) into
standardized ABET-compliant course syllabi.

## Installation

```bash
pip install -e .
```

## Usage

```bash
abet-syllabus --help
abet-syllabus ingest <path>
abet-syllabus query courses
abet-syllabus map <course> --program MATH
abet-syllabus generate <course> --program MATH --term T252
```

## Development

```bash
pip install -e ".[dev]"
pytest
```

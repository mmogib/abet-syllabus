---
status: active
date: 2026-04-05
---

# Architecture Decision: CLI-First with Future Web UI

## Decision

Build a Python CLI tool first. Design the internals so a lightweight web UI
(Streamlit, Gradio, or FastAPI) can be layered on later without rewriting core logic.

## Rationale

- Product shape is still being explored — CLI lets us iterate on core logic fast
- The user is the primary operator right now
- SQLite DB + Python modules become the foundation for any future UI
- Can process all 72+ files immediately and validate results
- CLO-PLO AI mapping can run interactively in terminal first

## Project Structure

```
abet-syllabus/
  resources/              # renamed from files/
    course-descriptions/  # input PDF/DOCX files organized by program
    plos/                 # PLO definitions (CSV/XLSX)
    templates/            # output DOCX template(s)
  src/                    # Python package
    extract/              # PDF + DOCX text/table extraction
    parse/                # structured field extraction from text
    db/                   # SQLite schema + persistence
    mapping/              # AI-powered CLO-PLO mapping
    generate/             # DOCX + PDF output generation
  cli.py                  # CLI entry point
  notes/                  # project discussion notes
```

## Core Capabilities

1. **Extract** — read PDF and DOCX course specifications, extract text and tables
2. **Parse** — map extracted content into a canonical schema (handles Format A PDFs
   and Format B CRF2 DOCX files)
3. **Store** — persist all extracted data in a central SQLite database
4. **Map** — AI-assisted CLO-to-PLO mapping, unique per (course, program) pair
5. **Generate** — produce ABET syllabus output in DOCX and PDF using the template

## Data Model Contract

- A course can appear in multiple programs
- CLO-PLO mapping key = (course, program, clo, plo)
- MATH 101 might map CLO-1 to PLO K1 in MATH but differently in DATA
- All extracted data stored — not just what the output template needs

## Environment

- Python via conda, using the `claude` environment
- SQLite for the central database
- All agents must use `conda activate claude` before running Python

## What Comes Later (Not Now)

- Lightweight web UI for file upload, review, CLO-PLO approval
- Batch processing dashboard
- Multi-user support

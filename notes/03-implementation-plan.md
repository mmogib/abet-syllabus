---
status: active
date: 2026-04-05
---

# Implementation Plan

## Overview

Build a Python CLI that processes course specification files (PDF/DOCX) into
ABET-compliant syllabi (DOCX + PDF), with a central SQLite database storing
all extracted data and AI-assisted CLO-PLO mappings.

Eight stages. Each stage produces a testable, usable increment.

---

## Stage 1: Project Scaffold

**Goal:** Working Python package with CLI skeleton, conda environment verified,
and project infrastructure in place.

**Tasks:**
- [ ] Verify conda `claude` env, install base dependencies (click or typer for CLI)
- [ ] Create Python package structure under `src/`
- [ ] Create `cli.py` entry point with placeholder subcommands:
  - `ingest <path>` — process a file or folder
  - `query <command>` — inspect the database
  - `map <course> <program>` — run CLO-PLO mapping
  - `generate <course> [--program X] [--term T]` — produce output
- [ ] Add `pyproject.toml` or `setup.py` for package management
- [ ] Add `.gitignore` (Python, SQLite, conda, IDE files)
- [ ] Initialize git repo

**Deliverable:** `python cli.py --help` shows all subcommands.

**Decisions needed:**
- CLI framework: `click` vs `typer` vs `argparse`
- Package manager: `pyproject.toml` (modern) vs `setup.py`

---

## Stage 2: Database Schema

**Goal:** SQLite database with a well-designed schema that captures ALL data
from both input formats, plus CLO-PLO mappings.

**Tasks:**
- [ ] Design schema (tables below)
- [ ] Implement schema creation and migration in `src/db/`
- [ ] Write helper functions for common queries (upsert course, add CLOs, etc.)
- [ ] Load PLO definitions from `resources/plos/plos.csv` into the DB
- [ ] Write tests for schema creation and basic CRUD

**Proposed Tables:**

```
programs
  program_code (PK)        — "MATH", "AS", "DATA"
  program_name             — "BS in Mathematics"

courses
  id (PK)
  course_code              — "MATH 101" (normalized)
  course_title             — "Calculus I"
  department
  college
  credit_hours             — "4-0-4" (raw)
  lecture_credits           — 4
  lab_credits               — 0
  total_credits             — 4
  catalog_description
  prerequisites
  corequisites
  course_type              — "Required Department" / "Elective" / null
  level                    — "UG - First Year" / null
  created_at
  updated_at

course_programs
  course_id (FK)
  program_code (FK)
  designation              — "Required" / "Selected Elective" / "Elective"
  UNIQUE(course_id, program_code)

course_clos
  id (PK)
  course_id (FK)
  clo_code                 — "1.1", "2.3"
  clo_category             — "Knowledge and Understanding" / "Skills" / "Values"
  clo_text
  sequence                 — ordering within the course
  teaching_strategy        — if available from input
  assessment_method        — if available from input

plo_definitions
  id (PK)
  program_code (FK)
  plo_code                 — "K1", "S1", "V1"
  plo_category             — "Knowledge" / "Skills" / "Values"
  plo_text
  sequence

clo_plo_mappings
  id (PK)
  course_clo_id (FK)
  plo_id (FK)
  program_code (FK)        — mapping is unique per program
  mapping_source           — "extracted" / "ai_suggested" / "user_approved"
  confidence               — 0.0-1.0 (for AI suggestions)
  rationale                — AI explanation for the mapping
  approved                 — boolean
  approved_at
  UNIQUE(course_clo_id, plo_id, program_code)

course_topics
  id (PK)
  course_id (FK)
  topic_number
  topic_title
  contact_hours            — numeric
  topic_type               — "lecture" / "lab"

course_textbooks
  id (PK)
  course_id (FK)
  textbook_text
  textbook_type            — "required" / "reference" / "recommended" / "electronic"

course_assessment
  id (PK)
  course_id (FK)
  assessment_task
  week_due
  proportion               — percentage
  assessment_type          — "lecture" / "lab"

source_files
  id (PK)
  file_path
  file_name
  file_extension           — "pdf" / "docx"
  file_hash                — SHA-256 for dedup
  format_type              — "format_a_pdf" / "format_b_crf2"
  processed_at
  course_id (FK)           — which course was extracted

processing_runs
  id (PK)
  started_at
  completed_at
  input_path               — folder or file that was processed
  total_files
  success_count
  error_count
  notes

run_files
  run_id (FK)
  source_file_id (FK)
  status                   — "success" / "error" / "skipped"
  error_message
  extracted_text           — full raw text (for debugging/reprocessing)
  parsed_json              — full parsed result as JSON

course_instructors
  id (PK)
  course_id (FK)
  instructor_name
  term_code                — "T252"
  role                     — "coordinator" / "instructor"

credit_categorization
  course_id (FK, PK)
  engineering_cs           — numeric hours
  math_science             — numeric hours
  humanities               — numeric hours
  social_sciences_business — numeric hours
  general_education        — numeric hours
  other                    — numeric hours
```

**Decisions needed:**
- Review and finalize table design
- Whether to store raw extracted text per file (useful for reprocessing)
- Term/semester handling (do we need a terms table?)

---

## Stage 3: Extraction

**Goal:** Reliably extract raw text and table structures from both PDF and
DOCX files.

**Tasks:**
- [ ] PDF extraction (`src/extract/pdf_extractor.py`)
  - Extract page text preserving layout
  - Extract tables as structured data (rows/columns)
  - Handle the KFUPM PDF format (tables with colored headers)
- [ ] DOCX extraction (`src/extract/docx_extractor.py`)
  - Extract paragraph text
  - Extract tables preserving row/column structure
  - Handle CRF2 format (checklist table, multi-column CLO tables)
- [ ] Common interface: both extractors return a unified `ExtractionResult`
  containing raw text + list of tables
- [ ] Format detection: auto-detect Format A vs Format B
- [ ] Tests against real files from `resources/course-descriptions/`

**Key libraries to evaluate:**
- PDF: `pdfplumber` (good table extraction) vs `pymupdf` vs `pdfminer`
- DOCX: `python-docx` (native table support)

**Deliverable:** `python cli.py extract <file>` prints structured extraction output.

---

## Stage 4: Parsing

**Goal:** Convert raw extracted text + tables into structured course data
matching the DB schema.

**Tasks:**
- [ ] Format A parser (`src/parse/format_a_parser.py`)
  - Sections A-H from KFUPM PDF template
  - Handle: course identity, credits, description, prerequisites, CLOs,
    topics, textbooks, assessment
  - CLO table: Code / CLO / PLO's Code (3-column)
- [ ] Format B parser (`src/parse/format_b_parser.py`)
  - CRF2 DOCX structure
  - Handle: checklist, course identity, credits, course type, CLOs with
    aligned PLOs + teaching strategies + assessment (4-column)
  - Topics table with contact hours
- [ ] Common output: both parsers produce a `ParsedCourse` dataclass
  that maps directly to the DB schema
- [ ] Course code normalization — "BUS200" / "Math 101" / "MATH208" all
  become "MATH 101" format (uppercase dept + space + number)
- [ ] Confidence scoring: flag fields that were ambiguous or missing
- [ ] Tests: parse every file in `resources/course-descriptions/` and report
  success/failure per field

**Deliverable:** `python cli.py parse <file>` shows parsed fields with confidence.

**This is the hardest stage.** Strategy decided:
- **Hybrid, rules-first:** exhaustive, relentless deterministic rules that
  handle >= 95% of fields. AI only checks and completes what rules couldn't.
- AI never replaces rules — it supplements them.
- Build rules iteratively: run against all real files, find failures, add rules,
  repeat until >= 95% field extraction rate.

---

## Stage 5: Ingestion Pipeline

**Goal:** End-to-end flow: point at a file or folder → extract → parse →
store in DB.

**Tasks:**
- [ ] Wire together: extract → detect format → parse → validate → store
- [ ] Implement `ingest` CLI command:
  - `python cli.py ingest <file>` — process one file
  - `python cli.py ingest <folder>` — process all files in folder
  - `python cli.py ingest <folder> --program MATH` — tag with program
  - `python cli.py ingest <folder> --recursive` — walk subdirectories
- [ ] Deduplication: skip files already processed (by hash)
- [ ] Error handling: continue on failure, collect errors for reporting
- [ ] Processing report: summary of what was ingested, what failed, what's missing
- [ ] PLO ingestion: `python cli.py ingest-plos <csv>` loads PLO definitions
- [ ] Implement basic `query` commands:
  - `python cli.py query courses` — list all courses
  - `python cli.py query course <code>` — show course details
  - `python cli.py query clos <course>` — list CLOs for a course
  - `python cli.py query stats` — summary statistics

**Deliverable:** Process all 72 files, inspect what landed in the DB.

**Validation checkpoint:** Run against all three program folders, review parsed
data quality, fix parser bugs before moving to mapping.

---

## Stage 6: CLO-PLO Mapping

**Goal:** AI-assisted mapping of each CLO to one or more PLOs, per program.

**Tasks:**
- [ ] Design the mapping prompt:
  - Input: course info, CLO text, list of available PLOs for the program
  - Output: structured mapping with confidence and rationale
- [ ] Implement mapping engine (`src/mapping/ai_mapper.py`):
  - Send CLOs + PLOs to LLM
  - Parse structured response
  - Store as `ai_suggested` with confidence scores
- [ ] Handle pre-existing mappings from input files:
  - Format B files often include "Aligned PLOs" — extract and store as
    `extracted` source
  - Only run AI mapping for CLOs without existing mappings
- [ ] Review workflow:
  - `python cli.py map <course> --program MATH` — run AI mapping
  - `python cli.py map <course> --program MATH --review` — show mappings
    for approval
  - `python cli.py map <course> --program MATH --approve` — mark as approved
  - `python cli.py map --program MATH --all` — map all unmapped courses
- [ ] Export mapping matrix:
  - `python cli.py query plo-matrix --program MATH` — CLO-PLO matrix

**Decisions resolved:**
- Primary AI provider: **Anthropic (Claude)**
- Architecture must support swappable providers (OpenAI, OpenRouter, etc.)
- API key management: env var + optional config file
- Goal: publishable as a Python package (PyPI) for other users

---

## Stage 7: Output Generation

**Goal:** Generate ABET syllabus documents (DOCX + PDF) from DB data
using the template.

**Tasks:**
- [ ] Template analysis: map every field in `ABETSyllabusTemplate.docx` to
  DB columns
- [ ] DOCX generation (`src/generate/docx_generator.py`):
  - Read template, replace placeholders with course data
  - Handle: course identity, credits categorization, instructor, textbooks,
    description, prerequisites, designation checkmark, CLO-SO table,
    topics list
  - CLO numbering: convert hierarchical (1.1, 2.1) to flat (CLO-1, CLO-2)
  - PLO → SO: determine if renaming is needed or if they're the same
  - Topics: convert contact hours to weekly duration
- [ ] PDF generation from DOCX:
  - Option A: `python-docx2pdf` (uses LibreOffice/Word)
  - Option B: direct PDF generation via `reportlab` or `weasyprint`
- [ ] Generate CLI command:
  - `python cli.py generate <course> --program MATH --term T252`
  - `python cli.py generate --program MATH --term T252 --all`
  - `python cli.py generate --program MATH --term T252 --all --output <dir>`
- [ ] Output naming convention: `T252_MATH101_ABET_Syllabus.docx`

**Deliverable:** Generate ABET syllabi for all MATH courses from DB data.

---

## Stage 8: Polish & Batch Operations

**Goal:** Production-quality CLI with batch processing, reporting, and
robust error handling.

**Tasks:**
- [ ] Batch processing with progress bars and summary reports
- [ ] CSV/JSON export of DB data
- [ ] Logging (file + console)
- [ ] Configuration file support (default paths, AI provider settings)
- [ ] `python cli.py status` — overall pipeline status:
  - How many courses ingested per program
  - How many have CLO-PLO mappings
  - How many have approved mappings
  - How many have generated output
- [ ] `python cli.py validate` — check data quality:
  - Courses missing CLOs
  - CLOs without PLO mappings
  - Required fields missing for generation
- [ ] Documentation: update CLAUDE.md, write usage guide

---

## Stage Dependencies

```
Stage 1 (Scaffold)
  └─→ Stage 2 (DB Schema)
        └─→ Stage 3 (Extraction)
              └─→ Stage 4 (Parsing)
                    └─→ Stage 5 (Ingestion Pipeline)
                          ├─→ Stage 6 (CLO-PLO Mapping)
                          └─→ Stage 7 (Output Generation)
                                └─→ Stage 8 (Polish)
```

Stages 6 and 7 can run in parallel once Stage 5 is done.

---

## Resolved Decisions

| Decision | Resolution | Stage |
|----------|------------|-------|
| Parsing strategy | Hybrid rules-first (>= 95% rules, AI supplements) | 4 |
| AI provider | Anthropic (Claude) primary, swappable architecture | 6 |
| API key management | env var + optional config file | 6 |
| Package goal | Publishable Python package (PyPI) | all |
| Security | Minimize dependencies, evaluate security of every package | all |

## Open Decisions (to resolve as we go)

| Decision | Options | Stage |
|----------|---------|-------|
| CLI framework | click / typer / argparse | 1 |
| PDF extraction library | pdfplumber / pymupdf / stdlib-only | 3 |
| PDF generation method | docx2pdf (LibreOffice) / reportlab / weasyprint | 7 |
| PLO vs SO terminology | same thing? needs mapping table? | 7 |

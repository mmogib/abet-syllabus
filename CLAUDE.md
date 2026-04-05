# ABET Syllabus Generator

CLI-first tool that converts KFUPM course specification files (PDF/DOCX) into
standardized ABET-compliant course syllabi (DOCX + PDF). Designed to work for
any program in the university.

## Python Environment

**All Python execution must use conda with the `claude` environment.**

```bash
# Conda location
CONDA=/c/Users/mmogi/anaconda3/Scripts/conda.exe

# Run Python
$CONDA run -n claude python <script>

# Install packages
$CONDA run -n claude pip install <package>
$CONDA install -n claude <package>

# Update Python version if needed
$CONDA install -n claude python=<version>
```

Never use system Python. Never create ad-hoc virtual environments.
Any spawned agent that runs Python must follow this rule.

## Project Structure

```
abet-syllabus/
  resources/                  # reference data
    course-descriptions/      # input PDF/DOCX organized by program (math/, as/, data/)
    plos/                     # PLO definitions (plos.csv, plos.xlsx)
    templates/                # output DOCX template(s)
  src/
    abet_syllabus/            # Python package (importable as abet_syllabus)
      cli.py                  # CLI entry point (argparse)
      extract/                # PDF + DOCX text/table extraction
      parse/                  # structured field extraction from raw text
      db/                     # SQLite schema + persistence
      mapping/                # AI-powered CLO-PLO mapping
      generate/               # DOCX + PDF output generation
  tests/                      # pytest test suite
  pyproject.toml              # package metadata, dependencies, entry_points
  notes/                      # project discussion and decision notes
  CLAUDE.md                   # this file
```

CLI entry point: `abet-syllabus` (installed via `pip install -e .`)

## Domain Concepts

- **Course Specification** — input document describing a course (varies by department)
- **ABET Syllabus** — standardized output document for accreditation
- **CLO** — Course Learning Outcome (per course)
- **PLO** — Program Learning Outcome (per program)
- **CLO-PLO mapping** — links a CLO to one or more PLOs, unique per (course, program)
- A course can belong to multiple programs; its CLO-PLO mappings differ per program

## Input Formats

Two distinct formats exist across the university:

- **Format A (PDF)** — standard KFUPM "COURSE SPECIFICATIONS" with sections A-H.
  Used by external departments (BUS, CGS, COE, ENGL, IAS, ICS, PE, SWE, etc.)
- **Format B (DOCX CRF2)** — "CRF2. COURSE SPECIFICATIONS" with checklist header,
  richer CLO tables. Used by MATH, AS, DATA departments.

## Output

- DOCX + PDF generated from `resources/templates/ABETSyllabusTemplate.docx`
- All extracted data stored in a central SQLite database

## Development Rules

- All decisions and plans live in `notes/` with `status: active` or `status: complete`
- Discuss approach before writing code — don't start implementing without alignment
- SQLite for all persistence
- Test against real files in `resources/course-descriptions/`

## Security & Dependencies

- **Security is paramount.** Every new package must be evaluated for security before use.
- Prefer standard library over third-party packages when feasible.
- Only add a dependency when the standard library genuinely cannot do the job.
- When a package is necessary, prefer well-maintained, widely-adopted libraries.
- Any spawned agent must follow these dependency rules.

## Parsing Strategy

Hybrid approach, rules-first:
1. Exhaustive, relentless deterministic rules that handle >= 95% of cases
2. AI checks and completes only what rules couldn't resolve
3. AI never replaces rules — it supplements them

## AI / LLM Integration

- Primary provider: **Anthropic (Claude)** for CLO-PLO mapping and parsing fallback
- Architecture must support swappable providers (OpenAI, OpenRouter, etc.)
- Goal: publishable CLI package (PyPI) that other users can install and configure
  with their own API keys

## v1 Reference

The v1 prototype at the Dropbox path has a working SQLite schema in
`src/cli/catalogDb.ts`. Use it as inspiration for the DB design but
don't copy it — improve and extend it for the broader university scope.

# ABET Syllabus Generator

CLI tool that converts university course specification files (PDF/DOCX) into standardized ABET-compliant course syllabi. Designed for KFUPM but adaptable to any institution.

## Features

- **Extract** text and tables from PDF and DOCX course specifications
- **Parse** two input formats: standard KFUPM PDF (sections A-H) and CRF2 DOCX
- **Store** all extracted data in a central SQLite database
- **Map** Course Learning Outcomes (CLOs) to Program Learning Outcomes (PLOs) using AI
- **Generate** ABET syllabus documents (DOCX) from a template
- **Export** data to CSV/JSON for reporting
- **Validate** data quality before generation
- **Interactive mode** with folder browsing and smart defaults

## Installation

```bash
pip install abet-syllabus
```

With AI mapping support (Anthropic or OpenRouter):

```bash
pip install abet-syllabus[ai]
```

For development:

```bash
git clone https://github.com/yourusername/abet-syllabus.git
cd abet-syllabus
pip install -e ".[ai,dev]"
```

## Quick Start

### Full pipeline (one command)

```bash
abet-syllabus run resources/course-descriptions/math/ -p MATH -t T252 -o ./output/
```

### Interactive mode

```bash
abet-syllabus run
```

Browses folders, asks for program and term interactively.

### Step by step

```bash
# 1. Ingest course files
abet-syllabus ingest resources/course-descriptions/math/ -p MATH -r

# 2. Load PLO definitions
abet-syllabus ingest-plos resources/plos/plos.csv

# 3. (Optional) AI-powered CLO-PLO mapping
export OPENROUTER_API_KEY="your-key"  # or ANTHROPIC_API_KEY
abet-syllabus map --all -p MATH

# 4. Generate ABET syllabi
abet-syllabus generate --all -p MATH -t T252 -o ./output/
```

## Commands

| Command | Description |
|---------|-------------|
| `run` | Full pipeline: ingest, (optionally map), generate |
| `extract` | Raw text/table extraction from PDF/DOCX |
| `parse` | Structured field extraction |
| `ingest` | Extract, parse, and store in database |
| `ingest-plos` | Load PLO definitions from CSV |
| `map` | AI-powered CLO-PLO mapping |
| `generate` | Produce ABET syllabus DOCX from database |
| `query` | Inspect database (courses, CLOs, stats, coverage, SQL) |
| `export` | Export to CSV/JSON |
| `status` | Database overview |
| `validate` | Data quality check |

## AI Mapping

Supports two AI providers for CLO-PLO mapping:

- **OpenRouter** (multi-model gateway): `export OPENROUTER_API_KEY="your-key"`
- **Anthropic** (direct): `export ANTHROPIC_API_KEY="your-key"`

The provider is auto-detected from available API keys. Use `--provider` and `--model` flags for control:

```bash
abet-syllabus map "MATH 101" -p MATH --provider openrouter --model google/gemini-2.5-flash
```

## Input Formats

- **Format A (PDF)** - Standard KFUPM "COURSE SPECIFICATIONS" with sections A-H
- **Format B (DOCX)** - CRF2 "COURSE SPECIFICATIONS" with structured tables

## Configuration

Optional YAML config file (`abet_syllabus.yaml`):

```yaml
db_path: abet_syllabus.db
template_path: resources/templates/ABETSyllabusTemplate.docx
output_dir: ./output
log_file: abet_syllabus.log
```

## Requirements

- Python 3.11+
- Dependencies: pdfplumber, python-docx, PyYAML, defusedxml
- Optional: anthropic (for AI mapping), docx2pdf (for PDF output)

## License

MIT

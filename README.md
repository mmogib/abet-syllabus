# ABET Syllabus Generator

[![PyPI version](https://badge.fury.io/py/abet-syllabus.svg)](https://pypi.org/project/abet-syllabus/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)

CLI tool that converts university course specification files (PDF/DOCX) into standardized ABET-compliant course syllabi. Designed for KFUPM but adaptable to any institution.

## Features

- **Extract** text and tables from PDF and DOCX course specifications
- **Parse** two input formats automatically (PDF sections A-H and DOCX CRF2)
- **Store** all extracted data in a central SQLite database
- **Map** Course Learning Outcomes (CLOs) to Program Learning Outcomes (PLOs) using AI
- **Generate** ABET syllabus documents (DOCX) from a customizable template
- **Export** data to CSV/JSON for ABET self-study reports
- **Validate** data quality before generation
- **Interactive mode** with folder browsing and smart defaults
- **PLO aliases** for mapping between different PLO naming conventions (K1/S1 to SO1/SO2)

## Installation

```bash
pip install abet-syllabus
```

With AI mapping support:

```bash
pip install "abet-syllabus[ai]"
```

For development:

```bash
git clone https://github.com/mmogib/abet-syllabus.git
cd abet-syllabus
pip install -e ".[ai,dev]"
```

## Quick Start

### One command (interactive)

```bash
abet-syllabus run
```

Browses your folders, asks for program code and term, then processes everything.

### One command (scripted)

```bash
abet-syllabus run input/math/ -p MATH -t T252 -o ./output/math/
```

### With AI mapping

```bash
export OPENROUTER_API_KEY="your-key"
abet-syllabus run input/math/ -p MATH -t T252 --map -o ./output/math/
```

The default AI model is free (no cost). Use `--model` for premium models.

### Step by step

```bash
# 1. Ingest course specification files
abet-syllabus ingest input/math/ -p MATH -r

# 2. Load PLO/SO definitions
abet-syllabus ingest-plos plos.csv

# 3. (Optional) Set up PLO aliases if your files use different codes
abet-syllabus plo-alias K1 SO1 -p MATH
abet-syllabus plo-alias S1 SO2 -p MATH

# 4. (Optional) AI-powered CLO-PLO mapping
export OPENROUTER_API_KEY="your-key"   # free models available
abet-syllabus map --all -p MATH

# 5. Review and approve mappings
abet-syllabus map "MATH 101" -p MATH --review
abet-syllabus map "MATH 101" -p MATH --approve

# 6. Generate ABET syllabi
abet-syllabus generate --all -p MATH -t T252 -o ./output/math/
```

## Commands

| Command | Description |
|---------|-------------|
| `run` | Full pipeline: ingest, (optionally) map, generate |
| `ingest` | Extract, parse, and store course files in database |
| `ingest-plos` | Load PLO/SO definitions from CSV |
| `plo-alias` | Manage PLO code aliases (e.g., K1 = SO1) |
| `map` | AI-powered CLO-PLO mapping |
| `generate` | Produce ABET syllabus DOCX from database |
| `query` | Inspect database, export to CSV/JSON with `-o` flag |
| `status` | Database overview |
| `validate` | Data quality check |
| `extract` | Raw text/table extraction (debugging) |
| `parse` | Structured field extraction (debugging) |

## AI Mapping

Supports two AI providers for CLO-PLO mapping:

| Provider | Env Variable | Cost | Notes |
|----------|-------------|------|-------|
| **OpenRouter** | `OPENROUTER_API_KEY` | Free tier available | Default. Multi-model gateway. Get key at [openrouter.ai](https://openrouter.ai) |
| **Anthropic** | `ANTHROPIC_API_KEY` | Pay per use ($5 min) | Direct Claude API. Get key at [console.anthropic.com](https://console.anthropic.com) |

The provider is auto-detected from available API keys. Use flags for control:

```bash
# Use a specific provider
abet-syllabus map "MATH 101" -p MATH --provider anthropic

# Use a specific model (any model available on OpenRouter)
abet-syllabus map --all -p MATH --model google/gemini-2.5-flash

# Force re-mapping
abet-syllabus map --all -p MATH -f
```

## PLO Aliases

Course specification files often use codes like `K1`, `S1`, `V1` (Knowledge/Skills/Values) while ABET uses `SO1`-`SO6` (Student Outcomes). PLO aliases bridge this gap:

```bash
# Define aliases (one-time setup per program)
abet-syllabus plo-alias K1 SO1 -p MATH
abet-syllabus plo-alias S1 SO2 -p MATH
abet-syllabus plo-alias V1 SO3 -p MATH

# List defined aliases
abet-syllabus plo-alias --list -p MATH

# Delete an alias
abet-syllabus plo-alias --delete K1 -p MATH
```

During ingestion, if unmatched PLO codes are found, you'll be prompted to map them interactively.

## Query and Reporting

```bash
# List all courses
abet-syllabus query courses -p MATH

# Course details
abet-syllabus query course "MATH 101"

# CLOs for a course
abet-syllabus query clos "MATH 101"

# PLO coverage matrix (which courses cover which PLOs)
abet-syllabus query coverage -p MATH

# Database statistics
abet-syllabus query stats

# Custom SQL query (read-only)
abet-syllabus query sql "SELECT course_code, course_title FROM courses WHERE department='Mathematics'"
```

### Exporting Query Results

Any query can be exported to a file with `-o`. Format is inferred from extension (`.json` for JSON, anything else for CSV):

```bash
# Export courses to CSV
abet-syllabus query courses -o courses.csv

# Export courses as JSON
abet-syllabus query courses -p MATH -o math_courses.json

# Export CLOs
abet-syllabus query clos "MATH 101" -o math101_clos.csv

# Export PLO coverage matrix (great for ABET self-study reports)
abet-syllabus query coverage -p MATH -o coverage.csv

# Export PLO mapping matrix
abet-syllabus query plo-matrix -p MATH -o matrix.csv

# Export custom SQL results
abet-syllabus query sql "SELECT * FROM courses" -o dump.csv
```

## Input Formats

The tool automatically detects and handles two formats:

- **Format A (PDF)** - Standard KFUPM "COURSE SPECIFICATIONS" with sections A-H. Used by external departments (BUS, CGS, COE, ENGL, IAS, ICS, PE, SWE, etc.)
- **Format B (DOCX)** - CRF2 "COURSE SPECIFICATIONS" with structured tables. Used by MATH, AS, DATA departments.

## Configuration

Optional YAML config file (`abet_syllabus.yaml` in the working directory):

```yaml
db_path: abet_syllabus.db
template_path: resources/templates/ABETSyllabusTemplate.docx
output_dir: ./output
log_file: abet_syllabus.log
```

CLI flags always override config file values.

## Course Code Normalization

All user input is automatically normalized:

```
math101   -> MATH 101
Math 101  -> MATH 101
MATH   101 -> MATH 101
math-101  -> MATH 101
```

## Requirements

- Python 3.11+
- Core dependencies: pdfplumber, python-docx, PyYAML, defusedxml
- Optional: `anthropic` (for direct Anthropic API), `docx2pdf` (for PDF output)

## License

MIT

## Author

Mohammed Alshahrani - KFUPM

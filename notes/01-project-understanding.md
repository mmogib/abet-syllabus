---
status: active
date: 2026-04-05
---

# Project Understanding: ABET Syllabus Generator

## What We're Building

A tool that takes inconsistently formatted KFUPM course specification documents (PDF/DOCX)
and produces standardized ABET-compliant course syllabi using a fixed departmental template.

**Target scope:** any program in the university, not limited to MATH/AS/DATA.

## The Problem

- Faculty submit course specifications in wildly varying formats
- Manually converting dozens of courses per program per term into ABET syllabi is tedious and error-prone
- Standardization and uniformity across instructors and departments is difficult to enforce
- ABET accreditation requires consistent documentation

## Input File Analysis

### Inventory

| Program | Files | Formats |
|---------|-------|---------|
| MATH    | 30    | DOCX only |
| AS      | 4     | DOCX only |
| DATA    | 38    | Mixed: 14 DOCX + 24 PDF |

The DATA folder is the most representative — it contains files from 13+ departments
(BUS, CGS, COE, DATA, ENGL, IAS, ICS, MATH, PE, STAT, SWE) showing real cross-university diversity.

### Two Distinct Input Formats Observed

**Format A — PDF "COURSE SPECIFICATIONS" (used by external departments)**
- Standard KFUPM template with sections A through H
- Sections: Course Identification, Description/Objectives, Contents, Teaching/Assessment,
  Office Hours, Learning Resources, Staff Requirements, Course Evaluation
- CLO table has Code / CLO / PLO's Code columns (PLO column often empty)
- Topics table has No / Topic / Contact Hours
- Course code format inconsistent: "BUS200", "CGS392", "ICS104" (no space)
- Seen in: BUS, CGS, COE, ENGL, IAS, ICS, MATH (some), PE, STAT, SWE

**Format B — DOCX "CRF2. COURSE SPECIFICATIONS" (used by math-adjacent departments)**
- Starts with a checklist table
- Has "Course Type" (Required/Elective), "Level at which course is offered"
- CLO table is richer: Code / CLOs / Aligned PLOs / Teaching Strategies / Assessment Methods all in one table
- Topics listed differently, sometimes without contact hours
- Course code format: "Math 101", "DATA 201", "AS 201" (with space)
- Has Version number and Development/Revision Date
- Seen in: MATH, DATA, AS

### Key Input Challenges

1. **Two fundamentally different document structures** (Format A vs Format B)
2. **PDF vs DOCX extraction** — table extraction from PDF is lossy; DOCX XML parsing
   splits text across many `<w:t>` elements
3. **Course code formatting** is inconsistent ("BUS200" vs "Math 101" vs "MATH 208")
4. **CLO table complexity** — Format B has 4 columns per CLO row; Format A has 3
   (but repeats CLOs in Section D with teaching/assessment)
5. **Missing data** — PLO codes are often empty, some fields say "None"
6. **Credit hours format** — "3-0-3" or "2-3-3" or "0-2-1" (Lecture-Lab-Credit)
7. **Subject Area Credit Hours** — a 2x3 table with 6 categories,
   rendered differently across formats
8. **Lab topics** — some courses have separate lab topic tables (ICS 104, CGS 392),
   some don't

## Output Template Analysis

The output ABET Syllabus template (`templates/ABETSyllabusTemplate.docx`) is significantly
**simpler and more focused** than the input:

### Key output fields:
- Course Number and Title
- Department
- Credit Hours (L, LAB, CR format)
- Credits Categorization (Math/Science, Engineering, Other)
- Course Instructor or Coordinator Name
- Textbook(s) and Supplemental Materials
- Course Content (Catalog Description)
- Prerequisites or Co-requisites
- Designation (Required / Selected Elective / Elective — with checkmark)
- CLOs mapped to Student Outcomes (SO-1, SO-2, etc.)
- Brief List of Course Topics (with weekly durations)

### Input-to-Output Mapping Observations

| Output Field | Input Source |
|---|---|
| Course Number/Title | Course Code + Course Title (both formats) |
| Department | Department field |
| Credit Hours | "Course Credit Hours" (both formats) |
| Credits Categorization | "Subject Area Credit Hours" table |
| Instructor | "Course Instructor/Coordinator" |
| Textbook | "Required Textbooks" (Section F.1) |
| Supplemental Materials | "Essential/Recommended References" + "Electronic Material" |
| Catalog Description | "Course Catalog Description" |
| Prerequisites | "Pre-requisites" (Section A.2 or A.4) |
| Designation | "Course Type" (Format B) or needs user input (Format A) |
| CLOs -> SOs | CLO table + PLO mapping (needs translation: PLO -> SO) |
| Topics | Topics table (contact hours -> weekly duration conversion) |

### Notable Gaps

- **PLO vs SO terminology**: Inputs use "PLO" (Program Learning Outcomes), output uses
  "SO" (Student Outcomes). These may be the same thing or need a mapping.
- **Designation**: Format A PDFs don't have a "Course Type" field — this must come from
  user input or be inferred from the program.
- **Topic durations**: Inputs give contact hours; output wants weekly duration like "(3 weeks)".
  Conversion depends on the credit hours pattern.
- **CLO numbering**: Input uses hierarchical codes (1.1, 1.2, 2.1); output uses flat
  numbering (CLO-1, CLO-2, ...).

## What Existed Before (v1 Prototype)

A working prototype exists at the Dropbox path with:
- React+TypeScript SPA deployed on Netlify (client-only, no backend)
- Deterministic rule-based parser targeting MATH DOCX files
- Optional AI fallback for unresolved fields (OpenAI/OpenRouter)
- Batch CLI with SQLite catalog for processing history
- CLO-PLO mapping review skill via Codex
- 30 MATH files processing at 100% success

### Validated design decisions from v1:
1. Deterministic extraction first, AI only for unresolved fields
2. Client-only web app works well for single-file processing
3. Batch CLI needed for department-wide processing
4. SQLite catalog useful for tracking courses/CLOs/PLOs across terms
5. Template-based DOCX generation works well

### Known issues from v1:
1. Parser was sample-sensitive (MATH-only), broke on unseen layouts
2. CLO text quality issues (leaked table residue from DOCX extraction)
3. Course number formatting inconsistency
4. AS/DATA programs not yet validated

## Open Questions for Discussion

1. **Fresh rewrite or port?** This directory is empty. Are we starting clean with lessons
   learned, or migrating the v1 codebase?

2. **Scope expansion**: v1 focused on MATH/AS/DATA. You said "any program in the
   university." This significantly changes the extraction strategy — we need to handle
   both Format A (PDF) and Format B (DOCX CRF2) robustly.

3. **AI-first vs rules-first**: Given the format diversity across departments, should we
   lean more heavily on LLM extraction this time? The v1 "deterministic first" approach
   worked for one format but may not scale to 13+ department variants.

4. **PLO vs SO mapping**: How does the PLO-to-SO translation work? Is there a fixed
   mapping per program? Or are SOs just PLOs renamed?

5. **Who are the target users now?** Just you on the committee, or are other faculty
   expected to use this directly?

6. **Timeline/urgency**: Is this tied to a specific ABET visit deadline?

7. **Deployment model**: Still client-only static app? Or is a lightweight backend
   acceptable now?

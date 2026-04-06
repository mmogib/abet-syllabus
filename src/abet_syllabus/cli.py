"""CLI entry point for the ABET Syllabus Generator."""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from io import StringIO
from pathlib import Path

from abet_syllabus import __version__
from abet_syllabus.parse.normalize import normalize_course_code

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = "abet_syllabus.db"


def _infer_format(output_path: str) -> str:
    """Infer export format from file extension. Returns 'json' or 'csv'."""
    if output_path.lower().endswith(".json"):
        return "json"
    return "csv"


def _format_rows(rows: list[dict], fmt: str) -> str:
    """Format a list of row dicts as CSV or JSON string."""
    if not rows:
        return "[]" if fmt == "json" else ""
    if fmt == "json":
        return json.dumps(rows, indent=2, ensure_ascii=False)
    buf = StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def _write_query_output(content: str, output_path: str | None) -> None:
    """Write content to a file or print to terminal.

    Args:
        content: The string content to write.
        output_path: File path, or None for stdout.
    """
    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        print(f"Exported to {output_path}")
    else:
        print(content, end="")


def cmd_extract(args: argparse.Namespace) -> int:
    """Extract text and tables from course specification file(s)."""
    from abet_syllabus.extract import extract_file, extract_folder

    path = Path(args.path)
    if not path.exists():
        logger.error("Path not found: %s", path)
        return 1

    if path.is_file():
        try:
            results = [extract_file(path)]
        except (ValueError, OSError) as exc:
            logger.error("Extraction failed: %s", exc)
            return 1
    elif path.is_dir():
        results = extract_folder(path, recursive=args.recursive)
    else:
        logger.error("Not a file or directory: %s", path)
        return 1

    if not results:
        print("No supported files found.")
        return 0

    for result in results:
        name = Path(result.file_path).name
        text_len = len(result.raw_text)
        table_count = len(result.tables)
        preview = result.raw_text[:200].replace("\n", " ")
        print(f"--- {name} ---")
        print(f"  Format:  {result.format_type}")
        print(f"  Tables:  {table_count}")
        print(f"  Text:    {text_len} chars")
        print(f"  Preview: {preview}...")
        print()

    return 0


def cmd_parse(args: argparse.Namespace) -> int:
    """Parse course specification file(s) and display structured data."""
    from abet_syllabus.parse import parse_file, parse_folder

    path = Path(args.path)
    if not path.exists():
        logger.error("Path not found: %s", path)
        return 1

    if path.is_file():
        try:
            courses = [parse_file(path)]
        except (ValueError, OSError) as exc:
            logger.error("Parse failed: %s", exc)
            return 1
    elif path.is_dir():
        courses = parse_folder(path, recursive=args.recursive)
    else:
        logger.error("Not a file or directory: %s", path)
        return 1

    if not courses:
        print("No supported files found.")
        return 0

    for course in courses:
        name = Path(course.source_file).name
        print(f"--- {name} ---")
        print(f"  Course Code:  {course.course_code or '(not found)'}")
        print(f"  Title:        {course.course_title or '(not found)'}")
        print(f"  Credits:      {course.credit_hours_raw or '(not found)'}")
        print(f"  Format:       {course.format_type}")
        print(f"  CLOs:         {len(course.clos)}")
        print(f"  Topics:       {len(course.topics)}")
        print(f"  Assessments:  {len(course.assessments)}")
        print(f"  Textbooks:    {len(course.textbooks)}")

        if course.warnings:
            print(f"  Warnings:")
            for w in course.warnings:
                print(f"    - {w}")

        if course.confidence:
            confs = ", ".join(
                f"{k}={v:.0%}" for k, v in sorted(course.confidence.items())
            )
            print(f"  Confidence:   {confs}")
        print()

    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    """Process course specification files into the database."""
    from abet_syllabus.ingest import ingest_file, ingest_folder
    from abet_syllabus.ingest.pipeline import prompt_plo_aliases
    from abet_syllabus.db.schema import init_db as _init_db

    path = Path(args.path)
    db_path = args.db
    force = getattr(args, "force", False)

    if not path.exists():
        logger.error("Path not found: %s", path)
        return 1

    if path.is_file():
        print(f"[1/1] {path.name}... ", end="", flush=True)
        result = ingest_file(path, db_path, program=args.program, force=force)
        print(result.status)
        results = [result]
    elif path.is_dir():
        results = _ingest_folder_with_progress(
            path, db_path, program=args.program, recursive=args.recursive, force=force
        )
    else:
        logger.error("Not a file or directory: %s", path)
        return 1

    if not results:
        print("No supported files found.")
        return 0

    # Print summary
    success = [r for r in results if r.status == "success"]
    skipped = [r for r in results if r.status == "skipped"]
    errors = [r for r in results if r.status == "error"]

    print(f"\nIngestion Summary")
    print(f"  Database:  {db_path}")
    print(f"  Program:   {args.program or '(none)'}")
    print(f"  Total:     {len(results)}")
    print(f"  Success:   {len(success)}")
    print(f"  Skipped:   {len(skipped)}")
    print(f"  Errors:    {len(errors)}")
    print()

    if success:
        print("Courses stored:")
        for r in success:
            print(f"  {r.course_code:<15} {r.file_name}")
        print()

    if skipped:
        print("Skipped (already processed):")
        for r in skipped:
            print(f"  {r.file_name}")
        print()

    if errors:
        print("Errors:")
        for r in errors:
            print(f"  {r.file_name}: {r.message}")
        print()

    # Collect unmatched PLO codes across all results and prompt for aliases
    if args.program:
        all_unmatched: set[str] = set()
        for r in results:
            all_unmatched.update(r.unmatched_plo_codes)
        if all_unmatched:
            conn = _init_db(db_path)
            try:
                prompt_plo_aliases(conn, all_unmatched, args.program)
            finally:
                conn.close()

    return 1 if errors and not success else 0


def _ingest_folder_with_progress(
    path: Path,
    db_path: str,
    program: str | None = None,
    recursive: bool = False,
    force: bool = False,
) -> list:
    """Ingest a folder with per-file progress output."""
    from abet_syllabus.extract.detector import is_supported
    from abet_syllabus.ingest import ingest_file

    # Collect supported files
    pattern = "**/*" if recursive else "*"
    files = sorted(
        p for p in path.glob(pattern)
        if p.is_file() and is_supported(p)
    )

    if not files:
        return []

    total = len(files)
    results = []
    for i, file_path in enumerate(files, 1):
        print(f"[{i}/{total}] {file_path.name}... ", end="", flush=True)
        result = ingest_file(file_path, db_path, program=program, force=force)
        print(result.status)
        results.append(result)

    return results


def cmd_ingest_plos(args: argparse.Namespace) -> int:
    """Load PLO definitions from a CSV file into the database."""
    from abet_syllabus.ingest import ingest_plos

    csv_path = Path(args.csv_path)
    if not csv_path.exists():
        logger.error("File not found: %s", csv_path)
        return 1

    try:
        count = ingest_plos(csv_path, args.db)
        print(f"Loaded {count} PLO definitions into {args.db}")
        return 0
    except Exception as exc:
        logger.error("Failed to load PLOs: %s", exc)
        return 1


def cmd_query(args: argparse.Namespace) -> int:
    """Query the course database."""
    from abet_syllabus.db import repository as repo
    from abet_syllabus.db.schema import init_db

    db_path = args.db
    db_file = Path(db_path)
    if not db_file.exists():
        logger.error("Database not found: %s", db_path)
        print("Run 'abet-syllabus ingest' first to create the database.")
        return 1

    conn = init_db(db_path)
    try:
        return _dispatch_query(conn, args)
    finally:
        conn.close()


def _dispatch_query(conn, args: argparse.Namespace) -> int:
    """Dispatch to the appropriate query subcommand."""
    from abet_syllabus.db import repository as repo

    qcmd = args.query_command

    if qcmd == "courses":
        return _query_courses(conn, args)
    elif qcmd == "course":
        return _query_course_detail(conn, args)
    elif qcmd == "clos":
        return _query_clos(conn, args)
    elif qcmd == "stats":
        return _query_stats(conn, args)
    elif qcmd == "plo-matrix":
        return _query_plo_matrix(conn, args)
    elif qcmd == "coverage":
        return _query_coverage(conn, args)
    elif qcmd == "sql":
        return _query_sql(conn, args)
    else:
        logger.error("Unknown query command: %s", qcmd)
        return 1


def _query_courses(conn, args: argparse.Namespace) -> int:
    """List all courses, optionally filtered by program."""
    from abet_syllabus.db import repository as repo

    program = getattr(args, "program", None)
    output = getattr(args, "output", None)
    courses = repo.get_all_courses(conn, program_code=program)

    if not courses:
        if program:
            print(f"No courses found for program '{program}'.")
        else:
            print("No courses in the database.")
        return 0

    if output:
        fmt = _infer_format(output)
        rows = []
        for c in courses:
            clo_count = len(repo.get_course_clos(conn, c.id))
            topic_count = len(repo.get_course_topics(conn, c.id))
            rows.append({
                "course_code": c.course_code,
                "course_title": c.course_title or "",
                "credits": c.credit_hours_raw or str(c.total_credits) or "",
                "department": c.department or "",
                "clo_count": clo_count,
                "topic_count": topic_count,
            })
        content = _format_rows(rows, fmt)
        _write_query_output(content, output)
        return 0

    # Print table header
    print(f"{'Code':<15} {'Title':<40} {'Credits':<10} {'#CLOs':<8} {'#Topics':<8}")
    print("-" * 81)

    for course in courses:
        clo_count = len(repo.get_course_clos(conn, course.id))
        topic_count = len(repo.get_course_topics(conn, course.id))
        credits = course.credit_hours_raw or str(course.total_credits) or "-"
        title = course.course_title[:38] if course.course_title else "(no title)"
        print(f"{course.course_code:<15} {title:<40} {credits:<10} {clo_count:<8} {topic_count:<8}")

    print(f"\nTotal: {len(courses)} courses")
    return 0


def _query_course_detail(conn, args: argparse.Namespace) -> int:
    """Show detailed information for a specific course."""
    from abet_syllabus.db import repository as repo

    code = normalize_course_code(args.code)
    output = getattr(args, "output", None)
    course = repo.get_course(conn, code)
    if course is None:
        logger.error("Course not found: %s", code)
        return 1

    if output:
        fmt = _infer_format(output)
        rows = [
            {"field": "course_code", "value": course.course_code or ""},
            {"field": "course_title", "value": course.course_title or ""},
            {"field": "department", "value": course.department or ""},
            {"field": "college", "value": course.college or ""},
            {"field": "credit_hours_raw", "value": course.credit_hours_raw or ""},
            {"field": "lecture_credits", "value": course.lecture_credits or ""},
            {"field": "lab_credits", "value": course.lab_credits or ""},
            {"field": "total_credits", "value": course.total_credits or ""},
            {"field": "course_type", "value": course.course_type or ""},
            {"field": "level", "value": course.level or ""},
            {"field": "prerequisites", "value": course.prerequisites or ""},
            {"field": "corequisites", "value": course.corequisites or ""},
        ]
        content = _format_rows(rows, fmt)
        _write_query_output(content, output)
        return 0

    # Basic info
    print(f"Course Code:         {course.course_code}")
    print(f"Title:               {course.course_title}")
    print(f"Department:          {course.department}")
    print(f"College:             {course.college}")
    print(f"Credits (raw):       {course.credit_hours_raw}")
    print(f"Lecture Credits:     {course.lecture_credits}")
    print(f"Lab Credits:         {course.lab_credits}")
    print(f"Total Credits:       {course.total_credits}")
    print(f"Course Type:         {course.course_type}")
    print(f"Level:               {course.level}")
    print(f"Prerequisites:       {course.prerequisites}")
    print(f"Corequisites:        {course.corequisites}")

    # Catalog description
    if course.catalog_description:
        desc = course.catalog_description
        if len(desc) > 200:
            desc = desc[:200] + "..."
        print(f"Description:         {desc}")
    print()

    # CLOs
    clos = repo.get_course_clos(conn, course.id)
    if clos:
        print(f"CLOs ({len(clos)}):")
        for clo in clos:
            text = clo.clo_text[:70] + "..." if len(clo.clo_text) > 70 else clo.clo_text
            print(f"  [{clo.clo_code}] ({clo.clo_category}) {text}")
        print()

    # Topics
    topics = repo.get_course_topics(conn, course.id)
    if topics:
        print(f"Topics ({len(topics)}):")
        for t in topics:
            hours = f"{t.contact_hours:.1f}h" if t.contact_hours else ""
            print(f"  {t.topic_number:>3}. {t.topic_title:<50} {hours}")
        print()

    # Textbooks
    textbooks = repo.get_course_textbooks(conn, course.id)
    if textbooks:
        print(f"Textbooks ({len(textbooks)}):")
        for tb in textbooks:
            text = tb.textbook_text[:80] + "..." if len(tb.textbook_text) > 80 else tb.textbook_text
            print(f"  [{tb.textbook_type}] {text}")
        print()

    # Assessments
    assessments = repo.get_course_assessments(conn, course.id)
    if assessments:
        print(f"Assessments ({len(assessments)}):")
        for a in assessments:
            pct = f"{a.proportion:.0f}%" if a.proportion else "-"
            week = a.week_due or "-"
            print(f"  {a.assessment_task:<30} {pct:>6}  (week {week})")
        print()

    return 0


def _query_clos(conn, args: argparse.Namespace) -> int:
    """List CLOs for a specific course."""
    from abet_syllabus.db import repository as repo

    code = normalize_course_code(args.code)
    output = getattr(args, "output", None)
    course = repo.get_course(conn, code)
    if course is None:
        logger.error("Course not found: %s", code)
        return 1

    clos = repo.get_course_clos(conn, course.id)
    if not clos:
        print(f"No CLOs found for {code}.")
        return 0

    if output:
        fmt = _infer_format(output)
        rows = []
        for clo in clos:
            plo_labels = _get_clo_plo_labels(conn, clo.id)
            rows.append({
                "clo_code": clo.clo_code,
                "clo_category": clo.clo_category or "",
                "clo_text": clo.clo_text,
                "aligned_plos": ", ".join(plo_labels) if plo_labels else "",
            })
        content = _format_rows(rows, fmt)
        _write_query_output(content, output)
        return 0

    print(f"CLOs for {code} ({len(clos)} total):")
    print(f"{'Code':<8} {'Category':<30} {'Text':<60} {'PLOs'}")
    print("-" * 110)

    for clo in clos:
        text = clo.clo_text[:58] + ".." if len(clo.clo_text) > 58 else clo.clo_text
        # Look up any mapped PLOs
        plo_labels = _get_clo_plo_labels(conn, clo.id)
        plo_str = ", ".join(plo_labels) if plo_labels else "-"
        print(f"{clo.clo_code:<8} {clo.clo_category:<30} {text:<60} {plo_str}")

    return 0


def _get_clo_plo_labels(conn, clo_id: int) -> list[str]:
    """Get PLO labels mapped to a specific CLO."""
    rows = conn.execute(
        """SELECT p.plo_label FROM clo_plo_mappings m
           JOIN plo_definitions p ON m.plo_id = p.id
           WHERE m.course_clo_id = ?
           ORDER BY p.sequence""",
        (clo_id,),
    ).fetchall()
    return [r["plo_label"] for r in rows]


def _query_stats(conn, args: argparse.Namespace) -> int:
    """Show database statistics."""
    from abet_syllabus.db import repository as repo

    output = getattr(args, "output", None)
    stats = repo.get_stats(conn)

    if output:
        fmt = _infer_format(output)
        rows = [
            {"metric": "Programs", "value": stats.get("programs", 0)},
            {"metric": "Courses", "value": stats.get("courses", 0)},
            {"metric": "CLOs", "value": stats.get("course_clos", 0)},
            {"metric": "Topics", "value": stats.get("course_topics", 0)},
            {"metric": "Textbooks", "value": stats.get("course_textbooks", 0)},
            {"metric": "Assessments", "value": stats.get("course_assessment", 0)},
            {"metric": "PLO Definitions", "value": stats.get("plo_definitions", 0)},
            {"metric": "CLO-PLO Mappings", "value": stats.get("clo_plo_mappings", 0)},
            {"metric": "Source Files", "value": stats.get("source_files", 0)},
        ]
        content = _format_rows(rows, fmt)
        _write_query_output(content, output)
        return 0

    print("Database Statistics")
    print("-" * 35)
    print(f"  Programs:          {stats.get('programs', 0):>6}")
    print(f"  Courses:           {stats.get('courses', 0):>6}")
    print(f"  CLOs:              {stats.get('course_clos', 0):>6}")
    print(f"  Topics:            {stats.get('course_topics', 0):>6}")
    print(f"  Textbooks:         {stats.get('course_textbooks', 0):>6}")
    print(f"  Assessments:       {stats.get('course_assessment', 0):>6}")
    print(f"  PLO Definitions:   {stats.get('plo_definitions', 0):>6}")
    print(f"  CLO-PLO Mappings:  {stats.get('clo_plo_mappings', 0):>6}")
    print(f"  Source Files:      {stats.get('source_files', 0):>6}")

    return 0


def _query_plo_matrix(conn, args: argparse.Namespace) -> int:
    """Show CLO-PLO mapping matrix for a program."""
    from abet_syllabus.db import repository as repo

    program = getattr(args, "program", None)
    output = getattr(args, "output", None)
    if not program:
        logger.error("--program / -p is required for plo-matrix")
        return 1

    courses = repo.get_all_courses(conn, program_code=program)
    if not courses:
        print(f"No courses found for program {program}.")
        return 0

    if output:
        # Use the export module's matrix function for file output
        from abet_syllabus.export import export_plo_matrix
        fmt = _infer_format(output)
        export_plo_matrix(args.db, program, fmt=fmt, output=output)
        print(f"Exported to {output}")
        return 0

    has_mappings = False
    for course in courses:
        mappings = repo.get_mappings_for_course(conn, course.id, program)
        if not mappings:
            continue

        has_mappings = True
        # Group by CLO
        clo_groups: dict[str, list[str]] = {}
        for m in mappings:
            clo_code = m["clo_code"]
            plo_label = m["plo_label"]
            if clo_code not in clo_groups:
                clo_groups[clo_code] = []
            if plo_label not in clo_groups[clo_code]:
                clo_groups[clo_code].append(plo_label)

        print(f"{course.course_code} - {course.course_title}:")
        for clo_code, plo_labels in clo_groups.items():
            plos_str = ", ".join(plo_labels)
            print(f"  {clo_code:<8} -> {plos_str}")
        print()

    if not has_mappings:
        print(f"No CLO-PLO mappings found for program {program}.")
        print("Run 'abet-syllabus map --all -p <program>' to generate mappings.")

    return 0


def _query_coverage(conn, args: argparse.Namespace) -> int:
    """Show course-level PLO coverage matrix for a program."""
    from abet_syllabus.db import repository as repo

    program = getattr(args, "program", None)
    output = getattr(args, "output", None)
    if not program:
        logger.error("--program / -p is required for coverage")
        return 1

    courses = repo.get_all_courses(conn, program_code=program)
    if not courses:
        print(f"No courses found for program {program}.")
        return 0

    plos = repo.get_plos_for_program(conn, program)
    if not plos:
        print(f"No PLO definitions found for program {program}.")
        return 0

    plo_labels = [p.plo_label for p in plos]

    # Build coverage: for each course, which PLOs are covered by any CLO?
    coverage_rows = []
    for course in courses:
        mappings = repo.get_mappings_for_course(conn, course.id, program)
        covered = set()
        for m in mappings:
            plo_label = m.get("plo_label", "")
            if plo_label:
                covered.add(plo_label)
        coverage_rows.append((course.course_code, covered))

    if output:
        fmt = _infer_format(output)
        rows = []
        for code, covered in coverage_rows:
            row: dict[str, str] = {"Course": code}
            for lbl in plo_labels:
                row[lbl] = "x" if lbl in covered else ""
            rows.append(row)
        content = _format_rows(rows, fmt)
        _write_query_output(content, output)
        return 0

    # Print header
    code_width = max(len(r[0]) for r in coverage_rows) if coverage_rows else 12
    header_labels = "  ".join(f"{lbl:>4}" for lbl in plo_labels)
    print(f"\nPLO Coverage Matrix -- Program: {program}")
    print(f"{'Course':<{code_width}}  {header_labels}")
    print("-" * (code_width + 2 + len(plo_labels) * 6))

    for code, covered in coverage_rows:
        marks = "  ".join(
            f"{'x':>4}" if lbl in covered else f"{'':>4}"
            for lbl in plo_labels
        )
        print(f"{code:<{code_width}}  {marks}")

    # Summary row: count of courses covering each PLO
    print("-" * (code_width + 2 + len(plo_labels) * 6))
    counts = []
    for lbl in plo_labels:
        count = sum(1 for _, covered in coverage_rows if lbl in covered)
        counts.append(f"{count:>4}")
    print(f"{'Total':<{code_width}}  {'  '.join(counts)}")
    print()

    return 0


def _query_sql(conn, args: argparse.Namespace) -> int:
    """Execute a read-only SQL query and display results."""
    query = args.sql_query.strip()
    output = getattr(args, "output", None)

    # Safety: only allow read-only statements
    first_word = query.split()[0].upper() if query.split() else ""
    if first_word not in ("SELECT", "WITH", "PRAGMA", "EXPLAIN"):
        logger.error("Only SELECT, WITH, PRAGMA, and EXPLAIN queries are allowed.")
        return 1

    try:
        cursor = conn.execute(query)
        rows = cursor.fetchall()
    except Exception as exc:
        logger.error("SQL error: %s", exc)
        return 1

    if not rows:
        print("(no results)")
        return 0

    # Get column names
    columns = [desc[0] for desc in cursor.description]

    if output:
        fmt = _infer_format(output)
        dict_rows = []
        for row in rows:
            dict_rows.append({
                col: (row[i] if row[i] is not None else "")
                for i, col in enumerate(columns)
            })
        content = _format_rows(dict_rows, fmt)
        _write_query_output(content, output)
        return 0

    # Calculate column widths (capped at 50)
    col_widths = [len(c) for c in columns]
    for row in rows:
        for i, val in enumerate(row):
            col_widths[i] = max(col_widths[i], len(str(val if val is not None else "")))
    col_widths = [min(w, 50) for w in col_widths]

    # Print header
    header = "  ".join(f"{c:<{col_widths[i]}}" for i, c in enumerate(columns))
    print(header)
    print("  ".join("-" * w for w in col_widths))

    # Print rows
    for row in rows:
        vals = []
        for i, val in enumerate(row):
            s = str(val if val is not None else "")
            if len(s) > col_widths[i]:
                s = s[:col_widths[i] - 3] + "..."
            vals.append(f"{s:<{col_widths[i]}}")
        print("  ".join(vals))

    print(f"\n({len(rows)} rows)")
    return 0


def _check_plos_for_mapping(db_path: str, program: str) -> bool:
    """Check that PLO definitions exist for the given program.

    If PLOs are missing, prompts the user (interactive) or logs an error
    (non-interactive).

    Returns:
        True if PLOs are available (or were just loaded), False otherwise.
    """
    from abet_syllabus.db import repository as repo
    from abet_syllabus.db.schema import init_db

    conn = init_db(db_path)
    try:
        plos = repo.get_plos_for_program(conn, program)
    finally:
        conn.close()

    if plos:
        return True

    interactive = sys.stdin.isatty()
    if interactive:
        print(f"No PLO definitions found for program '{program}'.")
        plo_path = input("Enter path to PLO CSV file (or press Enter to abort): ").strip()
        if plo_path and Path(plo_path).exists():
            from abet_syllabus.ingest import ingest_plos
            count = ingest_plos(plo_path, db_path)
            print(f"Loaded {count} PLO definitions.")
            return True

    logger.error(
        "No PLO definitions for program '%s'. "
        "Load PLOs first with: abet-syllabus ingest-plos <csv>",
        program,
    )
    return False


def cmd_map(args: argparse.Namespace) -> int:
    """Run CLO-PLO mapping for a course or program."""
    from abet_syllabus.mapping import (
        approve_mappings,
        map_course,
        map_program,
        review_mappings,
    )

    from abet_syllabus.mapping.engine import get_default_provider

    db_path = args.db
    program = args.program
    force = getattr(args, "force", False)
    do_review = getattr(args, "review", False)
    do_approve = getattr(args, "approve", False)
    map_all = getattr(args, "map_all", False)
    provider_name = getattr(args, "provider", None)
    model_name = getattr(args, "model", None)

    # --- Review mode ---
    if do_review and not map_all:
        course_code = normalize_course_code(args.course) if args.course else None
        if not course_code:
            logger.error("Course code required for --review")
            return 1
        mappings = review_mappings(db_path, course_code, program)
        if not mappings:
            print(f"No mappings found for {course_code} in {program}.")
            return 0

        print(f"Mappings for {course_code} in {program}:")
        print(f"{'CLO':<8} {'PLO':<8} {'Source':<15} {'Conf':>5} {'Appr':>5}  Rationale")
        print("-" * 90)
        for m in mappings:
            approved = "Yes" if m.get("approved") else "No"
            conf = f"{m.get('confidence', 0):.2f}"
            rationale = m.get("rationale", "")
            if len(rationale) > 40:
                rationale = rationale[:40] + "..."
            print(
                f"{m.get('clo_code', '?'):<8} "
                f"{m.get('plo_label', '?'):<8} "
                f"{m.get('mapping_source', '?'):<15} "
                f"{conf:>5} "
                f"{approved:>5}  "
                f"{rationale}"
            )
        return 0

    # --- Approve mode ---
    if do_approve and not map_all:
        course_code = normalize_course_code(args.course) if args.course else None
        if not course_code:
            logger.error("Course code required for --approve")
            return 1
        count = approve_mappings(db_path, course_code, program)
        if count > 0:
            print(f"Approved {count} mapping(s) for {course_code} in {program}.")
        else:
            print(f"No pending AI-suggested mappings to approve for {course_code} in {program}.")
        return 0

    # --- PLO check before mapping ---
    if not do_review and not do_approve:
        if not _check_plos_for_mapping(db_path, program):
            return 1

    # --- Map all courses in a program ---
    if map_all:
        try:
            provider = get_default_provider(provider_name, model=model_name)
            all_results = map_program(db_path, program, provider=provider, force=force)
        except ValueError as exc:
            logger.error("Mapping failed: %s", exc)
            return 1
        except RuntimeError as exc:
            logger.error("API error: %s", exc)
            return 1

        if not all_results:
            print(f"No courses found for program {program}.")
            return 0

        total = 0
        for course_code, results in all_results.items():
            count = len(results)
            total += count
            if count > 0:
                print(f"  {course_code}: {count} mapping(s) suggested")
            else:
                print(f"  {course_code}: already mapped (skipped)")

        print(f"\nTotal: {total} mapping(s) suggested for {program}.")
        return 0

    # --- Map a single course ---
    course_code = normalize_course_code(args.course) if args.course else None
    if not course_code:
        logger.error("Course code required (or use --all)")
        return 1

    try:
        provider = get_default_provider(provider_name, model=model_name)
        results = map_course(db_path, course_code, program, provider=provider, force=force)
    except ValueError as exc:
        logger.error("Mapping failed: %s", exc)
        return 1
    except RuntimeError as exc:
        logger.error("API error: %s", exc)
        return 1

    if not results:
        print(f"All CLOs already mapped for {course_code} in {program}.")
        return 0

    print(f"Mapping results for {course_code} in {program}:")
    print(f"{'CLO':<8} {'PLO':<8} {'Conf':>5}  Rationale")
    print("-" * 70)
    for r in results:
        rationale = r.rationale
        if len(rationale) > 45:
            rationale = rationale[:45] + "..."
        print(f"{r.clo_code:<8} {r.plo_code:<8} {r.confidence:>5.2f}  {rationale}")

    print(f"\nTotal: {len(results)} mapping(s) suggested.")
    print(f"Use 'abet-syllabus map \"{course_code}\" -p {program} --review' to review.")
    print(f"Use 'abet-syllabus map \"{course_code}\" -p {program} --approve' to approve.")
    return 0


def cmd_generate(args: argparse.Namespace) -> int:
    """Generate ABET syllabus documents."""
    from abet_syllabus.generate import generate_syllabus, generate_program

    db_path = args.db
    db_file = Path(db_path)
    if not db_file.exists():
        logger.error("Database not found: %s", db_path)
        print("Run 'abet-syllabus ingest' first to create the database.")
        return 1

    template = getattr(args, "template", None)
    output_dir = args.output
    no_pdf = getattr(args, "no_pdf", False)
    gen_pdf = not no_pdf
    instructor = getattr(args, "instructor", None)

    if args.gen_all:
        if not args.program:
            logger.error("--program is required with --all")
            return 1

        results = generate_program(
            db_path=db_path,
            program_code=args.program,
            term=args.term,
            template_path=template,
            output_dir=output_dir,
            pdf=gen_pdf,
        )
    else:
        if not args.course:
            logger.error("Provide a course code or use --all")
            return 1

        course_code = normalize_course_code(args.course)
        result = generate_syllabus(
            db_path=db_path,
            course_code=course_code,
            program_code=args.program,
            term=args.term,
            instructor=instructor,
            template_path=template,
            output_dir=output_dir,
            pdf=gen_pdf,
        )
        results = [result]

    # Print results with progress for batch
    success = [r for r in results if r.status == "success"]
    errors = [r for r in results if r.status == "error"]

    if success:
        print(f"\nGenerated {len(success)} syllabus document(s):")
        for r in success:
            print(f"  {r.course_code}: {r.message}")
            if r.docx_path:
                print(f"    DOCX: {r.docx_path}")
            if r.pdf_path:
                print(f"    PDF:  {r.pdf_path}")

    if errors:
        print(f"\nErrors ({len(errors)}):")
        for r in errors:
            print(f"  {r.course_code or '(unknown)'}: {r.message}")

    return 1 if errors and not success else 0


def _confirm_or_fail(prompt_msg: str, default_yes: bool = True) -> bool:
    """Prompt the user for confirmation if stdin is a tty.

    Returns True if confirmed. Raises SystemExit with a helpful message
    if stdin is not a tty (non-interactive mode).
    """
    if not sys.stdin.isatty():
        return False

    suffix = " [Y/n]: " if default_yes else " [y/N]: "
    try:
        answer = input(prompt_msg + suffix).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False

    if not answer:
        return default_yes
    return answer in ("y", "yes")


def _list_subdirs(root: Path, max_depth: int = 4) -> list[Path]:
    """Recursively list all subdirectories up to max_depth, relative to root."""
    dirs: list[Path] = []

    def _walk(current: Path, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            children = sorted(current.iterdir())
        except OSError:
            return
        for child in children:
            if child.is_dir() and not child.name.startswith("."):
                dirs.append(child)
                _walk(child, depth + 1)

    _walk(root, 1)
    return dirs


def _browse_folder(prompt_msg: str) -> Path:
    """Interactive folder browser. Lists all subdirs and lets user pick."""
    cwd = Path.cwd()
    dirs = _list_subdirs(cwd)

    if not dirs:
        user_path = input(f"{prompt_msg}: ").strip()
        if user_path:
            return Path(user_path)
        logger.error("No path provided.")
        sys.exit(1)

    print(f"\n{prompt_msg}:")
    for i, d in enumerate(dirs, 1):
        try:
            rel = d.relative_to(cwd)
        except ValueError:
            rel = d
        print(f"  {i}) {rel}/")

    choice = input(f"\nEnter number [1-{len(dirs)}] or path: ").strip()
    if choice.isdigit() and 1 <= int(choice) <= len(dirs):
        return dirs[int(choice) - 1]
    elif choice:
        return Path(choice)

    logger.error("No path provided.")
    sys.exit(1)


def _resolve_run_defaults(args: argparse.Namespace) -> tuple[Path, str | None, str | None, str | None]:
    """Resolve smart defaults for the 'run' command.

    Returns (path, program, term, output_dir) with defaults applied.
    Prompts interactively when stdin is a tty and info is missing.
    """
    from abet_syllabus.term import get_current_term

    interactive = sys.stdin.isatty()

    # --- Resolve input path ---
    path_arg = getattr(args, "path", None)
    if path_arg:
        path = Path(path_arg)
    elif interactive:
        path = _browse_folder("Select input folder")
        print(f"Using: {path}")
    else:
        logger.error("No input path specified. Use: abet-syllabus run <path>")
        sys.exit(1)

    # --- Resolve program ---
    program = args.program
    if not program and interactive:
        program = input("Program code (e.g. MATH, DATA, AS): ").strip().upper()
        if not program:
            program = None
    elif not program:
        # Non-interactive: program is optional, leave as None
        pass

    # --- Resolve term ---
    term = args.term
    if not term:
        current_term = get_current_term()
        if interactive:
            user_term = input(f"Term [{current_term}]: ").strip()
            if user_term:
                user_term = user_term.upper()
                if user_term.isdigit():
                    user_term = f"T{user_term}"
                term = user_term
            else:
                term = current_term
        else:
            term = current_term
            print(f"Using current term: {term}")

    # --- Resolve output ---
    output_dir = args.output
    if not output_dir:
        output_dir = str(Path.cwd() / "output")

    return path, program, term, output_dir


def cmd_run(args: argparse.Namespace) -> int:
    """Run the full pipeline: ingest files then generate syllabi."""
    from abet_syllabus.ingest import ingest_file
    from abet_syllabus.generate import generate_syllabus

    # Resolve smart defaults
    path, program, term, output_dir = _resolve_run_defaults(args)

    db_path = args.db
    template = getattr(args, "template", None)
    no_pdf = getattr(args, "no_pdf", False)
    gen_pdf = not no_pdf
    instructor = getattr(args, "instructor", None)
    do_map = getattr(args, "map", False)
    force = getattr(args, "force", False)

    if not path.exists():
        logger.error("Path not found: %s", path)
        return 1

    # --- Step 1: Ingest ---
    print("=== Step 1: Ingesting course files ===\n")

    if path.is_file():
        print(f"[1/1] {path.name}... ", end="", flush=True)
        result = ingest_file(path, db_path, program=program, force=force)
        print(result.status)
        ingest_results = [result]
    elif path.is_dir():
        ingest_results = _ingest_folder_with_progress(
            path, db_path, program=program, recursive=args.recursive, force=force
        )
    else:
        logger.error("Not a file or directory: %s", path)
        return 1

    if not ingest_results:
        print("No supported files found.")
        return 0

    # Collect course codes from successful + skipped ingestions
    course_codes = []
    for r in ingest_results:
        if r.status in ("success", "skipped") and r.course_code:
            if r.course_code not in course_codes:
                course_codes.append(r.course_code)

    success_count = sum(1 for r in ingest_results if r.status == "success")
    skipped_count = sum(1 for r in ingest_results if r.status == "skipped")
    error_count = sum(1 for r in ingest_results if r.status == "error")

    print(f"\nIngested: {success_count} success, {skipped_count} skipped, {error_count} errors")

    if not course_codes:
        print("No courses to generate syllabi for.")
        return 1 if error_count else 0

    # --- Step 1.5: Mapping (optional, when --map is set) ---
    if do_map and program:
        print(f"\n=== Step 1.5: CLO-PLO Mapping ===\n")
        model_name = getattr(args, "model", None)
        _run_mapping_step(db_path, course_codes, program, model=model_name)

    # --- Step 2: Generate ---
    print(f"\n=== Step 2: Generating {len(course_codes)} syllabus document(s) ===\n")

    gen_results = []
    for i, code in enumerate(course_codes, 1):
        print(f"[{i}/{len(course_codes)}] {code}... ", end="", flush=True)
        result = generate_syllabus(
            db_path=db_path,
            course_code=code,
            program_code=program,
            term=term,
            instructor=instructor,
            template_path=template,
            output_dir=output_dir,
            pdf=gen_pdf,
        )
        print(result.status)
        gen_results.append(result)

    # --- Summary ---
    gen_success = [r for r in gen_results if r.status == "success"]
    gen_errors = [r for r in gen_results if r.status == "error"]

    print(f"\n=== Summary ===")
    print(f"  Files processed:  {len(ingest_results)}")
    print(f"  Courses ingested: {success_count}")
    print(f"  Syllabi generated: {len(gen_success)}")
    if gen_errors:
        print(f"  Generation errors: {len(gen_errors)}")
        for r in gen_errors:
            print(f"    {r.course_code or '(unknown)'}: {r.message}")

    if gen_success:
        print(f"\nOutput files:")
        for r in gen_success:
            if r.docx_path:
                print(f"  {r.docx_path}")

    return 1 if gen_errors and not gen_success else 0


def _run_mapping_step(db_path: str, course_codes: list[str], program: str, model: str | None = None) -> None:
    """Run CLO-PLO mapping for courses when --map is set.

    Warns and skips if no API key is available or PLOs are missing.
    """
    from abet_syllabus.db import repository as repo
    from abet_syllabus.db.schema import init_db
    from abet_syllabus.mapping.engine import get_default_provider, map_course

    # Check if PLOs exist for this program
    conn = init_db(db_path)
    try:
        plos = repo.get_plos_for_program(conn, program)
    finally:
        conn.close()

    if not plos:
        interactive = sys.stdin.isatty()
        if interactive:
            print(f"No PLO definitions found for program '{program}'.")
            plo_path = input("Enter path to PLO CSV file (or press Enter to skip mapping): ").strip()
            if plo_path and Path(plo_path).exists():
                from abet_syllabus.ingest import ingest_plos
                count = ingest_plos(plo_path, db_path)
                print(f"Loaded {count} PLO definitions.")
            else:
                print("Skipping mapping step (no PLOs).")
                return
        else:
            print(f"Warning: No PLO definitions for '{program}'. Skipping mapping.")
            print(f"Load PLOs first with: abet-syllabus ingest-plos <csv>")
            return

    # Get provider
    try:
        provider = get_default_provider(model=model)
    except ValueError:
        print("Warning: No API key found (OPENROUTER_API_KEY or ANTHROPIC_API_KEY).")
        print("Skipping mapping step. Set an API key to enable CLO-PLO mapping.")
        return

    total = len(course_codes)
    for i, code in enumerate(course_codes, 1):
        print(f"[{i}/{total}] {code}... ", end="", flush=True)
        try:
            results = map_course(db_path, code, program, provider=provider)
            print(f"{len(results)} mappings")
        except ValueError as exc:
            print(f"skipped ({exc})")
        except RuntimeError as exc:
            print(f"error ({exc})")
            logger.warning("Mapping failed for %s: %s", code, exc)


def cmd_status(args: argparse.Namespace) -> int:
    """Show database status and summary."""
    from abet_syllabus.db import repository as repo
    from abet_syllabus.db.schema import init_db

    db_path = args.db
    db_file = Path(db_path)
    if not db_file.exists():
        logger.error("Database not found: %s", db_path)
        print("No database found. Run 'abet-syllabus ingest' first.")
        return 1

    conn = init_db(db_path)
    try:
        # Programs
        programs = repo.get_programs(conn)
        program_codes = [p.program_code for p in programs]

        # Courses
        all_courses = repo.get_all_courses(conn)
        total_courses = len(all_courses)

        # Per-course data counts
        with_clos = 0
        with_topics = 0
        with_textbooks = 0
        with_assessments = 0
        ready_count = 0

        for course in all_courses:
            has_clos = len(repo.get_course_clos(conn, course.id)) > 0
            has_topics = len(repo.get_course_topics(conn, course.id)) > 0
            has_textbooks = len(repo.get_course_textbooks(conn, course.id)) > 0
            has_assessments = len(repo.get_course_assessments(conn, course.id)) > 0

            if has_clos:
                with_clos += 1
            if has_topics:
                with_topics += 1
            if has_textbooks:
                with_textbooks += 1
            if has_assessments:
                with_assessments += 1

            # Minimum required data: title + CLOs
            has_title = bool(course.course_title and course.course_title.strip())
            if has_title and has_clos:
                ready_count += 1

        # CLO-PLO mappings
        stats = repo.get_stats(conn)
        total_mappings = stats.get("clo_plo_mappings", 0)

        # Count by source
        extracted = conn.execute(
            "SELECT COUNT(*) as c FROM clo_plo_mappings WHERE mapping_source = 'extracted'"
        ).fetchone()["c"]
        ai_suggested = conn.execute(
            "SELECT COUNT(*) as c FROM clo_plo_mappings WHERE mapping_source = 'ai_suggested'"
        ).fetchone()["c"]
        approved = conn.execute(
            "SELECT COUNT(*) as c FROM clo_plo_mappings WHERE approved = 1"
        ).fetchone()["c"]

        # Source files
        source_files = stats.get("source_files", 0)
        last_ingested_row = conn.execute(
            "SELECT MAX(processed_at) as last_at FROM source_files"
        ).fetchone()
        last_ingested = last_ingested_row["last_at"] if last_ingested_row else None

        # Output
        print(f"Database: {db_path}")
        prog_list = ", ".join(program_codes) if program_codes else "(none)"
        print(f"Programs: {len(programs)} ({prog_list})")
        print(f"Courses: {total_courses}")
        print(f"  - With CLOs: {with_clos}/{total_courses}")
        print(f"  - With topics: {with_topics}/{total_courses}")
        print(f"  - With textbooks: {with_textbooks}/{total_courses}")
        print(f"  - With assessments: {with_assessments}/{total_courses}")
        print()
        print("CLO-PLO Mappings:")
        print(f"  - Total mappings: {total_mappings}")
        print(f"  - Extracted: {extracted}")
        print(f"  - AI suggested: {ai_suggested}")
        print(f"  - Approved: {approved}")
        print()
        print(f"Source files: {source_files}")
        if last_ingested:
            print(f"  - Last ingested: {last_ingested}")
        print()
        print(f"Ready to generate: {ready_count}/{total_courses} courses have minimum required data")

    finally:
        conn.close()

    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    """Validate data quality in the database."""
    from abet_syllabus.validate import validate_database

    db_path = args.db
    db_file = Path(db_path)
    if not db_file.exists():
        logger.error("Database not found: %s", db_path)
        print("No database found. Run 'abet-syllabus ingest' first.")
        return 1

    program = getattr(args, "program", None)
    report = validate_database(db_path, program_code=program)

    print(report.format())

    # Return 1 if there are errors
    return 1 if report.errors else 0


def cmd_plo_alias(args: argparse.Namespace) -> int:
    """Manage PLO aliases (create, list, delete)."""
    from abet_syllabus.db import repository as repo
    from abet_syllabus.db.models import Program
    from abet_syllabus.db.schema import init_db

    db_path = args.db
    program = args.program

    conn = init_db(db_path)
    try:
        # Ensure program exists
        programs = repo.get_programs(conn)
        program_codes = [p.program_code for p in programs]
        if program not in program_codes:
            # Create program if it doesn't exist
            repo.upsert_program(conn, Program(program_code=program))

        # --- List mode ---
        if getattr(args, "list_aliases", False):
            aliases = repo.get_plo_aliases(conn, program)
            if not aliases:
                print(f"No PLO aliases defined for program {program}.")
                return 0

            print(f"PLO aliases for {program}:")
            print(f"  {'Alias':<10} {'Maps to':<15} {'PLO Label'}")
            print(f"  {'-'*10} {'-'*15} {'-'*15}")
            for a in aliases:
                # Look up the PLO label
                plo = conn.execute(
                    "SELECT plo_code, plo_label FROM plo_definitions WHERE id = ?",
                    (a.plo_id,),
                ).fetchone()
                plo_code = plo["plo_code"] if plo else "?"
                plo_label = plo["plo_label"] if plo else "?"
                print(f"  {a.alias:<10} {plo_code:<15} {plo_label}")
            return 0

        # --- Delete mode ---
        if getattr(args, "delete", False):
            alias_name = args.alias
            if not alias_name:
                logger.error("Alias name required for --delete")
                return 1
            deleted = repo.delete_plo_alias(conn, program, alias_name)
            if deleted:
                print(f"Deleted alias '{alias_name}' for program {program}.")
            else:
                print(f"Alias '{alias_name}' not found for program {program}.")
            return 0

        # --- Create mode ---
        alias_name = args.alias
        target_label = args.target
        if not alias_name or not target_label:
            logger.error("Both alias and target PLO label are required.")
            logger.error("Usage: abet-syllabus plo-alias K1 SO1 -p MATH")
            return 1

        # Resolve target PLO
        plos = repo.get_plos_for_program(conn, program)
        if not plos:
            logger.error("No PLO definitions found for program %s.", program)
            return 1

        target_plo = None
        for p in plos:
            if p.plo_label == target_label or p.plo_code == target_label:
                target_plo = p
                break

        if target_plo is None:
            plo_labels = ", ".join(p.plo_label for p in plos)
            logger.error(
                "PLO '%s' not found for program %s. Available: %s",
                target_label, program, plo_labels,
            )
            return 1

        repo.upsert_plo_alias(conn, program, alias_name, target_plo.id)
        print(f"Alias created: {alias_name} -> {target_plo.plo_label} ({target_plo.plo_code}) for {program}")
        return 0

    finally:
        conn.close()


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="abet-syllabus",
        description="Generate ABET-compliant course syllabi from course specifications.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )

    # Global flags
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable verbose (DEBUG) logging output",
    )
    parser.add_argument(
        "--quiet", "-q", action="store_true",
        help="Suppress all logging except warnings and errors",
    )
    parser.add_argument(
        "--config", default=None,
        help="Path to a YAML configuration file",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # --- run (full pipeline) ---
    p_run = subparsers.add_parser(
        "run",
        help="Full pipeline: ingest course files then generate ABET syllabi",
    )
    p_run.add_argument("path", nargs="?", default=None,
                        help="Path to a file or directory to process (defaults to ./input/)")
    p_run.add_argument(
        "--program", "-p", default=None,
        help="Program code (e.g., MATH, AS, DATA)",
    )
    p_run.add_argument("--term", "-t", default=None, help="Term code (e.g., T252)")
    p_run.add_argument(
        "--output", "-o", default=None,
        help="Output directory for generated syllabi (default: ./output/)",
    )
    p_run.add_argument(
        "--recursive", "-r", action="store_true",
        help="Process subdirectories",
    )
    p_run.add_argument(
        "--no-pdf", action="store_true",
        help="Skip PDF generation (DOCX only)",
    )
    p_run.add_argument(
        "--template", default=None,
        help="Path to DOCX template",
    )
    p_run.add_argument(
        "--instructor", default=None,
        help="Instructor name to include",
    )
    p_run.add_argument(
        "--map", action="store_true",
        help="Run CLO-PLO mapping after ingestion (requires API key)",
    )
    p_run.add_argument(
        "--model", default=None,
        help="AI model for mapping (e.g., 'google/gemini-2.5-flash')",
    )
    p_run.add_argument(
        "--force", "-f", action="store_true",
        help="Re-process files even if already ingested",
    )
    p_run.add_argument(
        "--db", default=DEFAULT_DB_PATH,
        help=f"Database path (default: {DEFAULT_DB_PATH})",
    )
    p_run.set_defaults(func=cmd_run)

    # --- extract ---
    p_extract = subparsers.add_parser(
        "extract",
        help="Extract text and tables from course specification file(s)",
    )
    p_extract.add_argument("path", help="Path to a file or directory to extract")
    p_extract.add_argument(
        "--recursive", "-r", action="store_true",
        help="Process subdirectories",
    )
    p_extract.set_defaults(func=cmd_extract)

    # --- parse ---
    p_parse = subparsers.add_parser(
        "parse",
        help="Parse course specification file(s) and show structured data",
    )
    p_parse.add_argument("path", help="Path to a file or directory to parse")
    p_parse.add_argument(
        "--recursive", "-r", action="store_true",
        help="Process subdirectories",
    )
    p_parse.set_defaults(func=cmd_parse)

    # --- ingest ---
    p_ingest = subparsers.add_parser(
        "ingest",
        help="Process course specification file(s) into the database",
    )
    p_ingest.add_argument("path", help="Path to a file or directory to process")
    p_ingest.add_argument(
        "--program", "-p", default=None,
        help="Program code (e.g., MATH, AS, DATA)",
    )
    p_ingest.add_argument(
        "--recursive", "-r", action="store_true",
        help="Process subdirectories",
    )
    p_ingest.add_argument(
        "--force", "-f", action="store_true",
        help="Re-process files even if already ingested",
    )
    p_ingest.add_argument(
        "--db", default=DEFAULT_DB_PATH,
        help=f"Database path (default: {DEFAULT_DB_PATH})",
    )
    p_ingest.set_defaults(func=cmd_ingest)

    # --- ingest-plos ---
    p_ingest_plos = subparsers.add_parser(
        "ingest-plos",
        help="Load PLO definitions from a CSV file",
    )
    p_ingest_plos.add_argument("csv_path", help="Path to the PLO definitions CSV file")
    p_ingest_plos.add_argument(
        "--db", default=DEFAULT_DB_PATH,
        help=f"Database path (default: {DEFAULT_DB_PATH})",
    )
    p_ingest_plos.set_defaults(func=cmd_ingest_plos)

    # --- query ---
    p_query = subparsers.add_parser("query", help="Query the course database")
    p_query.add_argument(
        "--db", default=DEFAULT_DB_PATH,
        help=f"Database path (default: {DEFAULT_DB_PATH})",
    )
    query_sub = p_query.add_subparsers(dest="query_command", help="Query subcommands")

    q_courses = query_sub.add_parser("courses", help="List all courses")
    q_courses.add_argument("--program", "-p", default=None, help="Filter by program")
    q_courses.add_argument("--output", "-o", default=None,
                           help="Write to file (format inferred from extension: .json or .csv)")
    q_courses.set_defaults(func=cmd_query)

    q_course = query_sub.add_parser("course", help="Show details for a course")
    q_course.add_argument("code", help="Course code (e.g., 'MATH 101')")
    q_course.add_argument("--output", "-o", default=None,
                          help="Write to file (format inferred from extension: .json or .csv)")
    q_course.set_defaults(func=cmd_query)

    q_clos = query_sub.add_parser("clos", help="List CLOs for a course")
    q_clos.add_argument("code", help="Course code")
    q_clos.add_argument("--output", "-o", default=None,
                        help="Write to file (format inferred from extension: .json or .csv)")
    q_clos.set_defaults(func=cmd_query)

    q_stats = query_sub.add_parser("stats", help="Show database statistics")
    q_stats.add_argument("--output", "-o", default=None,
                         help="Write to file (format inferred from extension: .json or .csv)")
    q_stats.set_defaults(func=cmd_query)

    q_plo_matrix = query_sub.add_parser("plo-matrix", help="Show CLO-PLO mapping matrix")
    q_plo_matrix.add_argument("--program", "-p", required=True, help="Program code")
    q_plo_matrix.add_argument("--output", "-o", default=None,
                              help="Write to file (format inferred from extension: .json or .csv)")
    q_plo_matrix.set_defaults(func=cmd_query)

    q_coverage = query_sub.add_parser("coverage", help="Show course-level PLO coverage matrix")
    q_coverage.add_argument("--program", "-p", required=True, help="Program code")
    q_coverage.add_argument("--output", "-o", default=None,
                            help="Write to file (format inferred from extension: .json or .csv)")
    q_coverage.set_defaults(func=cmd_query)

    q_sql = query_sub.add_parser("sql", help="Execute a read-only SQL query")
    q_sql.add_argument("sql_query", help="SQL query (SELECT only)")
    q_sql.add_argument("--output", "-o", default=None,
                       help="Write to file (format inferred from extension: .json or .csv)")
    q_sql.set_defaults(func=cmd_query)

    # --- map ---
    p_map = subparsers.add_parser("map", help="Run CLO-PLO mapping for a course")
    p_map.add_argument("course", nargs="?", default=None, help="Course code (e.g., 'MATH 101')")
    p_map.add_argument(
        "--program", "-p", required=True,
        help="Program code (e.g., MATH)",
    )
    p_map.add_argument(
        "--db", default=DEFAULT_DB_PATH,
        help=f"Database path (default: {DEFAULT_DB_PATH})",
    )
    p_map.add_argument(
        "--review", action="store_true",
        help="Show current mappings for review",
    )
    p_map.add_argument(
        "--approve", action="store_true",
        help="Mark mappings as approved",
    )
    p_map.add_argument(
        "--all", dest="map_all", action="store_true",
        help="Map all unmapped courses in the program",
    )
    p_map.add_argument(
        "--force", "-f", action="store_true",
        help="Re-map even if mappings already exist",
    )
    p_map.add_argument(
        "--provider", default=None, choices=["anthropic", "openrouter"],
        help="AI provider (default: auto-detect from API keys)",
    )
    p_map.add_argument(
        "--model", default=None,
        help="AI model identifier (e.g., 'anthropic/claude-sonnet-4'). "
             "Defaults to provider's default model.",
    )
    p_map.set_defaults(func=cmd_map)

    # --- generate ---
    p_gen = subparsers.add_parser("generate", help="Generate ABET syllabus document(s)")
    p_gen.add_argument(
        "course", nargs="?", default=None,
        help="Course code (e.g., 'MATH 101')",
    )
    p_gen.add_argument("--program", "-p", default=None, help="Program code")
    p_gen.add_argument("--term", "-t", default=None, help="Term code (e.g., T252)")
    p_gen.add_argument(
        "--output", "-o", default=None,
        help="Output directory (default: current dir)",
    )
    p_gen.add_argument(
        "--all", dest="gen_all", action="store_true",
        help="Generate for all courses in a program",
    )
    p_gen.add_argument(
        "--no-pdf", action="store_true",
        help="Skip PDF generation (DOCX only)",
    )
    p_gen.add_argument(
        "--template", default=None,
        help="Path to DOCX template (default: resources/templates/ABETSyllabusTemplate.docx)",
    )
    p_gen.add_argument(
        "--instructor", default=None,
        help="Instructor name to include in the syllabus",
    )
    p_gen.add_argument(
        "--db", default=DEFAULT_DB_PATH,
        help=f"Database path (default: {DEFAULT_DB_PATH})",
    )
    p_gen.set_defaults(func=cmd_generate)

    # --- status ---
    p_status = subparsers.add_parser("status", help="Show database status and summary")
    p_status.add_argument(
        "--db", default=DEFAULT_DB_PATH,
        help=f"Database path (default: {DEFAULT_DB_PATH})",
    )
    p_status.set_defaults(func=cmd_status)

    # --- validate ---
    p_validate = subparsers.add_parser("validate", help="Validate data quality")
    p_validate.add_argument(
        "--db", default=DEFAULT_DB_PATH,
        help=f"Database path (default: {DEFAULT_DB_PATH})",
    )
    p_validate.add_argument(
        "--program", "-p", default=None,
        help="Program code to scope validation",
    )
    p_validate.set_defaults(func=cmd_validate)

    # --- plo-alias ---
    p_alias = subparsers.add_parser(
        "plo-alias",
        help="Manage PLO aliases (alternative codes that map to PLO definitions)",
    )
    p_alias.add_argument(
        "alias", nargs="?", default=None,
        help="Alias code (e.g., K1)",
    )
    p_alias.add_argument(
        "target", nargs="?", default=None,
        help="Target PLO label or code (e.g., SO1)",
    )
    p_alias.add_argument(
        "--program", "-p", required=True,
        help="Program code (e.g., MATH)",
    )
    p_alias.add_argument(
        "--list", dest="list_aliases", action="store_true",
        help="List all aliases for the program",
    )
    p_alias.add_argument(
        "--delete", action="store_true",
        help="Delete the specified alias",
    )
    p_alias.add_argument(
        "--db", default=DEFAULT_DB_PATH,
        help=f"Database path (default: {DEFAULT_DB_PATH})",
    )
    p_alias.set_defaults(func=cmd_plo_alias)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 1

    # Setup logging based on global flags
    from abet_syllabus.logging_config import setup_logging
    from abet_syllabus.config import Config

    # Load config
    config_path = getattr(args, "config", None)
    config = Config.load(config_path)

    # Apply config defaults to args if not explicitly set
    verbose = getattr(args, "verbose", False)
    quiet = getattr(args, "quiet", False)

    # Determine log file from config
    log_file = config.log_file if not quiet else None

    setup_logging(verbose=verbose, quiet=quiet, log_file=log_file)

    # Apply config db_path as default if args.db is the default
    if hasattr(args, "db") and args.db == DEFAULT_DB_PATH:
        args.db = config.db_path

    # Normalize user input globally before dispatching
    # Program code: uppercase (math → MATH)
    if hasattr(args, "program") and args.program:
        args.program = args.program.upper()
    # Course code: normalize (math101 → MATH 101)
    if hasattr(args, "course") and args.course:
        args.course = normalize_course_code(args.course)
    if hasattr(args, "code") and args.code:
        args.code = normalize_course_code(args.code)

    if hasattr(args, "func"):
        return args.func(args)

    parser.print_help()
    return 1


def main_cli() -> None:
    """Entry point for console_scripts (no return value)."""
    sys.exit(main())


if __name__ == "__main__":
    sys.exit(main())

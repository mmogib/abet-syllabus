"""CLI entry point for the ABET Syllabus Generator."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from abet_syllabus import __version__

DEFAULT_DB_PATH = "abet_syllabus.db"


def cmd_extract(args: argparse.Namespace) -> int:
    """Extract text and tables from course specification file(s)."""
    from abet_syllabus.extract import extract_file, extract_folder

    path = Path(args.path)
    if not path.exists():
        print(f"Error: path not found: {path}", file=sys.stderr)
        return 1

    if path.is_file():
        try:
            results = [extract_file(path)]
        except (ValueError, OSError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
    elif path.is_dir():
        results = extract_folder(path, recursive=args.recursive)
    else:
        print(f"Error: not a file or directory: {path}", file=sys.stderr)
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
        print(f"Error: path not found: {path}", file=sys.stderr)
        return 1

    if path.is_file():
        try:
            courses = [parse_file(path)]
        except (ValueError, OSError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
    elif path.is_dir():
        courses = parse_folder(path, recursive=args.recursive)
    else:
        print(f"Error: not a file or directory: {path}", file=sys.stderr)
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

    path = Path(args.path)
    db_path = args.db

    if not path.exists():
        print(f"Error: path not found: {path}", file=sys.stderr)
        return 1

    if path.is_file():
        results = [ingest_file(path, db_path, program=args.program)]
    elif path.is_dir():
        results = ingest_folder(path, db_path, program=args.program, recursive=args.recursive)
    else:
        print(f"Error: not a file or directory: {path}", file=sys.stderr)
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

    return 1 if errors and not success else 0


def cmd_ingest_plos(args: argparse.Namespace) -> int:
    """Load PLO definitions from a CSV file into the database."""
    from abet_syllabus.ingest import ingest_plos

    csv_path = Path(args.csv_path)
    if not csv_path.exists():
        print(f"Error: file not found: {csv_path}", file=sys.stderr)
        return 1

    try:
        count = ingest_plos(csv_path, args.db)
        print(f"Loaded {count} PLO definitions into {args.db}")
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def cmd_query(args: argparse.Namespace) -> int:
    """Query the course database."""
    from abet_syllabus.db import repository as repo
    from abet_syllabus.db.schema import init_db

    db_path = args.db
    db_file = Path(db_path)
    if not db_file.exists():
        print(f"Error: database not found: {db_path}", file=sys.stderr)
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
        return _query_stats(conn)
    elif qcmd == "plo-matrix":
        return _query_plo_matrix(conn, args)
    else:
        print(f"Unknown query command: {qcmd}", file=sys.stderr)
        return 1


def _query_courses(conn, args: argparse.Namespace) -> int:
    """List all courses, optionally filtered by program."""
    from abet_syllabus.db import repository as repo

    program = getattr(args, "program", None)
    courses = repo.get_all_courses(conn, program_code=program)

    if not courses:
        if program:
            print(f"No courses found for program '{program}'.")
        else:
            print("No courses in the database.")
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

    code = args.code.upper()
    course = repo.get_course(conn, code)
    if course is None:
        print(f"Course not found: {code}", file=sys.stderr)
        return 1

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

    code = args.code.upper()
    course = repo.get_course(conn, code)
    if course is None:
        print(f"Course not found: {code}", file=sys.stderr)
        return 1

    clos = repo.get_course_clos(conn, course.id)
    if not clos:
        print(f"No CLOs found for {code}.")
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


def _query_stats(conn) -> int:
    """Show database statistics."""
    from abet_syllabus.db import repository as repo

    stats = repo.get_stats(conn)

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
    from abet_syllabus.mapping.engine import export_plo_matrix

    program = getattr(args, "program", None)
    if not program:
        print("Error: --program / -p is required for plo-matrix", file=sys.stderr)
        return 1

    # We need db_path for the engine function; reconstruct from conn
    # Actually, export_plo_matrix needs db_path, but we already have conn.
    # Re-implement using conn directly to avoid opening a second connection.
    from abet_syllabus.db import repository as repo

    courses = repo.get_all_courses(conn, program_code=program)
    if not courses:
        print(f"No courses found for program {program}.")
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


def cmd_map(args: argparse.Namespace) -> int:
    """Run CLO-PLO mapping for a course or program."""
    from abet_syllabus.mapping import (
        approve_mappings,
        map_course,
        map_program,
        review_mappings,
    )

    db_path = args.db
    program = args.program
    force = getattr(args, "force", False)
    do_review = getattr(args, "review", False)
    do_approve = getattr(args, "approve", False)
    map_all = getattr(args, "map_all", False)

    # --- Review mode ---
    if do_review and not map_all:
        course_code = args.course
        if not course_code:
            print("Error: course code required for --review", file=sys.stderr)
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
        course_code = args.course
        if not course_code:
            print("Error: course code required for --approve", file=sys.stderr)
            return 1
        count = approve_mappings(db_path, course_code, program)
        if count > 0:
            print(f"Approved {count} mapping(s) for {course_code} in {program}.")
        else:
            print(f"No pending AI-suggested mappings to approve for {course_code} in {program}.")
        return 0

    # --- Map all courses in a program ---
    if map_all:
        try:
            all_results = map_program(db_path, program, force=force)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        except RuntimeError as exc:
            print(f"API Error: {exc}", file=sys.stderr)
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
    course_code = args.course
    if not course_code:
        print("Error: course code required (or use --all)", file=sys.stderr)
        return 1

    try:
        results = map_course(db_path, course_code, program, force=force)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(f"API Error: {exc}", file=sys.stderr)
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
    print(f"[generate] course={args.course}, program={args.program}, term={args.term}")
    print("Not yet implemented (Stage 7).")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="abet-syllabus",
        description="Generate ABET-compliant course syllabi from course specifications.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

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
    q_courses.set_defaults(func=cmd_query)

    q_course = query_sub.add_parser("course", help="Show details for a course")
    q_course.add_argument("code", help="Course code (e.g., 'MATH 101')")
    q_course.set_defaults(func=cmd_query)

    q_clos = query_sub.add_parser("clos", help="List CLOs for a course")
    q_clos.add_argument("code", help="Course code")
    q_clos.set_defaults(func=cmd_query)

    q_stats = query_sub.add_parser("stats", help="Show database statistics")
    q_stats.set_defaults(func=cmd_query)

    q_plo_matrix = query_sub.add_parser("plo-matrix", help="Show CLO-PLO mapping matrix")
    q_plo_matrix.add_argument("--program", "-p", required=True, help="Program code")
    q_plo_matrix.set_defaults(func=cmd_query)

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
        "--force", action="store_true",
        help="Re-map even if mappings already exist",
    )
    p_map.set_defaults(func=cmd_map)

    # --- generate ---
    p_gen = subparsers.add_parser("generate", help="Generate ABET syllabus document(s)")
    p_gen.add_argument("course", help="Course code (e.g., MATH 101)")
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
    p_gen.set_defaults(func=cmd_generate)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 1

    if hasattr(args, "func"):
        return args.func(args)

    parser.print_help()
    return 1


def main_cli() -> None:
    """Entry point for console_scripts (no return value)."""
    sys.exit(main())


if __name__ == "__main__":
    sys.exit(main())

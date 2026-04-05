"""CLI entry point for the ABET Syllabus Generator."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from abet_syllabus import __version__


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
    print(f"[ingest] path={args.path}, program={args.program}, recursive={args.recursive}")
    print("Not yet implemented (Stage 5).")
    return 0


def cmd_query(args: argparse.Namespace) -> int:
    """Query the course database."""
    print(f"[query] command={args.query_command}")
    print("Not yet implemented (Stage 5).")
    return 0


def cmd_map(args: argparse.Namespace) -> int:
    """Run CLO-PLO mapping for a course."""
    print(f"[map] course={args.course}, program={args.program}")
    print("Not yet implemented (Stage 6).")
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
    p_ingest.set_defaults(func=cmd_ingest)

    # --- query ---
    p_query = subparsers.add_parser("query", help="Query the course database")
    query_sub = p_query.add_subparsers(dest="query_command", help="Query subcommands")

    q_courses = query_sub.add_parser("courses", help="List all courses")
    q_courses.add_argument("--program", "-p", default=None, help="Filter by program")
    q_courses.set_defaults(func=cmd_query)

    q_course = query_sub.add_parser("course", help="Show details for a course")
    q_course.add_argument("code", help="Course code (e.g., MATH 101)")
    q_course.set_defaults(func=cmd_query)

    q_clos = query_sub.add_parser("clos", help="List CLOs for a course")
    q_clos.add_argument("code", help="Course code")
    q_clos.set_defaults(func=cmd_query)

    q_stats = query_sub.add_parser("stats", help="Show database statistics")
    q_stats.set_defaults(func=cmd_query)

    # --- map ---
    p_map = subparsers.add_parser("map", help="Run CLO-PLO mapping for a course")
    p_map.add_argument("course", help="Course code (e.g., MATH 101)")
    p_map.add_argument(
        "--program", "-p", required=True,
        help="Program code (e.g., MATH)",
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

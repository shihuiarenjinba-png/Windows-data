from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .pipeline import inspect_msix, run_pipeline


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Windows MSIX Auto Build & Identity Collector"
    )
    sub = parser.add_subparsers(dest="command")
    build = sub.add_parser("build", help="Resolve an app name and run the existing build")
    build.add_argument("app_name", help="Application name")
    build.add_argument("--owner", default="shihuiarenjinba-png")
    build.add_argument("--repo", default="", help="Exact GitHub repository URL override")
    build.add_argument("--branch", default="", help="Exact source branch override")
    build.add_argument("--workspace", type=Path, default=Path.home() / "Documents" / "MSIX-Workspace")
    build.add_argument("--resolve-only", action="store_true")
    inspect = sub.add_parser("inspect", help="Extract identity from an existing MSIX")
    inspect.add_argument("msix", type=Path)
    inspect.add_argument("--output", type=Path, default=Path.cwd() / "identity-output")
    sub.add_parser("gui", help="Open the bilingual desktop GUI")
    return parser


def main(argv: list[str] | None = None) -> int:
    if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command in {None, "gui"}:
        from .gui import main as gui_main

        gui_main()
        return 0
    if args.command == "inspect":
        report = inspect_msix(args.msix, args.output)
    else:
        report = run_pipeline(
            app_name=args.app_name,
            workspace=args.workspace,
            owner=args.owner,
            repository_url=args.repo,
            source_branch=args.branch,
            execute_build=not args.resolve_only,
            progress=lambda message: print(message, flush=True),
        )
    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    return 0 if not report.holds else 1


if __name__ == "__main__":
    raise SystemExit(main())

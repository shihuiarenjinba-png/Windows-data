from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .pipeline import inspect_msix, run_pipeline
from .self_package import build_self_msix


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
    self_msix = sub.add_parser("self-msix", help="Build or HOLD the Windows-data MSIX")
    self_msix.add_argument("--root", type=Path, default=Path.cwd())
    self_msix.add_argument(
        "--inputs", type=Path, default=Path.cwd() / "store" / "self-msix-inputs.json"
    )
    self_msix.add_argument(
        "--exe", type=Path, default=Path.cwd() / "dist" / "MSIXAutoBuildIdentity.exe"
    )
    self_msix.add_argument(
        "--output", type=Path, default=Path.cwd() / "dist" / "self-msix"
    )
    gui_check = sub.add_parser("gui-check", help="Validate bilingual GUI layout")
    gui_check.add_argument("--width", type=int, default=1024)
    gui_check.add_argument("--height", type=int, default=768)
    gui_check.add_argument(
        "--output", type=Path, default=Path.cwd() / "gui-validation.json"
    )
    sub.add_parser("gui", help="Open the bilingual desktop GUI")
    return parser


def main(argv: list[str] | None = None) -> int:
    if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command in {None, "gui"}:
        from .gui import main as gui_main

        gui_main()
        return 0
    if args.command == "gui-check":
        from .gui_validation import validate_gui

        payload = validate_gui(args.width, args.height, args.output)
        if sys.stdout is not None:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload["status"] == "PASS" else 2
    if args.command == "self-msix":
        report = build_self_msix(
            root=args.root,
            inputs_path=args.inputs,
            exe_path=args.exe,
            output_directory=args.output,
        )
        if sys.stdout is not None:
            print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
        return 0 if not report.holds else 1
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
    if sys.stdout is not None:
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    return 0 if not report.holds else 1


if __name__ == "__main__":
    raise SystemExit(main())

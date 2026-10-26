from __future__ import annotations

import csv
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .models import RunReport


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def checker_config(report: RunReport) -> dict[str, Any]:
    msix = next((item for item in report.artifacts if item.kind == "MSIX"), None)
    return {
        "expected": {
            "name": report.identity.name,
            "publisher": report.identity.publisher,
            "version": report.identity.version,
            "display_name": report.identity.display_name,
            "architecture": report.identity.architecture,
            "msix_sha256": msix.sha256 if msix else "",
            "source_commit": report.source_head,
            "github_actions_run_id": "",
        },
        "listing": {
            "description": "",
            "privacy_url": "",
            "languages": ["ja-JP", "en-US"],
            "markets": "",
        },
        "attestations": {
            "identity_confirmed": False,
            "submission_verified": False,
            "windows_installed": False,
            "workflow_tested": False,
        },
        "build": {
            "github_actions_run_id": "",
            "source_commit": report.source_head,
            "artifact_sha256": msix.sha256 if msix else "",
            "provenance_verified": False,
        },
        "collector": {
            "status": report.status,
            "store_id": report.store_id,
            "package_family_name": report.identity.package_family_name,
            "publisher_id": report.identity.publisher_id,
            "package_sid": report.identity.package_sid,
            "hold_codes": [item.code for item in report.holds],
        },
    }


def _flatten(prefix: str, value: Any, rows: list[tuple[str, str]]) -> None:
    if isinstance(value, dict):
        for key in sorted(value):
            _flatten(f"{prefix}.{key}" if prefix else str(key), value[key], rows)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _flatten(f"{prefix}[{index}]", item, rows)
    elif value is None:
        rows.append((prefix, ""))
    else:
        rows.append((prefix, str(value)))


def export_report(report: RunReport, output_directory: Path) -> tuple[Path, Path, Path]:
    output_directory.mkdir(parents=True, exist_ok=True)
    json_path = output_directory / "msix-identity-report.json"
    csv_path = output_directory / "msix-identity-report.csv"
    checker_path = output_directory / "windows-checker-submission.json"
    report.output_json = str(json_path.resolve())
    report.output_csv = str(csv_path.resolve())
    report.windows_checker_config = str(checker_path.resolve())
    payload = report.as_dict()
    _atomic_text(json_path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    rows: list[tuple[str, str]] = []
    _flatten("", payload, rows)
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(["field", "value"])
        writer.writerows(rows)
        stream.seek(0)
        _atomic_text(csv_path, stream.read())
    _atomic_text(
        checker_path,
        json.dumps(checker_config(report), ensure_ascii=False, indent=2) + "\n",
    )
    return json_path, csv_path, checker_path

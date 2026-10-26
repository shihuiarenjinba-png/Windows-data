from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .exporter import export_report
from .github_client import GitHubClient, GitHubError
from .identity import IdentityError, parse_msix, sha256_file
from .models import Artifact, RunReport
from .source_build import (
    SourceError,
    checkout_source,
    discover_build_plan,
    load_identity_inputs,
    msix_gate_holds,
    run_executable_build,
    run_msix_build,
)


Progress = Callable[[str], None]


def _slug(value: str) -> str:
    result = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.")
    return result[:80] or "application"


def _run_directory(workspace: Path, app_name: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return workspace.resolve() / "results" / f"{stamp}-{_slug(app_name)}"


def _artifact(kind: str, path: Path) -> Artifact:
    return Artifact(kind, str(path.resolve()), sha256_file(path), path.stat().st_size)


def _compare_identity(report: RunReport, expected: dict[str, object]) -> None:
    comparisons = {
        "package_identity_name": (report.identity.name, "Identity Name"),
        "package_identity_publisher": (report.identity.publisher, "Publisher"),
        "package_family_name": (report.identity.package_family_name, "Package Family Name"),
        "package_sid": (report.identity.package_sid, "Package SID"),
        "approved_store_version": (report.identity.version, "Version"),
        "architecture": (report.identity.architecture, "Architecture"),
    }
    for key, (actual, label) in comparisons.items():
        declared = str(expected.get(key) or "").strip()
        if declared and declared.casefold() != actual.casefold():
            report.add_hold(
                "IDENTITY_MISMATCH",
                f"MSIX内の{label}が確認済み入力と一致しません。",
                f"The packaged {label} does not match the verified input.",
                "identity",
            )


def run_pipeline(
    *,
    app_name: str,
    workspace: Path,
    owner: str = "shihuiarenjinba-png",
    repository_url: str = "",
    source_branch: str = "",
    execute_build: bool = True,
    client: GitHubClient | None = None,
    progress: Progress | None = None,
) -> RunReport:
    notify = progress or (lambda _message: None)
    report = RunReport(app_name=app_name.strip())
    run_dir = _run_directory(workspace, app_name)
    logs = run_dir / "logs"
    client = client or GitHubClient()
    try:
        notify("Resolving GitHub repository")
        repository = (
            client.repository_from_url(repository_url)
            if repository_url.strip()
            else client.find_repository(app_name, owner)
        )
        revision = client.resolve_revision(repository, source_branch)
    except GitHubError as exc:
        report.add_hold(
            "SOURCE_UNRESOLVED",
            "GitHubリポジトリまたは対象ブランチを一意に確定できません。",
            "The GitHub repository or source branch could not be resolved uniquely.",
            "source",
        )
        report.logs.append(str(exc))
        export_report(report, run_dir)
        return report
    report.repository = repository.full_name
    report.repository_url = repository.html_url
    report.source_branch = revision.branch
    report.source_head = revision.sha.lower()
    report.metadata["source_resolution_evidence"] = list(revision.evidence)
    # Keep this deliberately short: target builds often create deep virtualenv and
    # PyInstaller hook paths, and many Windows systems still enforce MAX_PATH.
    repository_key = hashlib.sha256(repository.full_name.encode("utf-8")).hexdigest()[:8]
    source_dir = workspace.resolve() / "_w" / repository_key / secrets.token_hex(4)
    try:
        notify(f"Checking out {repository.full_name}@{revision.sha[:12]}")
        checkout_source(
            repository.clone_url,
            revision.branch,
            revision.sha,
            source_dir,
        )
        plan = discover_build_plan(source_dir)
        report.build_scripts = {
            "executable": str(plan.executable_script or ""),
            "msix": str(plan.msix_script or ""),
            "identity": str(plan.identity_file or ""),
        }
        inputs = load_identity_inputs(plan.identity_file)
    except SourceError as exc:
        report.add_hold(
            "SOURCE_PREPARATION_FAILED",
            "ソース取得またはビルド手順の解析に失敗しました。",
            "Source checkout or build discovery failed.",
            "source",
        )
        report.logs.append(str(exc))
        export_report(report, run_dir)
        return report
    report.metadata["verified_product_inputs"] = {
        key: inputs.get(key)
        for key in (
            "owner_confirmed_store_id",
            "store_id_verification",
            "package_identity_name",
            "package_identity_name_verification",
            "package_identity_publisher",
            "package_identity_publisher_verification",
            "publisher_display_name",
            "publisher_display_name_verification",
            "partner_center_reserved_display_name",
            "display_name_verification",
            "package_family_name",
            "package_family_name_verification",
            "package_sid",
            "package_sid_verification",
            "approved_store_version",
            "package_version_approval",
            "brand_assets_approval",
        )
        if key in inputs
    }
    if (
        str(inputs.get("store_id_verification") or "")
        in {"PARTNER_CENTER_VERIFIED", "OWNER_VERIFIED"}
    ):
        report.store_id = str(inputs.get("owner_confirmed_store_id") or "").strip()
    if not execute_build:
        report.add_hold(
            "BUILD_NOT_RUN",
            "解決のみが指定されたためビルドを実行していません。",
            "Resolve-only mode was requested; no build was executed.",
            "build",
        )
        export_report(report, run_dir)
        return report
    if plan.executable_script is None:
        report.add_hold(
            "EXE_BUILDER_MISSING",
            "既存のWindows EXEビルド手順が見つかりません。",
            "An existing Windows EXE build script was not found.",
            "exe",
        )
        export_report(report, run_dir)
        return report
    try:
        notify("Running the repository's existing Windows EXE build")
        exe_path = run_executable_build(
            source_dir,
            plan,
            logs,
            expected_name=str(inputs.get("expected_executable") or "").strip(),
        )
        report.artifacts.append(_artifact("EXE", exe_path))
    except SourceError as exc:
        report.add_hold(
            "EXE_BUILD_FAILED",
            "Windows EXEビルドに失敗しました。",
            "The Windows EXE build failed.",
            "exe",
        )
        report.logs.append(str(exc))
        export_report(report, run_dir)
        return report
    if plan.msix_script is None:
        report.add_hold(
            "MSIX_BUILDER_MISSING",
            "既存のMSIXビルド手順が見つかりません。",
            "An existing MSIX build script was not found.",
            "msix",
        )
    for code, ja, en in msix_gate_holds(inputs, source_dir):
        report.add_hold(code, ja, en, "msix")
    if any(item.blocking_stage == "msix" for item in report.holds):
        notify("MSIX build held because required approvals are incomplete")
        export_report(report, run_dir)
        return report
    try:
        notify("Running the repository's existing MSIX build")
        msix_path = run_msix_build(source_dir, plan, inputs, exe_path, logs)
        report.artifacts.append(_artifact("MSIX", msix_path))
        notify("Extracting identity from the generated MSIX")
        report.identity = parse_msix(msix_path)
        _compare_identity(report, inputs)
    except (SourceError, IdentityError) as exc:
        report.add_hold(
            "MSIX_BUILD_OR_IDENTITY_FAILED",
            "MSIX生成またはパッケージ内Identity抽出に失敗しました。",
            "MSIX generation or packaged identity extraction failed.",
            "identity",
        )
        report.logs.append(str(exc))
    if not report.holds and any(item.kind == "MSIX" for item in report.artifacts):
        report.status = "READY_CANDIDATE_NOT_CERTIFIED"
    export_report(report, run_dir)
    return report


def inspect_msix(msix: Path, output_directory: Path) -> RunReport:
    report = RunReport(app_name=msix.stem)
    try:
        report.identity = parse_msix(msix)
        report.artifacts.append(_artifact("MSIX", msix))
        report.status = "IDENTITY_COLLECTED_NOT_CERTIFIED"
    except IdentityError as exc:
        report.add_hold(
            "IDENTITY_EXTRACTION_FAILED",
            "MSIXからIdentityを抽出できませんでした。",
            "Identity could not be extracted from the MSIX.",
            "identity",
        )
        report.logs.append(str(exc))
    export_report(report, output_directory)
    return report

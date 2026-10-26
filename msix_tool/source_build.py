from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class SourceError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class BuildPlan:
    executable_script: Path | None
    msix_script: Path | None
    identity_file: Path | None


def _run(
    args: list[str], cwd: Path, timeout: int = 120, log_path: Path | None = None
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            args,
            cwd=str(cwd),
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SourceError(f"Command failed: {args[0]}: {exc}") from exc
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(result.stdout, encoding="utf-8")
    if result.returncode != 0:
        tail = result.stdout[-4_000:]
        raise SourceError(f"Command exited {result.returncode}: {' '.join(args)}\n{tail}")
    return result


def checkout_source(
    clone_url: str,
    branch: str,
    expected_sha: str,
    destination: Path,
) -> str:
    if not re.fullmatch(
        r"https://github[.]com/[A-Za-z0-9-]+/[A-Za-z0-9_.-]+(?:[.]git)?",
        clone_url,
    ):
        raise SourceError("Only HTTPS GitHub clone URLs are accepted")
    if not re.fullmatch(r"[0-9a-fA-F]{40}", expected_sha):
        raise SourceError("Expected source SHA is invalid")
    destination = destination.resolve()
    if destination.exists():
        if not (destination / ".git").is_dir():
            raise SourceError(f"Existing source destination is not a Git checkout: {destination}")
        origin = _run(["git", "remote", "get-url", "origin"], destination).stdout.strip()
        normalize = lambda value: re.sub(r"[.]git/?$", "", value).casefold()
        if normalize(origin) != normalize(clone_url):
            raise SourceError("Existing checkout has a different origin")
        if _run(["git", "status", "--porcelain"], destination).stdout.strip():
            raise SourceError("Existing source checkout has uncommitted changes")
        _run(["git", "fetch", "--prune", "origin", branch], destination, timeout=300)
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Git credentials are delegated to Git Credential Manager. Tokens are never
        # put in command arguments, remotes, logs, or generated reports.
        _run(
            ["git", "clone", "--branch", branch, "--single-branch", clone_url, str(destination)],
            destination.parent,
            timeout=600,
        )
    _run(["git", "checkout", "--detach", expected_sha], destination)
    actual = _run(["git", "rev-parse", "HEAD"], destination).stdout.strip().lower()
    if actual != expected_sha.lower():
        raise SourceError(f"Source HEAD mismatch: expected {expected_sha}, got {actual}")
    return actual


def discover_build_plan(root: Path) -> BuildPlan:
    root = root.resolve()
    executable_candidates = [
        root / "build-windows-portable.ps1",
        root / "build-windows.ps1",
        root / "scripts" / "build-windows.ps1",
    ]
    msix_candidates = [
        root / "store" / "build-msix.ps1",
        root / "build-msix.ps1",
        root / "scripts" / "build-msix.ps1",
    ]
    executable = next((path for path in executable_candidates if path.is_file()), None)
    msix = next((path for path in msix_candidates if path.is_file()), None)
    if executable is None:
        matches = sorted(root.glob("**/*windows*.ps1"))
        executable = next(
            (path for path in matches if ".git" not in path.parts and "msix" not in path.name.casefold()),
            None,
        )
    if msix is None:
        matches = sorted(root.glob("**/*msix*.ps1"))
        msix = next((path for path in matches if ".git" not in path.parts), None)
    identity_candidates = sorted(root.glob("**/unsigned_msix_submission_inputs.json"))
    if not identity_candidates:
        identity_candidates = sorted(root.glob("**/*identity*.json"))
    identity_file = next(
        (path for path in identity_candidates if ".git" not in path.parts), None
    )
    return BuildPlan(executable, msix, identity_file)


def load_identity_inputs(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    if path.stat().st_size > 2 * 1024 * 1024:
        raise SourceError("Identity input JSON exceeds the safety limit")
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SourceError(f"Identity input JSON is invalid: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SourceError("Identity input JSON must contain an object")
    return data


def msix_gate_holds(data: dict[str, Any], root: Path) -> list[tuple[str, str, str]]:
    holds: list[tuple[str, str, str]] = []
    required = {
        "package_identity_name": ("Package Identity Name", "package_identity_name_verification"),
        "package_identity_publisher": ("Publisher", "package_identity_publisher_verification"),
        "publisher_display_name": ("Publisher display name", "publisher_display_name_verification"),
        "partner_center_reserved_display_name": ("Display name", "display_name_verification"),
    }
    for key, (label, verification_key) in required.items():
        value = str(data.get(key) or "").strip()
        verification = str(data.get(verification_key) or "").strip()
        if not value or verification not in {"PARTNER_CENTER_VERIFIED", "OWNER_VERIFIED"}:
            holds.append(("IDENTITY_UNVERIFIED", f"{label}が確認済みではありません。", f"{label} is not verified."))
    version = str(data.get("approved_store_version") or "").strip()
    if not re.fullmatch(r"(?:0|[1-9][0-9]{0,4})(?:[.](?:0|[1-9][0-9]{0,4})){3}", version):
        holds.append(("VERSION_UNAPPROVED", "承認済みVersionがありません。", "Approved Store version is missing."))
    elif any(int(part) > 65535 for part in version.split(".")):
        holds.append(("VERSION_INVALID", "Versionの各要素は65535以下である必要があります。", "Each version component must be at most 65535."))
    if str(data.get("package_version_approval") or "") not in {"APPROVED", "OWNER_APPROVED"}:
        holds.append(("VERSION_UNAPPROVED", "Versionの承認証跡がありません。", "Version approval evidence is missing."))
    if str(data.get("brand_assets_approval") or "") not in {"APPROVED", "OWNER_APPROVED"}:
        holds.append(("ASSETS_UNAPPROVED", "ブランド素材が承認済みではありません。", "Brand assets are not approved."))
    asset_parents: set[Path] = set()
    for relative in data.get("logo_paths", []) if isinstance(data.get("logo_paths"), list) else []:
        candidate = (root / str(relative)).resolve()
        try:
            candidate.relative_to(root.resolve())
        except ValueError:
            holds.append(("ASSET_PATH_UNSAFE", f"素材パスがソース外を指しています: {relative}", f"Asset path escapes the source root: {relative}"))
            continue
        asset_parents.add(candidate.parent)
        if not candidate.is_file():
            holds.append(("ASSET_MISSING", f"素材がありません: {relative}", f"Asset is missing: {relative}"))
    if len(asset_parents) > 1:
        holds.append(("ASSET_DIRECTORY_MISMATCH", "MSIX素材が複数フォルダーに分かれています。", "MSIX assets are split across multiple directories."))
    if not str(data.get("owner_confirmed_store_id") or "").strip() or str(
        data.get("store_id_verification") or ""
    ) not in {"PARTNER_CENTER_VERIFIED", "OWNER_VERIFIED"}:
        holds.append(("STORE_ID_UNVERIFIED", "Store IDが確認済みではありません。", "Store ID is not verified."))
    unique: dict[str, tuple[str, str, str]] = {}
    for item in holds:
        unique.setdefault(item[0], item)
    return list(unique.values())


def powershell_executable() -> str:
    for name in ("pwsh.exe", "powershell.exe"):
        found = shutil.which(name)
        if found:
            return found
    raise SourceError("PowerShell was not found")


def run_executable_build(
    root: Path,
    plan: BuildPlan,
    logs: Path,
    expected_name: str = "",
    timeout: int = 3_600,
) -> Path:
    if plan.executable_script is None:
        raise SourceError("Windows executable build script was not found")
    _run(
        [
            powershell_executable(),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(plan.executable_script),
        ],
        root,
        timeout=timeout,
        log_path=logs / "exe-build.log",
    )
    exes = sorted(
        (path for path in (root / "dist").glob("**/*.exe") if path.is_file()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not exes:
        raise SourceError("Build completed but no EXE was found under dist")
    if expected_name:
        exact = [path for path in exes if path.name.casefold() == expected_name.casefold()]
        if len(exact) != 1:
            raise SourceError(f"Expected executable was not produced uniquely: {expected_name}")
        return exact[0]
    if len(exes) != 1:
        raise SourceError("Multiple EXE artifacts were produced and no expected executable was declared")
    return exes[0]


def run_msix_build(
    root: Path,
    plan: BuildPlan,
    identity: dict[str, Any],
    exe_path: Path,
    logs: Path,
    timeout: int = 1_800,
) -> Path:
    if plan.msix_script is None:
        raise SourceError("MSIX build script was not found")
    logo_paths = [str(item) for item in identity.get("logo_paths", [])]
    if not logo_paths:
        raise SourceError("No approved logo paths were provided")
    assets_directory = (root / logo_paths[0]).resolve().parent
    args = [
        powershell_executable(),
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(plan.msix_script),
        "-IdentityName",
        str(identity["package_identity_name"]),
        "-Publisher",
        str(identity["package_identity_publisher"]),
        "-PublisherDisplayName",
        str(identity["publisher_display_name"]),
        "-DisplayName",
        str(identity["partner_center_reserved_display_name"]),
        "-ExePath",
        str(exe_path.resolve()),
        "-AssetsDirectory",
        str(assets_directory),
        "-Version",
        str(identity["approved_store_version"]),
    ]
    before = {path.resolve() for path in root.glob("**/*.msix")}
    _run(args, root, timeout=timeout, log_path=logs / "msix-build.log")
    after = [path.resolve() for path in root.glob("**/*.msix") if path.resolve() not in before]
    if not after:
        raise SourceError("MSIX build completed but no new package was found")
    return max(after, key=lambda path: path.stat().st_mtime)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()

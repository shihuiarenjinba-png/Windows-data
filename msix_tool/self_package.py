from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from xml.sax.saxutils import escape

from .exporter import export_report
from .identity import IdentityError, parse_msix, sha256_file
from .models import Artifact, RunReport
from .source_build import SourceError, load_identity_inputs, msix_gate_holds


ASSET_DIMENSIONS = {
    "StoreLogo.png": (50, 50),
    "Square44x44Logo.png": (44, 44),
    "Square150x150Logo.png": (150, 150),
}


def _artifact(kind: str, path: Path) -> Artifact:
    return Artifact(kind, str(path.resolve()), sha256_file(path), path.stat().st_size)


def _find_makeappx() -> Path:
    direct = shutil.which("MakeAppx.exe")
    if direct:
        return Path(direct).resolve()
    program_files_x86 = Path(
        os.environ.get("ProgramFiles(x86)", Path.home().anchor + "Program Files (x86)")
    )
    kits = program_files_x86 / "Windows Kits" / "10" / "bin"
    candidates = sorted(kits.glob("*/x64/MakeAppx.exe"), reverse=True) if kits.is_dir() else []
    if not candidates:
        raise SourceError("Windows SDK MakeAppx.exe was not found")
    return candidates[0].resolve()


def _png_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()[:24]
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise SourceError(f"Invalid PNG: {path.name}")
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def _source_head(root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _run_makeappx(makeappx: Path, arguments: list[str], cwd: Path) -> str:
    result = subprocess.run(
        [str(makeappx), *arguments],
        cwd=cwd,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode != 0:
        raise SourceError(f"MakeAppx failed ({result.returncode}): {result.stdout[-4000:]}")
    return result.stdout


def _write_manifest(stage: Path, values: dict[str, object]) -> None:
    def attr(value: object) -> str:
        return escape(str(value), {'"': "&quot;", "'": "&apos;"})

    manifest = f'''<?xml version="1.0" encoding="utf-8"?>
<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"
         xmlns:uap="http://schemas.microsoft.com/appx/manifest/uap/windows10"
         xmlns:uap10="http://schemas.microsoft.com/appx/manifest/uap/windows10/10"
         xmlns:rescap="http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities"
         IgnorableNamespaces="uap uap10 rescap">
  <Identity Name="{attr(values['package_identity_name'])}"
            Publisher="{attr(values['package_identity_publisher'])}"
            Version="{attr(values['approved_store_version'])}"
            ProcessorArchitecture="x64"/>
  <Properties>
    <DisplayName>{escape(str(values['partner_center_reserved_display_name']))}</DisplayName>
    <PublisherDisplayName>{escape(str(values['publisher_display_name']))}</PublisherDisplayName>
    <Logo>Assets\\StoreLogo.png</Logo>
  </Properties>
  <Resources>
    <Resource Language="ja-JP"/>
    <Resource Language="en-US"/>
  </Resources>
  <Dependencies>
    <TargetDeviceFamily Name="Windows.Desktop" MinVersion="10.0.19041.0" MaxVersionTested="10.0.26100.0"/>
  </Dependencies>
  <Applications>
    <Application Id="{attr(values.get('application_id') or 'App')}"
                 Executable="MSIXAutoBuildIdentity.exe"
                 uap10:RuntimeBehavior="packagedClassicApp"
                 uap10:TrustLevel="mediumIL">
      <uap:VisualElements DisplayName="{escape(str(values['partner_center_reserved_display_name']))}"
          Description="{escape(str(values.get('description') or 'MSIX identity collector'))}"
          BackgroundColor="transparent"
          Square150x150Logo="Assets\\Square150x150Logo.png"
          Square44x44Logo="Assets\\Square44x44Logo.png"/>
    </Application>
  </Applications>
  <Capabilities><rescap:Capability Name="runFullTrust"/></Capabilities>
</Package>
'''
    (stage / "AppxManifest.xml").write_text(manifest, encoding="utf-8", newline="\n")


def build_self_msix(
    *, root: Path, inputs_path: Path, exe_path: Path, output_directory: Path
) -> RunReport:
    root = root.resolve()
    inputs_path = inputs_path.resolve()
    exe_path = exe_path.resolve()
    output_directory = output_directory.resolve()
    report = RunReport(app_name="Windows MSIX Auto Build & Identity Collector")
    report.repository = "shihuiarenjinba-png/Windows-data"
    report.repository_url = "https://github.com/shihuiarenjinba-png/Windows-data"
    report.source_branch = "codex/msix-auto-build-identity-20261025"
    report.source_head = _source_head(root)
    try:
        values = load_identity_inputs(inputs_path)
    except (OSError, SourceError) as exc:
        report.add_hold(
            "SELF_IDENTITY_INPUT_INVALID",
            "Windows-data自身のIdentity入力を読み取れません。",
            "The Windows-data identity input could not be read.",
            "self-msix",
        )
        report.logs.append(str(exc))
        export_report(report, output_directory)
        return report
    report.metadata["self_msix_inputs"] = values
    if str(values.get("store_id_verification") or "") in {
        "PARTNER_CENTER_VERIFIED",
        "OWNER_VERIFIED",
    }:
        report.store_id = str(values.get("owner_confirmed_store_id") or "").strip()
    for code, ja, en in msix_gate_holds(values, root):
        report.add_hold(code, ja, en, "self-msix")
    if not exe_path.is_file():
        report.add_hold(
            "SELF_EXE_MISSING",
            "Windows-dataのEXEがありません。",
            "The Windows-data EXE is missing.",
            "self-msix",
        )
    else:
        report.artifacts.append(_artifact("EXE", exe_path))
    if report.holds:
        export_report(report, output_directory)
        return report

    stage = output_directory / ("_stage-" + uuid.uuid4().hex)
    unpacked = output_directory / ("_verify-" + uuid.uuid4().hex)
    version = str(values["approved_store_version"])
    package = output_directory / f"MSIXAutoBuildIdentity_QA_UNSIGNED_{version}_x64.msix"
    package_created = False
    try:
        if package.exists():
            raise SourceError("An MSIX with the approved version already exists; it was not replaced")
        (stage / "Assets").mkdir(parents=True)
        shutil.copy2(exe_path, stage / "MSIXAutoBuildIdentity.exe")
        source_assets: dict[str, Path] = {}
        for relative in values.get("logo_paths", []):
            source = (root / str(relative)).resolve()
            source_assets[source.name] = source
        for name, dimensions in ASSET_DIMENSIONS.items():
            source = source_assets.get(name)
            if source is None or not source.is_file():
                raise SourceError(f"Required approved asset is missing: {name}")
            if _png_dimensions(source) != dimensions:
                raise SourceError(f"Approved asset has incorrect dimensions: {name}")
            shutil.copy2(source, stage / "Assets" / name)
        _write_manifest(stage, values)
        metadata = {
            "schema_version": 1,
            "source_commit": report.source_head,
            "exe_sha256": sha256_file(exe_path),
            "certification": "NOT_CERTIFIED",
            "signature": "QA_UNSIGNED",
        }
        (stage / "build-metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        output_directory.mkdir(parents=True, exist_ok=True)
        makeappx = _find_makeappx()
        report.metadata["makeappx"] = str(makeappx)
        report.logs.append(_run_makeappx(makeappx, ["pack", "/d", str(stage), "/p", str(package)], root))
        package_created = True
        unpacked.mkdir(parents=True)
        report.logs.append(
            _run_makeappx(makeappx, ["unpack", "/p", str(package), "/d", str(unpacked)], root)
        )
        unpacked_exe = unpacked / "MSIXAutoBuildIdentity.exe"
        if sha256_file(unpacked_exe) != sha256_file(exe_path):
            raise SourceError("Re-expanded MSIX EXE SHA-256 does not match the input EXE")
        embedded = json.loads((unpacked / "build-metadata.json").read_text(encoding="utf-8"))
        if embedded.get("source_commit") != report.source_head:
            raise SourceError("Re-expanded build metadata source commit does not match")
        report.identity = parse_msix(package)
        expected = {
            "package_identity_name": report.identity.name,
            "package_identity_publisher": report.identity.publisher,
            "package_family_name": report.identity.package_family_name,
            "package_sid": report.identity.package_sid,
            "approved_store_version": report.identity.version,
        }
        for key, actual in expected.items():
            declared = str(values.get(key) or "").strip()
            if declared and declared.casefold() != actual.casefold():
                raise SourceError(f"Packaged identity mismatch: {key}")
        report.artifacts.append(_artifact("MSIX", package))
        report.status = "READY_CANDIDATE_NOT_CERTIFIED"
    except (OSError, SourceError, IdentityError, json.JSONDecodeError) as exc:
        if package_created and package.exists():
            package.unlink(missing_ok=True)
        report.add_hold(
            "SELF_MSIX_BUILD_FAILED",
            "Windows-data自身のMSIX生成または再展開検証に失敗しました。",
            "Windows-data MSIX generation or round-trip verification failed.",
            "self-msix",
        )
        report.logs.append(str(exc))
    finally:
        shutil.rmtree(stage, ignore_errors=True)
        shutil.rmtree(unpacked, ignore_errors=True)
    export_report(report, output_directory)
    return report

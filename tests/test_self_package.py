from __future__ import annotations

import json
import os
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from msix_tool.self_package import _find_makeappx, build_self_msix


def _write_png(path: Path, width: int, height: int) -> None:
    def chunk(name: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + name + data + struct.pack(">I", zlib.crc32(name + data))

    row = b"\x00" + (b"\x2E\x75\xB6\xFF" * width)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(row * height))
        + chunk(b"IEND", b"")
    )


class SelfPackageTests(unittest.TestCase):
    def test_unknown_official_identity_produces_reports_and_holds(self) -> None:
        temp_root = Path.cwd() / ".test-tmp"
        temp_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root) as temporary:
            root = Path(temporary)
            (root / "store").mkdir()
            (root / "dist").mkdir()
            exe = root / "dist" / "MSIXAutoBuildIdentity.exe"
            exe.write_bytes(b"MZ local QA fixture")
            inputs = root / "store" / "self-msix-inputs.json"
            inputs.write_text(
                json.dumps(
                    {
                        "package_identity_name": None,
                        "package_identity_name_verification": "UNKNOWN",
                        "package_identity_publisher": None,
                        "package_identity_publisher_verification": "UNKNOWN",
                        "publisher_display_name": None,
                        "publisher_display_name_verification": "UNKNOWN",
                        "partner_center_reserved_display_name": None,
                        "display_name_verification": "UNKNOWN",
                        "owner_confirmed_store_id": None,
                        "store_id_verification": "UNKNOWN",
                        "approved_store_version": None,
                        "package_version_approval": "UNKNOWN",
                        "brand_assets_approval": "UNKNOWN",
                        "logo_paths": [],
                    }
                ),
                encoding="utf-8",
            )
            output = root / "result"
            report = build_self_msix(
                root=root, inputs_path=inputs, exe_path=exe, output_directory=output
            )
            codes = {item.code for item in report.holds}
            self.assertEqual(report.status, "HOLD")
            self.assertIn("IDENTITY_UNVERIFIED", codes)
            self.assertIn("VERSION_UNAPPROVED", codes)
            self.assertIn("ASSETS_UNAPPROVED", codes)
            self.assertIn("STORE_ID_UNVERIFIED", codes)
            self.assertTrue((output / "msix-identity-report.json").is_file())
            self.assertTrue((output / "msix-identity-report.csv").is_file())
            self.assertTrue((output / "windows-checker-submission.json").is_file())
            self.assertFalse(any(output.glob("*.msix")))

    @unittest.skipUnless(os.name == "nt", "MakeAppx and identity APIs require Windows")
    def test_synthetic_qa_package_round_trip(self) -> None:
        try:
            _find_makeappx()
        except Exception as exc:
            self.skipTest(str(exc))
        temp_root = Path.cwd() / ".test-tmp"
        temp_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root) as temporary:
            root = Path(temporary)
            assets = root / "store-assets" / "assets"
            assets.mkdir(parents=True)
            for name, size in {
                "StoreLogo.png": 50,
                "Square44x44Logo.png": 44,
                "Square150x150Logo.png": 150,
            }.items():
                _write_png(assets / name, size, size)
            exe = root / "MSIXAutoBuildIdentity.exe"
            exe.write_bytes(b"MZ synthetic QA fixture; never distribute")
            inputs = root / "self-msix-inputs.json"
            inputs.write_text(
                json.dumps(
                    {
                        "package_identity_name": "Test.WindowsData.QA",
                        "package_identity_name_verification": "OWNER_VERIFIED",
                        "package_identity_publisher": "CN=00000000-0000-0000-0000-000000000000",
                        "package_identity_publisher_verification": "OWNER_VERIFIED",
                        "publisher_display_name": "Synthetic QA Only",
                        "publisher_display_name_verification": "OWNER_VERIFIED",
                        "partner_center_reserved_display_name": "Synthetic Windows-data QA",
                        "display_name_verification": "OWNER_VERIFIED",
                        "owner_confirmed_store_id": "SYNTHETIC-NOT-A-STORE-ID",
                        "store_id_verification": "OWNER_VERIFIED",
                        "approved_store_version": "1.2.3.4",
                        "package_version_approval": "OWNER_APPROVED",
                        "brand_assets_approval": "OWNER_APPROVED",
                        "logo_paths": [
                            "store-assets/assets/StoreLogo.png",
                            "store-assets/assets/Square44x44Logo.png",
                            "store-assets/assets/Square150x150Logo.png",
                        ],
                    }
                ),
                encoding="utf-8",
            )
            output = root / "result"
            report = build_self_msix(
                root=root, inputs_path=inputs, exe_path=exe, output_directory=output
            )
            self.assertEqual(report.status, "READY_CANDIDATE_NOT_CERTIFIED", report.logs)
            self.assertFalse(report.holds)
            self.assertEqual(report.identity.name, "Test.WindowsData.QA")
            self.assertEqual(report.identity.version, "1.2.3.4")
            self.assertTrue(report.identity.package_family_name)
            self.assertTrue(report.identity.package_sid.startswith("S-1-15-2-"))
            self.assertEqual(len([item for item in report.artifacts if item.kind == "MSIX"]), 1)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from msix_tool.identity import IdentityError, parse_msix


MANIFEST = """<?xml version="1.0" encoding="utf-8"?>
<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10">
  <Identity Name="OkinawaDesktopTools.AIUploadGuard"
            Publisher="CN=46263F21-A700-41DB-8C9B-114C22FB82FC"
            Version="1.2.3.0" ProcessorArchitecture="x64"/>
  <Properties>
    <DisplayName>AI Upload Guard</DisplayName>
    <PublisherDisplayName>Okinawa Desktop Tools</PublisherDisplayName>
  </Properties>
  <Applications><Application Id="App" Executable="AIUploadGuard.exe"/></Applications>
</Package>
"""


class IdentityTests(unittest.TestCase):
    def _package(self, root: Path, duplicate: bool = False) -> Path:
        package = root / "sample.msix"
        with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("AppxManifest.xml", MANIFEST)
            archive.writestr("AIUploadGuard.exe", b"MZ test")
            if duplicate:
                archive.writestr("APPXMANIFEST.XML", MANIFEST)
        return package

    @unittest.skipUnless(__import__("os").name == "nt", "Windows official APIs required")
    def test_extracts_and_derives_verified_identity_with_windows_apis(self) -> None:
        temp_root = Path.cwd() / ".test-tmp"
        temp_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root) as temporary:
            identity = parse_msix(self._package(Path(temporary)))
        self.assertEqual(identity.name, "OkinawaDesktopTools.AIUploadGuard")
        self.assertEqual(identity.publisher_id, "j8yefg9jgfh58")
        self.assertEqual(
            identity.package_family_name,
            "OkinawaDesktopTools.AIUploadGuard_j8yefg9jgfh58",
        )
        self.assertEqual(
            identity.package_sid,
            "S-1-15-2-1367625074-1170962725-99302788-2166964424-3588270332-3739499782-15167583",
        )
        self.assertTrue(identity.package_full_name.startswith("OkinawaDesktopTools.AIUploadGuard_1.2.3.0_x64__"))

    def test_rejects_case_colliding_archive_entries(self) -> None:
        temp_root = Path.cwd() / ".test-tmp"
        temp_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root) as temporary:
            package = self._package(Path(temporary), duplicate=True)
            with self.assertRaises(IdentityError):
                parse_msix(package)


if __name__ == "__main__":
    unittest.main()

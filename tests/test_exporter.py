from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from msix_tool.exporter import export_report
from msix_tool.models import Artifact, PackageIdentity, RunReport


class ExporterTests(unittest.TestCase):
    def test_writes_json_csv_and_checker_handoff(self) -> None:
        report = RunReport(app_name="Example", status="IDENTITY_COLLECTED_NOT_CERTIFIED")
        report.source_head = "a" * 40
        report.identity = PackageIdentity(
            name="Example.App",
            publisher="CN=Example",
            version="1.0.0.0",
            architecture="x64",
            package_family_name="Example.App_123456789abcd",
            package_sid="S-1-15-2-1",
        )
        report.artifacts.append(Artifact("MSIX", "C:/build/example.msix", "B" * 64, 123))
        temp_root = Path.cwd() / ".test-tmp"
        temp_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root) as temporary:
            output = Path(temporary)
            json_path, csv_path, checker_path = export_report(report, output)
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            checker = json.loads(checker_path.read_text(encoding="utf-8"))
            with csv_path.open(encoding="utf-8", newline="") as stream:
                rows = list(csv.reader(stream))
        self.assertEqual(payload["identity"]["name"], "Example.App")
        self.assertEqual(checker["expected"]["msix_sha256"], "B" * 64)
        self.assertFalse(checker["attestations"]["windows_installed"])
        self.assertIn(["identity.package_family_name", "Example.App_123456789abcd"], rows)


if __name__ == "__main__":
    unittest.main()

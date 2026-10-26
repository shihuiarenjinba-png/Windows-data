from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from msix_tool.source_build import discover_build_plan, load_identity_inputs, msix_gate_holds


class SourceBuildTests(unittest.TestCase):
    def test_discovers_existing_contract_and_holds_unknown_approvals(self) -> None:
        temp_root = Path.cwd() / ".test-tmp"
        temp_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root) as temporary:
            root = Path(temporary)
            (root / "store").mkdir()
            (root / "build-windows-portable.ps1").write_text("", encoding="utf-8")
            (root / "store" / "build-msix.ps1").write_text("", encoding="utf-8")
            identity = {
                "package_identity_name": "Example.App",
                "package_identity_name_verification": "PARTNER_CENTER_VERIFIED",
                "package_identity_publisher": "CN=00000000-0000-0000-0000-000000000000",
                "package_identity_publisher_verification": "PARTNER_CENTER_VERIFIED",
                "publisher_display_name": "Example",
                "publisher_display_name_verification": "PARTNER_CENTER_VERIFIED",
                "partner_center_reserved_display_name": "Example App",
                "display_name_verification": "PARTNER_CENTER_VERIFIED",
                "owner_confirmed_store_id": "9TEST",
                "store_id_verification": "PARTNER_CENTER_VERIFIED",
                "approved_store_version": None,
                "package_version_approval": "UNKNOWN",
                "brand_assets_approval": "UNKNOWN",
                "logo_paths": [],
            }
            path = root / "store" / "unsigned_msix_submission_inputs.json"
            path.write_text(json.dumps(identity), encoding="utf-8")
            plan = discover_build_plan(root)
            self.assertEqual(plan.executable_script, root / "build-windows-portable.ps1")
            self.assertEqual(plan.msix_script, root / "store" / "build-msix.ps1")
            loaded = load_identity_inputs(plan.identity_file)
            codes = {item[0] for item in msix_gate_holds(loaded, root)}
            self.assertIn("VERSION_UNAPPROVED", codes)
            self.assertIn("ASSETS_UNAPPROVED", codes)
            self.assertNotIn("IDENTITY_UNVERIFIED", codes)

    def test_rejects_asset_paths_outside_source_root(self) -> None:
        temp_root = Path.cwd() / ".test-tmp"
        temp_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root) as temporary:
            root = Path(temporary)
            data = {
                "logo_paths": ["../outside.png"],
                "approved_store_version": "1.0.0.0",
                "package_version_approval": "APPROVED",
                "brand_assets_approval": "APPROVED",
            }
            codes = {item[0] for item in msix_gate_holds(data, root)}
            self.assertIn("ASSET_PATH_UNSAFE", codes)


if __name__ == "__main__":
    unittest.main()

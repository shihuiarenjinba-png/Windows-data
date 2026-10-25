from __future__ import annotations

import unittest

from msix_tool.gui import TEXT


class GuiContractTests(unittest.TestCase):
    def test_ja_and_en_have_the_same_translation_keys(self) -> None:
        self.assertEqual(set(TEXT["ja"]), set(TEXT["en"]))
        self.assertIn("build", TEXT["ja"])
        self.assertIn("build", TEXT["en"])


if __name__ == "__main__":
    unittest.main()

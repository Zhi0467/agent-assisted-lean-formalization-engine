from __future__ import annotations

import unittest
from pathlib import Path

import lean_formalization_engine


class TestPytestSourceImport(unittest.TestCase):
    def test_pytest_uses_repo_src_tree(self):
        package_path = Path(lean_formalization_engine.__file__).resolve()
        src_root = Path(__file__).resolve().parents[1] / "src"

        self.assertTrue(
            package_path.is_relative_to(src_root),
            f"expected pytest import to resolve under {src_root}, got {package_path}",
        )


if __name__ == "__main__":
    unittest.main()

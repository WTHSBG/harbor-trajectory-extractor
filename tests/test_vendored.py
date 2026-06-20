from __future__ import annotations

import importlib
import unittest

from harbor_trajectory_extractor.vendored import (
    activate_vendor_namespace,
    vendor_root,
)


class VendoredBackendTest(unittest.TestCase):
    def test_harbor_import_resolves_to_project_vendor(self) -> None:
        activate_vendor_namespace()
        harbor = importlib.import_module("harbor")
        self.assertTrue(str(harbor.__file__).startswith(str(vendor_root())))


if __name__ == "__main__":
    unittest.main()


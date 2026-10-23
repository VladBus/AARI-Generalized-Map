"""Unit tests for expected shapefile sets and size checks."""

import tempfile
import unittest
from pathlib import Path
from main import COMPONENTS, CopyJob, inspect_job


class FileValidationTests(unittest.TestCase):
    """Exercise simple input validation without network paths."""

    def test_small_file_outside_reference_range_is_flagged(self):
        """Flag a source file that is far smaller than its reference size."""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "aari_arc_20261020_pl_a.shp"
            p.write_bytes(b"x")
            job = CopyJob("SIGRID", (p,), Path(tmp) / "target", "sigrid.arc")
            self.assertTrue(any("подозрительный размер" in e for e in inspect_job(job)))

    def test_missing_shapefile_component_is_flagged(self):
        """Reject a shapefile layer whose sidecar set is incomplete."""
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            paths = []
            for ext in (".shp", ".shx", ".dbf"):
                p = folder / f"x{ext}"
                p.write_bytes(b"content")
                paths.append(p)
            self.assertTrue(
                any(
                    "комплект SHP" in e
                    for e in inspect_job(
                        CopyJob("SHP", tuple(paths), folder / "out", "none")
                    )
                )
            )

    def test_component_list(self):
        """Keep the four standard shapefile extensions in the component list."""
        self.assertEqual(set(COMPONENTS), {".shp", ".shx", ".dbf", ".prj"})


if __name__ == "__main__":
    unittest.main()

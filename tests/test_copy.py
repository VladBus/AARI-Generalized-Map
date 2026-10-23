import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import main


class CopyTests(unittest.TestCase):
    def test_existing_file_is_replaced_without_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "source"
            target_dir = root / "target"
            source_dir.mkdir()
            target_dir.mkdir()
            source = source_dir / "map.dat"
            target = target_dir / "map.dat"
            source.write_bytes(b"new data")
            target.write_bytes(b"old data")
            with patch.object(main, "SIZE_BASELINES", {}):
                result = main.copy_job(
                    main.CopyJob("map", (source,), target_dir, "none"), dry_run=False
                )
            self.assertEqual(result.status, "OK")
            self.assertEqual(target.read_bytes(), b"new data")
            self.assertEqual(list(root.glob("**/*backup*")), [])


if __name__ == "__main__":
    unittest.main()

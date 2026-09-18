from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pff_content.config import ENV_KEY, load_env_file


class ConfigTests(unittest.TestCase):
    def test_load_env_file_does_not_override_process_env(self) -> None:
        import os
        import tempfile

        previous = os.environ.get(ENV_KEY)
        try:
            os.environ[ENV_KEY] = "process-secret"
            with tempfile.TemporaryDirectory() as temp_dir:
                env_file = Path(temp_dir) / ".env"
                env_file.write_text(f"{ENV_KEY}=file-secret\n", encoding="utf-8")
                load_env_file(env_file)
            self.assertEqual(os.environ[ENV_KEY], "process-secret")
        finally:
            if previous is None:
                os.environ.pop(ENV_KEY, None)
            else:
                os.environ[ENV_KEY] = previous

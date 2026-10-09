"""Tests import the real API with provider/database construction replaced."""
import importlib
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def isolated_temp_directory(monkeypatch, tmp_path):
    # Keep subprocess/processing fixtures independent of Windows sandbox TEMP.
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))


@pytest.fixture(scope="session")
def api_module():
    fake_db = MagicMock()
    fake_db.get_pending_audio_jobs.return_value = []
    with patch("dotenv.load_dotenv", return_value=False), \
         patch("src.database.firebase_client.FirebaseClient", return_value=fake_db), \
         patch("openai.OpenAI", return_value=MagicMock()):
        return importlib.import_module("src.api")

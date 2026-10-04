"""Test setup: fake secrets, a throwaway database and log file, and stand-ins for
the heavy ML modules (Whisper, BLIP, sentence-transformers) so tests run fast
and need no GPU, models or API keys."""
import os
import sys
import tempfile
import types
from pathlib import Path

_tmp = Path(tempfile.mkdtemp())
os.environ.update(
    DASHBOARD_PASSWORD="test-password",
    BRIDGE_API_TOKEN="bridge-secret",
    ALLOWED_CONTACTS="",
    APP_LOG_FILE=str(_tmp / "app.log"),
)
os.environ.pop("DASHBOARD_TOKEN", None)


def _stub(name: str, **attrs) -> None:
    module = types.ModuleType(name)
    module.__dict__.update(attrs)
    sys.modules[name] = module


_stub("app.stt", transcribe_bytes=lambda audio, language="ar", model_size=None, vad=False: f"heard {len(audio)} bytes",
      transcribe_base64_audio=lambda b: "heard")
_stub("app.vision", caption_base64_image=lambda b: "a photo")
_stub("app.style_retrieval", retrieve_examples=lambda text, k=5: [])
_stub("app.tts", synthesize_to_base64=None)

import pytest  # noqa: E402

from app import db  # noqa: E402

db.DB_PATH = _tmp / "import-time.db"  # app.main calls db.init() when imported


@pytest.fixture()
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init()
    return db


@pytest.fixture()
def contacts_file(tmp_path, monkeypatch):
    from app import contacts

    path = tmp_path / "contacts.json"
    path.write_text('{"Mom": "201000000000", "Lulu": "112257593794569@lid"}', encoding="utf-8")
    monkeypatch.setattr(contacts, "CONTACTS_FILE", path)
    return path


@pytest.fixture()
def client(fresh_db, contacts_file):
    from fastapi.testclient import TestClient

    from app import dashboard
    from app.main import app

    dashboard._failed_logins.clear()
    return TestClient(app)


@pytest.fixture()
def signed_in(client):
    assert client.post("/api/login", json={"password": "test-password"}).status_code == 200
    return client

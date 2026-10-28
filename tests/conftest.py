import pytest


@pytest.fixture(autouse=True)
def _no_upload_gap(monkeypatch):
    """Tests don't need the real pause between channel posts."""
    from bot import main
    monkeypatch.setattr(main, "UPLOAD_GAP_SECONDS", 0)

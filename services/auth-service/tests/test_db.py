import importlib
import sys


def test_sqlite_database_directory_is_created(tmp_path, monkeypatch):
    db_path = tmp_path / "nested" / "auth-service.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    sys.modules.pop("app.db", None)

    import app.db as db_module

    assert db_path.exists()
    assert db_path.parent.exists()
    assert db_module.engine is not None

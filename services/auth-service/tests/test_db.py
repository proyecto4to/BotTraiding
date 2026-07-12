import sys


def test_sqlite_database_directory_is_created(tmp_path, monkeypatch):
    db_path = tmp_path / "nested" / "auth-service.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    # Reimportar app.db con la URL nueva crea un engine distinto; hay que
    # restaurar el modulo original o el resto de la suite queda apuntando
    # a esta DB temporal vacia.
    original = sys.modules.pop("app.db", None)
    try:
        import app.db as db_module

        assert db_path.exists()
        assert db_path.parent.exists()
        assert db_module.engine is not None
    finally:
        sys.modules.pop("app.db", None)
        if original is not None:
            sys.modules["app.db"] = original

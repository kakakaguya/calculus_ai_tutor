import importlib

import web_app


def test_default_database_is_the_project_database(monkeypatch):
    monkeypatch.delenv("CALCULUS_TUTOR_DB", raising=False)
    module = importlib.reload(web_app)
    assert module.DB_PATH == module.BASE_DIR / "database" / "calculus_tutor.db"
    assert module.DB_PATH.exists()

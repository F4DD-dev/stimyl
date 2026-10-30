from alembic.config import Config

from alembic import command


def test_accounts_migration_downgrades(tmp_path, monkeypatch):
    url = f"sqlite+aiosqlite:///{(tmp_path / 'migrate.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    command.downgrade(config, "-1")
    command.upgrade(config, "head")

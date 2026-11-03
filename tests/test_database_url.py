import ssl

from app.db.session import prepare_database_url


def test_sqlite_url_is_unchanged() -> None:
    url, args = prepare_database_url("sqlite+aiosqlite:///tmp/stimul.db")
    assert url == "sqlite+aiosqlite:///tmp/stimul.db"
    assert args == {}


def test_postgres_ssl_require_does_not_stay_in_the_url() -> None:
    url, args = prepare_database_url(
        "postgresql+asyncpg://user:secret@db.example:5432/stimul?ssl=require"
    )
    assert "ssl=" not in url
    assert "secret" in url
    assert args["timeout"] == 10
    context = args["ssl"]
    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode == ssl.CERT_NONE
    assert context.check_hostname is False


def test_remote_postgres_uses_asyncpg_and_verifies_tls() -> None:
    url, args = prepare_database_url("postgresql://user:secret@db.example:5432/stimul")
    assert url.startswith("postgresql+asyncpg://")
    assert "secret" in url
    assert isinstance(args["ssl"], ssl.SSLContext)
    assert args["ssl"].verify_mode == ssl.CERT_REQUIRED
    assert args["ssl"].check_hostname is True


def test_local_postgres_stays_without_ssl() -> None:
    url, args = prepare_database_url("postgresql+asyncpg://stimul:stimul@db:5432/stimul")
    assert args["ssl"] is False
    assert url.startswith("postgresql+asyncpg://")

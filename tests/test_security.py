from app.security.init_data import validate_init_data
from tests.support import sign_init_data


def test_init_data_roundtrip_and_rejection():
    token = "test-token"
    raw = sign_init_data(900001, token)
    assert validate_init_data(raw, token) == "900001"
    assert validate_init_data(raw + "x", token) is None
    assert validate_init_data(raw, "other-token") is None


def test_init_data_rejects_stale_auth_date():
    token = "test-token"
    raw = sign_init_data(900001, token)
    assert validate_init_data(raw, token, max_age_seconds=-1) is None


async def test_unknown_session_cookie_is_rejected(api):
    api.client.cookies.set("stimul_session", "not-a-real-token")
    response = await api.client.get("/api/session")
    assert response.status_code == 401

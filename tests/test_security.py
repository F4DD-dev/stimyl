import time

from app.security.cookies import read_cookie, write_cookie
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


def test_cookie_hides_a_tampered_role():
    value = write_cookie("session-secret", "student", "900002", now=int(time.time()))
    assert read_cookie("session-secret", value) == ("student", "900002")
    role, rest = value.split(".", 1)[0], value.split(".", 1)[1]
    forged = "teacher" + role[len("student") :] + "." + rest
    assert read_cookie("session-secret", forged) is None

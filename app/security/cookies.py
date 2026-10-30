COOKIE_NAME = "stimul_session"
COOKIE_MAX_AGE = 7 * 24 * 60 * 60


def cookie_params(secure: bool) -> dict:
    return {
        "httponly": True,
        "samesite": "lax",
        "secure": secure,
        "max_age": COOKIE_MAX_AGE,
        "path": "/",
    }

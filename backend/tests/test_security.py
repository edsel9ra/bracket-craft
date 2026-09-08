from uuid import uuid4

import pytest
from fastapi import HTTPException, Response

from app.core.security import (
    create_access_token,
    decode_access_token_claims,
    set_auth_cookie,
)


def test_access_tokens_include_session_binding_claims():
    user_id = uuid4()
    session_id = uuid4()

    claims = decode_access_token_claims(create_access_token(user_id, session_id))

    assert claims["sub"] == str(user_id)
    assert claims["jti"] == str(session_id)
    assert claims["typ"] == "access"


def test_auth_cookie_is_http_only():
    response = Response()
    set_auth_cookie(response, "signed-token")

    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie


def test_invalid_access_token_is_rejected():
    with pytest.raises(HTTPException) as failure:
        decode_access_token_claims("not-a-token")

    assert failure.value.status_code == 401

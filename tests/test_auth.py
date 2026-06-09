import pytest
from api.auth import hash_password, verify_password, create_token, decode_token


def test_password_hash_roundtrip():
    h = hash_password("s3cret")
    assert h != "s3cret"
    assert verify_password("s3cret", h)
    assert not verify_password("wrong", h)


def test_token_roundtrip_carries_role():
    tok = create_token(username="alice", role="admin")
    claims = decode_token(tok)
    assert claims["sub"] == "alice"
    assert claims["role"] == "admin"


def test_decode_rejects_tampered_token():
    tok = create_token(username="bob", role="analyst")
    with pytest.raises(Exception):
        decode_token(tok + "tamper")

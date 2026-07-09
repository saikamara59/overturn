import pytest
from cryptography.fernet import Fernet

from server.crypto import KeyVault, hash_password, last4, verify_password


def test_password_hash_roundtrip():
    h = hash_password("s3cret-pw")
    assert h != "s3cret-pw"
    assert verify_password("s3cret-pw", h)
    assert not verify_password("wrong", h)


def test_verify_password_malformed_hash_is_false():
    assert not verify_password("x", "not-a-bcrypt-hash")


def test_keyvault_roundtrip_and_bad_token():
    vault = KeyVault(Fernet.generate_key().decode())
    token = vault.encrypt("sk-ant-abc123xyz")
    assert token != "sk-ant-abc123xyz"
    assert vault.decrypt(token) == "sk-ant-abc123xyz"
    with pytest.raises(ValueError):
        vault.decrypt("garbage")


def test_last4():
    assert last4("sk-ant-abc123wxyz") == "wxyz"

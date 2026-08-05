#!/usr/bin/env python3
"""Tests for the encrypted per-tenant credential store (PR 2).

The store replaces PR 1's per-tenant ``.env`` files. Two properties matter and are
asserted directly rather than inferred:

* secrets are unreadable in the file on disk (encryption is real, not a wrapper)
* a wrong key fails closed rather than returning garbage
"""

import os
import sqlite3
import stat

import pytest

from common.credstore import CredentialNotFound, CredentialStore, CredentialStoreError, generate_key


@pytest.fixture()
def key() -> bytes:
    return generate_key()


@pytest.fixture()
def store(tmp_path, key) -> CredentialStore:
    return CredentialStore(tmp_path / "cred.db", key=key)


class TestRoundTrip:
    def test_put_then_get_returns_all_attributes(self, store):
        store.put(
            "scott",
            account_number="123456789",
            robinhood_bearer="rh-token-abc",
            anthropic_api_key="sk-ant-xyz",  # pragma: allowlist secret
        )
        c = store.get("scott")
        assert c.user_id == "scott"
        assert c.account_number == "123456789"
        assert c.robinhood_bearer == "rh-token-abc"
        assert c.anthropic_api_key == "sk-ant-xyz"  # pragma: allowlist secret

    def test_put_is_upsert(self, store):
        store.put("scott", account_number="1", robinhood_bearer="a")
        store.put("scott", account_number="1", robinhood_bearer="b")
        assert store.get("scott").robinhood_bearer == "b"

    def test_missing_tenant_raises(self, store):
        with pytest.raises(CredentialNotFound):
            store.get("nobody")

    def test_invalid_user_id_rejected(self, store):
        with pytest.raises(Exception):
            store.put("../escape", account_number="1", robinhood_bearer="a")

    def test_list_user_ids(self, store):
        store.put("alpha", account_number="1", robinhood_bearer="a")
        store.put("bravo", account_number="2", robinhood_bearer="b")
        assert store.list_user_ids() == ["alpha", "bravo"]


class TestEncryptionAtRest:
    def test_secrets_do_not_appear_in_plaintext_on_disk(self, tmp_path, key):
        path = tmp_path / "cred.db"
        s = CredentialStore(path, key=key)
        s.put(
            "scott",
            account_number="987654321",
            robinhood_bearer="SUPER_SECRET_BEARER",
            anthropic_api_key="sk-ant-SUPER_SECRET_KEY",  # pragma: allowlist secret
        )
        raw = path.read_bytes()
        assert b"SUPER_SECRET_BEARER" not in raw
        assert b"sk-ant-SUPER_SECRET_KEY" not in raw
        assert b"987654321" not in raw
        # user_id is an index key, not a secret — it may legitimately appear.
        assert b"scott" in raw

    def test_wrong_key_fails_closed(self, tmp_path, key):
        path = tmp_path / "cred.db"
        CredentialStore(path, key=key).put("scott", account_number="1", robinhood_bearer="a")
        other = CredentialStore(path, key=generate_key())
        with pytest.raises(CredentialStoreError):
            other.get("scott")

    def test_db_file_is_owner_only(self, tmp_path, key):
        if os.name == "nt":  # pragma: no cover - POSIX-only assertion
            pytest.skip("POSIX permissions only")
        path = tmp_path / "cred.db"
        CredentialStore(path, key=key).put("scott", account_number="1", robinhood_bearer="a")
        mode = stat.S_IMODE(path.stat().st_mode)
        assert mode & 0o077 == 0, "credential db must not be group/world readable"

    def test_tampered_ciphertext_is_detected(self, tmp_path, key):
        path = tmp_path / "cred.db"
        s = CredentialStore(path, key=key)
        s.put("scott", account_number="1", robinhood_bearer="a")
        con = sqlite3.connect(path)
        con.execute("UPDATE tenant_credentials SET robinhood_bearer = ? WHERE user_id = ?", (b"tampered", "scott"))
        con.commit()
        con.close()
        with pytest.raises(CredentialStoreError):
            s.get("scott")


class TestPasswords:
    def test_set_then_verify(self, store):
        store.put("scott", account_number="1", robinhood_bearer="a")
        store.set_password("scott", "correct horse battery staple")
        assert store.verify_password("scott", "correct horse battery staple") is True

    def test_wrong_password_rejected(self, store):
        store.put("scott", account_number="1", robinhood_bearer="a")
        store.set_password("scott", "right")
        assert store.verify_password("scott", "wrong") is False

    def test_verify_unknown_user_is_false_not_raise(self, store):
        """Must not leak account existence through an exception."""
        assert store.verify_password("ghost", "anything") is False

    def test_password_not_stored_in_plaintext(self, tmp_path, key):
        path = tmp_path / "cred.db"
        s = CredentialStore(path, key=key)
        s.put("scott", account_number="1", robinhood_bearer="a")
        s.set_password("scott", "PLAINTEXT_PASSWORD_MARKER")
        assert b"PLAINTEXT_PASSWORD_MARKER" not in path.read_bytes()

    def test_same_password_yields_different_hashes(self, store):
        """Distinct salts — otherwise equal passwords are visibly equal."""
        store.put("alpha", account_number="1", robinhood_bearer="x")
        store.put("bravo", account_number="2", robinhood_bearer="y")
        store.set_password("alpha", "same")
        store.set_password("bravo", "same")
        assert store._raw_password_record("alpha") != store._raw_password_record("bravo")


class TestKeyHandling:
    def test_key_from_env(self, tmp_path, monkeypatch, key):
        monkeypatch.setenv("BIOTECH_CREDSTORE_KEY", key.decode())
        s = CredentialStore(tmp_path / "c.db")
        s.put("scott", account_number="1", robinhood_bearer="a")
        assert s.get("scott").robinhood_bearer == "a"

    def test_missing_key_raises_rather_than_writing_plaintext(self, tmp_path, monkeypatch):
        monkeypatch.delenv("BIOTECH_CREDSTORE_KEY", raising=False)
        with pytest.raises(CredentialStoreError):
            CredentialStore(tmp_path / "c.db")

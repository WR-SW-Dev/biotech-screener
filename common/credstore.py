"""Encrypted per-tenant credential store.

See ``docs/design/MULTI_TENANCY_PR_PLAN.md`` §3. This replaces the per-tenant ``.env``
files from PR 1 for every tenant except ``_legacy``, which keeps the historical
single-user layout so ~1,900 unmigrated call sites continue to work.

Why a store rather than files:

* The execute path needs to read one tenant's Robinhood bearer token at request time.
  Reading it from a file means the file must be present, correctly owned, and correctly
  permissioned on every host that serves a request. Encrypting the value instead moves
  the secret's protection from filesystem ACLs to a key the process holds.
* Per-tenant Anthropic keys live here too, so there is exactly one place a tenant's
  secrets exist rather than two with different failure modes.

**Scope of protection.** Values are encrypted at rest, so a leaked or backed-up database
file is not a leaked credential. The key is held in the serving process's environment, so
this does *not* protect against an attacker who already executes code as that user — the
same caveat that applies to PR 1's file permissions. It protects backups, snapshots, and
anything that copies the db off-host.

Secrets are returned as values and are **never** written into ``os.environ``: the
environment is process-global and inherited by subprocesses, which is precisely the leak
the per-request subprocess in PR 3 exists to avoid.

Python 3.10 compatible (CI matrix is 3.10 + 3.12).
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from common.tenancy import validate_user_id

ENV_CREDSTORE_KEY = "BIOTECH_CREDSTORE_KEY"

#: scrypt parameters. n=2**14 keeps login well under a second on the WSL2 host while
#: staying far above a bare hash. Stored alongside each record so they can be raised
#: later without invalidating existing passwords.
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tenant_credentials (
    user_id           TEXT PRIMARY KEY,
    account_number    BLOB NOT NULL,
    robinhood_bearer  BLOB NOT NULL,
    anthropic_api_key BLOB,
    pw_salt           BLOB,
    pw_hash           BLOB,
    pw_n              INTEGER,
    pw_r              INTEGER,
    pw_p              INTEGER
);
"""


class CredentialStoreError(Exception):
    """Store is unusable, or a stored value failed to decrypt/authenticate."""


class CredentialNotFound(CredentialStoreError):
    """No record for this tenant."""


@dataclass(frozen=True)
class TenantCredentials:
    """One tenant's secrets. Frozen so a resolved credential cannot be edited in flight."""

    user_id: str
    account_number: str
    robinhood_bearer: str
    anthropic_api_key: Optional[str] = None


def generate_key() -> bytes:
    """Return a fresh urlsafe-base64 Fernet key. Operator stores this outside the repo."""
    return Fernet.generate_key()


class CredentialStore:
    """SQLite-backed, encrypted-at-rest credential store.

    ``key`` defaults to ``$BIOTECH_CREDSTORE_KEY``. A missing key raises rather than
    falling back to plaintext — silently degrading would be the worst possible default
    for a file whose whole purpose is to be safe at rest.
    """

    def __init__(self, path: Path | str, *, key: bytes | str | None = None) -> None:
        self.path = Path(path)
        raw = key if key is not None else os.environ.get(ENV_CREDSTORE_KEY, "")
        if not raw:
            raise CredentialStoreError(
                "no encryption key: pass key= or set " + ENV_CREDSTORE_KEY + " "
                "(generate one with common.credstore.generate_key)"
            )
        if isinstance(raw, str):
            raw = raw.encode()
        try:
            self._fernet = Fernet(raw)
        except (ValueError, TypeError) as exc:
            raise CredentialStoreError("invalid encryption key: " + str(exc)) from exc
        self._init_db()

    # -- internals ----------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def _init_db(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        existed = self.path.exists()
        con = self._connect()
        try:
            con.executescript(_SCHEMA)
            con.commit()
        finally:
            con.close()
        if not existed:
            # Owner-only. Defence in depth: the contents are encrypted, but there is no
            # reason for the file to be readable at all.
            try:
                self.path.chmod(0o600)
            except OSError:  # pragma: no cover - non-POSIX
                pass

    def _enc(self, value: str) -> bytes:
        return self._fernet.encrypt(value.encode("utf-8"))

    def _dec(self, blob: bytes, *, field: str, user_id: str) -> str:
        try:
            return self._fernet.decrypt(blob).decode("utf-8")
        except (InvalidToken, TypeError) as exc:
            raise CredentialStoreError(
                "could not decrypt "
                + field
                + " for tenant "
                + repr(user_id)
                + " — wrong key, or the record was tampered with"
            ) from exc

    # -- credentials --------------------------------------------------------------

    def put(
        self,
        user_id: str,
        *,
        account_number: str,
        robinhood_bearer: str,
        anthropic_api_key: str | None = None,
    ) -> None:
        """Insert or replace one tenant's credentials. Preserves any existing password."""
        validate_user_id(user_id)
        con = self._connect()
        try:
            con.execute(
                """
                INSERT INTO tenant_credentials
                    (user_id, account_number, robinhood_bearer, anthropic_api_key)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    account_number    = excluded.account_number,
                    robinhood_bearer  = excluded.robinhood_bearer,
                    anthropic_api_key = excluded.anthropic_api_key
                """,
                (
                    user_id,
                    self._enc(account_number),
                    self._enc(robinhood_bearer),
                    self._enc(anthropic_api_key) if anthropic_api_key else None,
                ),
            )
            con.commit()
        finally:
            con.close()

    def get(self, user_id: str) -> TenantCredentials:
        validate_user_id(user_id)
        con = self._connect()
        try:
            row = con.execute(
                "SELECT account_number, robinhood_bearer, anthropic_api_key "
                "FROM tenant_credentials WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        finally:
            con.close()
        if row is None:
            raise CredentialNotFound("no credentials for tenant " + repr(user_id))
        acct, bearer, anth = row
        return TenantCredentials(
            user_id=user_id,
            account_number=self._dec(acct, field="account_number", user_id=user_id),
            robinhood_bearer=self._dec(bearer, field="robinhood_bearer", user_id=user_id),
            anthropic_api_key=(self._dec(anth, field="anthropic_api_key", user_id=user_id) if anth else None),
        )

    def list_user_ids(self) -> "list[str]":
        con = self._connect()
        try:
            return [r[0] for r in con.execute("SELECT user_id FROM tenant_credentials ORDER BY user_id")]
        finally:
            con.close()

    # -- passwords ----------------------------------------------------------------

    def set_password(self, user_id: str, password: str) -> None:
        """Store a scrypt hash. The password itself is never written anywhere."""
        validate_user_id(user_id)
        salt = secrets.token_bytes(16)
        digest = hashlib.scrypt(
            password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_SCRYPT_DKLEN
        )
        con = self._connect()
        try:
            cur = con.execute(
                "UPDATE tenant_credentials SET pw_salt=?, pw_hash=?, pw_n=?, pw_r=?, pw_p=? WHERE user_id=?",
                (salt, digest, _SCRYPT_N, _SCRYPT_R, _SCRYPT_P, user_id),
            )
            if cur.rowcount == 0:
                raise CredentialNotFound("no credentials for tenant " + repr(user_id))
            con.commit()
        finally:
            con.close()

    def verify_password(self, user_id: str, password: str) -> bool:
        """Constant-time check. Returns False (never raises) for unknown tenants.

        An exception here would let an unauthenticated caller distinguish "no such user"
        from "wrong password", which is an account-enumeration oracle on the login form.
        """
        try:
            validate_user_id(user_id)
        except Exception:
            return False
        rec = self._raw_password_record(user_id)
        if rec is None:
            return False
        salt, expected, n, r, p = rec
        if not salt or not expected:
            return False
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=n or _SCRYPT_N,
            r=r or _SCRYPT_R,
            p=p or _SCRYPT_P,
            dklen=len(expected),
        )
        return hmac.compare_digest(digest, expected)

    def _raw_password_record(self, user_id: str):
        """Password row as stored. Exposed for tests asserting salts differ."""
        con = self._connect()
        try:
            return con.execute(
                "SELECT pw_salt, pw_hash, pw_n, pw_r, pw_p FROM tenant_credentials WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        finally:
            con.close()

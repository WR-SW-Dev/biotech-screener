"""Credential-isolation tests for multi-tenancy (design §1).

These are the tests that matter most in this PR: they assert that one tenant's process
cannot reach another tenant's secrets through the resolver, that over-permissive secret
files are refused *before* being read, and that secrets never leak into ``os.environ``.

What these tests deliberately do NOT claim: that OS-level isolation exists. Within a
single OS account any process can read any file that account owns, so the resolver is a
correctness gate, not a security boundary. See the module docstring in
``common/tenancy.py``.
"""

from __future__ import annotations

import json
import os
import stat

import pytest

from common.tenancy import (
    ENV_MULTI_TENANT,
    ENV_USER_ID,
    LEGACY_TENANT,
    CredentialNotFoundError,
    CredentialPermissionError,
    InvalidUserIdError,
    MissingUserContextError,
    RegistryError,
    TenancyError,
    UserContext,
    credentials_dir,
    credentials_file,
    load_registry,
    load_user_secrets,
    parse_env_text,
    require_user_context,
    resolve_user_context,
    validate_user_id,
)

# ---------------------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------------------


def _write_secret(repo_root, user_id: str, body: str, *, mode: int = 0o600):
    d = repo_root / "credentials" / user_id
    d.mkdir(parents=True, exist_ok=True)
    f = d / ".env"
    f.write_text(body, encoding="utf-8")
    f.chmod(mode)
    return f


def _write_registry(repo_root, tenants: dict):
    path = repo_root / "tenants.json"
    path.write_text(json.dumps({"tenants": tenants}), encoding="utf-8")
    return path


@pytest.fixture()
def two_tenants(tmp_path):
    """Two tenants, each with their own secret and account number."""
    _write_secret(
        tmp_path,
        "alice",
        "ANTHROPIC_API_KEY=sk-alice-secret\nROBINHOOD_TOKEN=rh-alice\n",  # pragma: allowlist secret
    )
    _write_secret(
        tmp_path,
        "bob",
        "ANTHROPIC_API_KEY=sk-bob-secret\nROBINHOOD_TOKEN=rh-bob\n",  # pragma: allowlist secret
    )
    reg = _write_registry(
        tmp_path,
        {
            "alice": {
                "account_number": "111111111",
                "broker_server": "robinhood-alice",
            },
            "bob": {"account_number": "222222222", "broker_server": "robinhood-bob"},
        },
    )
    return tmp_path, reg


# ---------------------------------------------------------------------------------------
# user_id validation / path traversal
# ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        "../bob",
        "..",
        "alice/../bob",
        "/etc",
        "alice/bob",
        "alice\\bob",
        "Alice",  # uppercase: would collide on case-insensitive filesystems
        "a",  # too short
        "_hidden",  # leading underscore reserved for the legacy sentinel
        "a" * 33,  # too long
        "alice.bob",  # dots excluded so '..' can never appear
        "",
        "alice$",
        "alice bob",
    ],
)
def test_validate_user_id_rejects_unsafe_ids(bad):
    with pytest.raises(InvalidUserIdError):
        validate_user_id(bad)


@pytest.mark.parametrize("good", ["alice", "bob-2", "user_1", "a1", "x" * 32])
def test_validate_user_id_accepts_safe_ids(good):
    assert validate_user_id(good) == good


def test_legacy_sentinel_is_permitted():
    assert validate_user_id(LEGACY_TENANT) == LEGACY_TENANT


@pytest.mark.parametrize("bad", ["../bob", "alice/../bob", ".."])
def test_credentials_path_cannot_escape_credentials_root(tmp_path, bad):
    """Traversal must fail at validation, never produce a path outside credentials/."""
    with pytest.raises(InvalidUserIdError):
        credentials_dir(bad, repo_root=tmp_path)


def test_credentials_dir_is_per_tenant(tmp_path):
    a = credentials_dir("alice", repo_root=tmp_path)
    b = credentials_dir("bob", repo_root=tmp_path)
    assert a != b
    assert a.parent == b.parent == (tmp_path / "credentials").resolve()


# ---------------------------------------------------------------------------------------
# permission enforcement
# ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("bad_mode", [0o644, 0o640, 0o604, 0o666, 0o660, 0o777])
def test_group_or_world_readable_secret_is_refused(tmp_path, bad_mode):
    _write_secret(tmp_path, "alice", "ANTHROPIC_API_KEY=sk-alice\n", mode=bad_mode)  # pragma: allowlist secret
    ctx = UserContext("alice", "111", "srv", tmp_path / "tenants" / "alice")
    with pytest.raises(CredentialPermissionError):
        load_user_secrets(ctx, repo_root=tmp_path)


def test_owner_only_secret_is_accepted(tmp_path):
    _write_secret(tmp_path, "alice", "ANTHROPIC_API_KEY=sk-alice\n", mode=0o600)  # pragma: allowlist secret
    ctx = UserContext("alice", "111", "srv", tmp_path / "tenants" / "alice")
    secrets = load_user_secrets(ctx, repo_root=tmp_path)
    assert secrets["ANTHROPIC_API_KEY"] == "sk-alice"  # pragma: allowlist secret


def test_permission_is_checked_before_content_is_trusted(tmp_path):
    """A bad-mode file must raise even when its contents are perfectly valid."""
    f = _write_secret(tmp_path, "alice", "ANTHROPIC_API_KEY=sk-valid\n", mode=0o644)  # pragma: allowlist secret
    assert stat.S_IMODE(f.stat().st_mode) == 0o644
    ctx = UserContext("alice", "111", "srv", tmp_path / "tenants" / "alice")
    with pytest.raises(CredentialPermissionError):
        load_user_secrets(ctx, repo_root=tmp_path)


def test_wrong_owner_uid_is_refused(tmp_path):
    _write_secret(tmp_path, "alice", "ANTHROPIC_API_KEY=sk-alice\n")  # pragma: allowlist secret
    ctx = UserContext("alice", "111", "srv", tmp_path / "tenants" / "alice")
    impossible_uid = os.getuid() + 12345 if hasattr(os, "getuid") else 999999
    with pytest.raises(CredentialPermissionError):
        load_user_secrets(ctx, repo_root=tmp_path, expected_uid=impossible_uid)


def test_missing_secret_file_raises_not_found(tmp_path):
    ctx = UserContext("ghost", "111", "srv", tmp_path / "tenants" / "ghost")
    with pytest.raises(CredentialNotFoundError):
        load_user_secrets(ctx, repo_root=tmp_path)


def test_missing_required_secret_is_reported(tmp_path):
    _write_secret(tmp_path, "alice", "SOMETHING_ELSE=1\n")
    ctx = UserContext("alice", "111", "srv", tmp_path / "tenants" / "alice")
    with pytest.raises(TenancyError) as exc:
        load_user_secrets(ctx, repo_root=tmp_path, required=("ANTHROPIC_API_KEY",))
    assert "ANTHROPIC_API_KEY" in str(exc.value)


# ---------------------------------------------------------------------------------------
# cross-tenant isolation
# ---------------------------------------------------------------------------------------


def test_one_tenant_context_never_yields_another_tenants_secret(two_tenants):
    """The core isolation property: resolving alice must not surface bob's key."""
    repo_root, reg = two_tenants
    alice = resolve_user_context("alice", repo_root=repo_root, registry_file=reg)
    bob = resolve_user_context("bob", repo_root=repo_root, registry_file=reg)

    a_secrets = load_user_secrets(alice, repo_root=repo_root)
    b_secrets = load_user_secrets(bob, repo_root=repo_root)

    assert a_secrets["ANTHROPIC_API_KEY"] == "sk-alice-secret"  # pragma: allowlist secret
    assert b_secrets["ANTHROPIC_API_KEY"] == "sk-bob-secret"  # pragma: allowlist secret
    assert a_secrets["ANTHROPIC_API_KEY"] != b_secrets["ANTHROPIC_API_KEY"]
    # No value from bob's file may appear anywhere in alice's resolved secrets.
    assert not (set(a_secrets.values()) & set(b_secrets.values()))


def test_secrets_are_not_written_into_os_environ(two_tenants, monkeypatch):
    """``load_dotenv`` would pollute os.environ; the resolver must not."""
    repo_root, reg = two_tenants
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    ctx = resolve_user_context("alice", repo_root=repo_root, registry_file=reg)

    secrets = load_user_secrets(ctx, repo_root=repo_root)

    assert secrets["ANTHROPIC_API_KEY"] == "sk-alice-secret"  # pragma: allowlist secret
    assert "ANTHROPIC_API_KEY" not in os.environ
    assert "ROBINHOOD_TOKEN" not in os.environ
    assert "sk-alice-secret" not in json.dumps(dict(os.environ))  # pragma: allowlist secret


def test_each_tenant_resolves_to_its_own_account(two_tenants):
    repo_root, reg = two_tenants
    alice = resolve_user_context("alice", repo_root=repo_root, registry_file=reg)
    bob = resolve_user_context("bob", repo_root=repo_root, registry_file=reg)
    assert alice.account_number == "111111111"
    assert bob.account_number == "222222222"
    assert alice.broker_server != bob.broker_server


# ---------------------------------------------------------------------------------------
# registry invariants
# ---------------------------------------------------------------------------------------


def test_registry_rejects_two_tenants_sharing_one_account(tmp_path):
    """A shared account number would make the ownership guard meaningless."""
    reg = _write_registry(
        tmp_path,
        {
            "alice": {"account_number": "999", "broker_server": "srv-a"},
            "bob": {"account_number": "999", "broker_server": "srv-b"},
        },
    )
    with pytest.raises(RegistryError) as exc:
        load_registry(repo_root=tmp_path, path=reg)
    assert "999" in str(exc.value)


def test_registry_requires_account_and_server(tmp_path):
    reg = _write_registry(tmp_path, {"alice": {"broker_server": "srv"}})
    with pytest.raises(RegistryError):
        load_registry(repo_root=tmp_path, path=reg)

    reg2 = _write_registry(tmp_path, {"alice": {"account_number": "111"}})
    with pytest.raises(RegistryError):
        load_registry(repo_root=tmp_path, path=reg2)


def test_registry_rejects_malformed_json(tmp_path):
    path = tmp_path / "tenants.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(RegistryError):
        load_registry(repo_root=tmp_path, path=path)


def test_unknown_tenant_is_refused(two_tenants):
    repo_root, reg = two_tenants
    with pytest.raises(RegistryError):
        resolve_user_context("charlie", repo_root=repo_root, registry_file=reg)


# ---------------------------------------------------------------------------------------
# fail-closed context resolution
# ---------------------------------------------------------------------------------------


def test_multi_tenant_mode_without_user_id_fails_closed(two_tenants, monkeypatch):
    """No silent default tenant — that is how cross-tenant writes happen."""
    repo_root, reg = two_tenants
    monkeypatch.setenv(ENV_MULTI_TENANT, "1")
    monkeypatch.delenv(ENV_USER_ID, raising=False)
    with pytest.raises(MissingUserContextError):
        require_user_context(None, repo_root=repo_root, registry_file=reg)


def test_single_tenant_mode_falls_back_to_legacy(tmp_path, monkeypatch):
    monkeypatch.delenv(ENV_MULTI_TENANT, raising=False)
    monkeypatch.delenv(ENV_USER_ID, raising=False)
    ctx = require_user_context(None, repo_root=tmp_path)
    assert ctx.user_id == LEGACY_TENANT
    assert ctx.is_legacy


def test_explicit_user_beats_environment(two_tenants, monkeypatch):
    repo_root, reg = two_tenants
    monkeypatch.setenv(ENV_USER_ID, "bob")
    ctx = require_user_context("alice", repo_root=repo_root, registry_file=reg)
    assert ctx.user_id == "alice"


def test_context_is_immutable():
    """A mutable context is exactly the race the trading guard exists to prevent."""
    ctx = UserContext("alice", "111", "srv", credentials_file("alice").parent)
    with pytest.raises(Exception):
        ctx.account_number = "222"  # type: ignore[misc]


# ---------------------------------------------------------------------------------------
# env parsing
# ---------------------------------------------------------------------------------------


def test_parse_env_text_handles_comments_quotes_and_export():
    text = "\n".join(
        [
            "# a comment",
            "",
            "PLAIN=value",
            'QUOTED="quoted value"',
            "SINGLE='single'",
            "export EXPORTED=exported",
            "  SPACED  =  padded  ",
            "NOEQUALS",
            "EMPTY=",
        ]
    )
    got = parse_env_text(text)
    assert got["PLAIN"] == "value"
    assert got["QUOTED"] == "quoted value"
    assert got["SINGLE"] == "single"
    assert got["EXPORTED"] == "exported"
    assert got["SPACED"] == "padded"
    assert got["EMPTY"] == ""
    assert "NOEQUALS" not in got


def test_parse_env_text_keeps_hash_inside_value():
    """A '#' after the '=' is part of the secret, not a comment — tokens contain '#'."""
    got = parse_env_text("TOKEN=abc#def\n")
    assert got["TOKEN"] == "abc#def"

"""Per-user (tenant) identity, credential resolution and context plumbing.

See ``docs/design/MULTI_TENANCY.md``. This module is the single place that answers
"which user is this run acting for, and what may it touch?".

Design constraints worth restating at the call site:

* Secrets are returned as a mapping. They are **never** written into ``os.environ``,
  because ``os.environ`` is process-global and inherited by subprocesses.
* Within one OS account, file permissions cannot stop tenant A's process from reading
  tenant B's ``.env``. The checks here are defense-in-depth and a correctness gate; the
  boundary that actually holds is one OS user (or container) per tenant. Do not describe
  this module as a security boundary on its own.

Python 3.10 compatible (CI matrix is 3.10 + 3.12): no ``tomllib``, no ``match``.
"""

from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Tenant ids are used to build filesystem paths, so the charset is deliberately narrow.
#: No dots (blocks ``..``), no slashes, no uppercase (case-insensitive filesystems would
#: otherwise let ``Bob`` and ``bob`` collide).
USER_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,31}$")

#: Sentinel tenant that resolves to the historical single-user layout, byte-identical.
#: Lets ~1,900 unmigrated call sites keep working during the staged migration.
LEGACY_TENANT = "_legacy"

DEFAULT_RETENTION_DAYS = 180
DEFAULT_MIN_KEEP_SNAPSHOTS = 60

ENV_USER_ID = "BIOTECH_USER_ID"
ENV_REGISTRY = "BIOTECH_TENANT_REGISTRY"
ENV_MULTI_TENANT = "BIOTECH_MULTI_TENANT"


class TenancyError(Exception):
    """Base class for tenancy configuration and resolution failures."""


class InvalidUserIdError(TenancyError):
    """The user id is malformed or would escape the credentials/tenants root."""


class CredentialPermissionError(TenancyError):
    """A credential file is readable by users other than its owner."""


class CredentialNotFoundError(TenancyError):
    """No credential file exists for this tenant."""


class RegistryError(TenancyError):
    """The tenant registry is missing, malformed, or internally inconsistent."""


class MissingUserContextError(TenancyError):
    """Multi-tenant mode is on but no user id was supplied."""


@dataclass(frozen=True)
class UserContext:
    """Everything a run needs to know about the tenant it acts for.

    Frozen on purpose: a context that can be mutated mid-run is exactly the race the
    trading guard exists to prevent.
    """

    user_id: str
    account_number: str
    broker_server: str
    data_root: Path
    retention_days: int = DEFAULT_RETENTION_DAYS
    min_keep_snapshots: int = DEFAULT_MIN_KEEP_SNAPSHOTS

    @property
    def is_legacy(self) -> bool:
        return self.user_id == LEGACY_TENANT


def validate_user_id(user_id: str) -> str:
    """Return ``user_id`` if it is safe to interpolate into a path, else raise.

    Rejects traversal (``..``), separators, absolute paths, and anything outside the
    documented charset. ``LEGACY_TENANT`` is permitted despite its leading underscore.
    """
    if not isinstance(user_id, str) or not user_id:
        raise InvalidUserIdError("user_id must be a non-empty string")
    if user_id == LEGACY_TENANT:
        return user_id
    if not USER_ID_RE.match(user_id):
        raise InvalidUserIdError(
            "invalid user_id "
            + repr(user_id)
            + " (allowed: lowercase alnum, '_' and '-', 2-32 chars, must start alnum)"
        )
    return user_id


def _tenant_subdir(root: Path, user_id: str, *, kind: str) -> Path:
    """Join ``root / user_id`` and verify the result stays inside ``root``.

    Belt-and-braces: ``validate_user_id`` already blocks traversal, but a containment
    check means a future regex loosening cannot silently become a path escape.
    """
    validate_user_id(user_id)
    root_resolved = root.resolve()
    candidate = (root_resolved / user_id).resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError:
        raise InvalidUserIdError(
            "resolved " + kind + " path for " + repr(user_id) + " escapes " + str(root_resolved)
        ) from None
    return candidate


def credentials_dir(user_id: str, *, repo_root: Path | None = None) -> Path:
    """Directory holding one tenant's secrets: ``credentials/{user_id}/``."""
    root = (repo_root or REPO_ROOT) / "credentials"
    return _tenant_subdir(root, user_id, kind="credentials")


def credentials_file(user_id: str, *, repo_root: Path | None = None) -> Path:
    return credentials_dir(user_id, repo_root=repo_root) / ".env"


def multi_tenant_enabled() -> bool:
    return os.environ.get(ENV_MULTI_TENANT, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


# --------------------------------------------------------------------------------------
# Credential resolution
# --------------------------------------------------------------------------------------


def _assert_owner_only_permissions(path: Path) -> None:
    """Refuse credential files that group or others can read.

    Checked before reading, so a mis-permissioned secret is never loaded at all.
    """
    mode = path.stat().st_mode
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise CredentialPermissionError(
            str(path)
            + " has mode "
            + oct(stat.S_IMODE(mode))
            + "; must be owner-only (0600). Fix: chmod 600 "
            + str(path)
        )


def _assert_expected_owner(path: Path, expected_uid: int | None) -> None:
    if expected_uid is None:
        return
    actual = path.stat().st_uid
    if actual != expected_uid:
        raise CredentialPermissionError(
            str(path) + " is owned by uid " + str(actual) + ", expected " + str(expected_uid)
        )


def parse_env_text(text: str) -> "dict[str, str]":
    """Minimal ``KEY=VALUE`` parser.

    Deliberately not ``python-dotenv``: ``load_dotenv`` mutates ``os.environ``, which is
    the exact behaviour this module exists to avoid.
    """
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key] = value
    return out


def load_user_secrets(
    ctx: UserContext,
    *,
    repo_root: Path | None = None,
    expected_uid: int | None = None,
    required: "tuple[str, ...]" = (),
) -> Mapping[str, str]:
    """Load one tenant's secrets as a mapping. Never touches ``os.environ``.

    Raises before reading if the file is missing or over-permissive.
    """
    path = credentials_file(ctx.user_id, repo_root=repo_root)
    if not path.is_file():
        raise CredentialNotFoundError("no credential file for tenant " + repr(ctx.user_id) + " at " + str(path))
    _assert_owner_only_permissions(path)
    _assert_expected_owner(path, expected_uid)

    secrets = parse_env_text(path.read_text(encoding="utf-8"))
    missing = [k for k in required if not secrets.get(k)]
    if missing:
        raise TenancyError("tenant " + repr(ctx.user_id) + " is missing required secrets: " + ", ".join(missing))
    return secrets


# --------------------------------------------------------------------------------------
# Tenant registry
# --------------------------------------------------------------------------------------


def registry_path(*, repo_root: Path | None = None) -> Path:
    override = os.environ.get(ENV_REGISTRY, "").strip()
    if override:
        return Path(override)
    return (repo_root or REPO_ROOT) / "tenants.json"


def load_registry(*, repo_root: Path | None = None, path: Path | None = None) -> "dict[str, dict]":
    """Load and validate the tenant registry.

    Enforces the invariant that matters for §5: **no brokerage account number may be
    claimed by two tenants.** A shared account number would make the ownership guard
    meaningless, so it is a load-time error rather than a runtime surprise.
    """
    reg_file = path or registry_path(repo_root=repo_root)
    if not reg_file.is_file():
        raise RegistryError("tenant registry not found at " + str(reg_file))
    try:
        raw = json.loads(reg_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RegistryError("tenant registry " + str(reg_file) + " is not valid JSON: " + str(exc)) from exc

    tenants = raw.get("tenants")
    if not isinstance(tenants, dict) or not tenants:
        raise RegistryError(str(reg_file) + " must contain a non-empty 'tenants' object")

    seen_accounts: dict[str, str] = {}
    cleaned: dict[str, dict] = {}
    for user_id, entry in tenants.items():
        validate_user_id(user_id)
        if not isinstance(entry, dict):
            raise RegistryError("tenant " + repr(user_id) + " entry must be an object")
        account = str(entry.get("account_number", "")).strip()
        server = str(entry.get("broker_server", "")).strip()
        if not account:
            raise RegistryError("tenant " + repr(user_id) + " is missing 'account_number'")
        if not server:
            raise RegistryError("tenant " + repr(user_id) + " is missing 'broker_server'")
        if account in seen_accounts:
            raise RegistryError(
                "account_number "
                + repr(account)
                + " is claimed by both "
                + repr(seen_accounts[account])
                + " and "
                + repr(user_id)
                + "; one account may belong to exactly one tenant"
            )
        seen_accounts[account] = user_id
        cleaned[user_id] = {
            "account_number": account,
            "broker_server": server,
            "retention_days": int(entry.get("retention_days", DEFAULT_RETENTION_DAYS)),
            "min_keep_snapshots": int(entry.get("min_keep_snapshots", DEFAULT_MIN_KEEP_SNAPSHOTS)),
        }
    return cleaned


def tenants_root(*, repo_root: Path | None = None) -> Path:
    return (repo_root or REPO_ROOT) / "tenants"


def resolve_user_context(
    user_id: str,
    *,
    repo_root: Path | None = None,
    registry: "dict[str, dict] | None" = None,
    registry_file: Path | None = None,
) -> UserContext:
    """Build the :class:`UserContext` for ``user_id`` from the registry."""
    validate_user_id(user_id)
    root = repo_root or REPO_ROOT

    if user_id == LEGACY_TENANT:
        return UserContext(
            user_id=LEGACY_TENANT,
            account_number="",
            broker_server="",
            data_root=root,
        )

    reg = registry if registry is not None else load_registry(repo_root=root, path=registry_file)
    entry = reg.get(user_id)
    if entry is None:
        raise RegistryError(
            "tenant " + repr(user_id) + " is not in the registry; known tenants: " + ", ".join(sorted(reg))
        )
    return UserContext(
        user_id=user_id,
        account_number=entry["account_number"],
        broker_server=entry["broker_server"],
        data_root=_tenant_subdir(tenants_root(repo_root=root), user_id, kind="tenant data"),
        retention_days=entry["retention_days"],
        min_keep_snapshots=entry["min_keep_snapshots"],
    )


def require_user_context(
    explicit: str | None = None,
    *,
    repo_root: Path | None = None,
    registry: "dict[str, dict] | None" = None,
    registry_file: Path | None = None,
) -> UserContext:
    """Resolve the acting tenant once per process. Fails closed.

    Order: explicit argument (``--user``) → ``BIOTECH_USER_ID``. In multi-tenant mode a
    missing id is a hard error: silently defaulting to a tenant is how cross-tenant
    writes and cross-account orders happen. Single-tenant mode falls back to
    ``LEGACY_TENANT`` so existing CLI usage is unchanged.
    """
    candidate = (explicit or os.environ.get(ENV_USER_ID, "")).strip()
    if not candidate:
        if multi_tenant_enabled():
            raise MissingUserContextError(
                "multi-tenant mode is enabled but no tenant was supplied; pass --user or set "
                + ENV_USER_ID
                + " (there is deliberately no default tenant)"
            )
        candidate = LEGACY_TENANT
    return resolve_user_context(candidate, repo_root=repo_root, registry=registry, registry_file=registry_file)

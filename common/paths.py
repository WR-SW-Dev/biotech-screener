"""Tenant-scoped filesystem layout.

See ``docs/design/MULTI_TENANCY.md`` §3. Every per-user output path should come from here
rather than a string literal, so that adding a tenant never requires touching call sites.

Two rules this module encodes:

1. **Derived, per-user output is namespaced.** Snapshots, artifacts, caches and the
   per-user parts of ``production_data`` live under ``tenants/{user_id}/``.
2. **Market facts stay single-copy.** Price history, AACT/CT.gov pulls, 13F data and the
   PIT options cache are properties of the market, not of a user. Copying them per tenant
   would multiply a ~550 MB tree by N *and* let two tenants hold divergent "truth" for the
   same date, which breaks point-in-time provenance. They resolve to a shared root.

``LEGACY_TENANT`` resolves to the historical single-user layout **byte-identically**, so
this module can be introduced without changing any existing behaviour.

Python 3.10 compatible.
"""

from __future__ import annotations

from pathlib import Path

from common.tenancy import LEGACY_TENANT, UserContext

#: Entries under ``production_data/`` that are market facts rather than per-user output.
#: During the staged migration (design §3, PR 4) these stay in the shared root while the
#: rest of ``production_data/`` becomes tenant-scoped. Listed explicitly because getting
#: this split wrong is how PIT provenance breaks.
SHARED_MARKET_FILES = (
    "price_history.csv",
    "price_history_split_adj.csv",
    "indices_prices.csv",
    "universe_prices.csv",
    "short_interest.json",
    "market_data.json",
)

#: Cache subdirectories that are shared and must never be tenant-duplicated or pruned.
#: ``massive_options`` holds point-in-time options data that cannot be re-fetched.
SHARED_CACHE_DIRS = ("massive_options",)


class UserPaths:
    """Resolve per-tenant paths for one :class:`UserContext`.

    >>> from common.tenancy import UserContext
    >>> ctx = UserContext("alice", "111", "robinhood-alice", Path("/repo/tenants/alice"))
    >>> UserPaths(ctx, repo_root=Path("/repo")).snapshot("2026-07-31").as_posix()
    '/repo/tenants/alice/data/snapshots/2026-07-31'
    """

    def __init__(self, ctx: UserContext, *, repo_root: Path | None = None) -> None:
        self.ctx = ctx
        self.repo_root = Path(repo_root) if repo_root is not None else _default_repo_root()

    # -- base -------------------------------------------------------------------------

    @property
    def base(self) -> Path:
        """Root for this tenant's derived output.

        For the legacy tenant this is the repo root, which is what makes the legacy
        layout identical to the pre-multi-tenant one.
        """
        if self.ctx.is_legacy:
            return self.repo_root
        return self.repo_root / "tenants" / self.ctx.user_id

    # -- per-tenant, derived ----------------------------------------------------------

    @property
    def snapshots_root(self) -> Path:
        return self.base / "data" / "snapshots"

    def snapshot(self, as_of_date: str) -> Path:
        return self.snapshots_root / as_of_date

    def rankings_csv(self, as_of_date: str) -> Path:
        return self.snapshot(as_of_date) / "rankings.csv"

    @property
    def artifacts_root(self) -> Path:
        return self.base / "artifacts"

    @property
    def caches_root(self) -> Path:
        return self.base / "data" / "caches"

    @property
    def production_data(self) -> Path:
        """Per-user portion of ``production_data/``.

        Note: today this directory also holds the files in :data:`SHARED_MARKET_FILES`.
        Use :meth:`shared_market_file` for those; see design §3 PR 4 for the split.
        """
        return self.base / "production_data"

    @property
    def logs_root(self) -> Path:
        return self.base / "logs"

    # -- shared, single-copy ----------------------------------------------------------

    @property
    def shared_root(self) -> Path:
        """Market-fact root, identical for every tenant."""
        return self.repo_root / "production_data"

    def shared_market_file(self, name: str) -> Path:
        """Path to a shared market-data file, refusing anything not on the allowlist.

        The allowlist is enforced so a caller cannot quietly reach a *per-user* file
        through the shared accessor and read another tenant's output.
        """
        if name not in SHARED_MARKET_FILES:
            raise ValueError(
                repr(name) + " is not a shared market file; expected one of: " + ", ".join(SHARED_MARKET_FILES)
            )
        return self.shared_root / name

    @property
    def shared_caches_root(self) -> Path:
        return self.repo_root / "data" / "caches"

    def shared_cache_dir(self, name: str) -> Path:
        if name not in SHARED_CACHE_DIRS:
            raise ValueError(
                repr(name) + " is not a shared cache dir; expected one of: " + ", ".join(SHARED_CACHE_DIRS)
            )
        return self.shared_caches_root / name

    # -- helpers ----------------------------------------------------------------------

    def ensure_dirs(self, *, mode: int = 0o700) -> None:
        """Create this tenant's directory tree with owner-only permissions.

        ``0700`` on tenant roots keeps other OS users out; within a single OS account it
        is advisory only (see ``common.tenancy`` module docstring).
        """
        for path in (
            self.snapshots_root,
            self.artifacts_root,
            self.caches_root,
            self.production_data,
            self.logs_root,
        ):
            path.mkdir(parents=True, exist_ok=True)
            if not self.ctx.is_legacy:
                try:
                    path.chmod(mode)
                except (OSError, NotImplementedError):
                    # Windows / mounted filesystems (/mnt/c) may not honour POSIX modes.
                    pass

    def owns(self, path: Path) -> bool:
        """True if ``path`` lies inside this tenant's derived-output tree.

        Used by the namespacing tests and by any code that must prove it is not about to
        write across a tenant boundary. The legacy tenant's base is the repo root, so
        this is intentionally permissive for it.
        """
        try:
            Path(path).resolve().relative_to(self.base.resolve())
        except ValueError:
            return False
        return True


def _default_repo_root() -> Path:
    from common.tenancy import REPO_ROOT

    return REPO_ROOT


def for_user(ctx: UserContext, *, repo_root: Path | None = None) -> UserPaths:
    """Convenience constructor mirroring the design doc's ``paths.for_user(ctx)``."""
    return UserPaths(ctx, repo_root=repo_root)


def legacy_paths(*, repo_root: Path | None = None) -> UserPaths:
    """Paths for the pre-multi-tenant layout, for comparison in tests and migration."""
    root = Path(repo_root) if repo_root is not None else _default_repo_root()
    ctx = UserContext(
        user_id=LEGACY_TENANT,
        account_number="",
        broker_server="",
        data_root=root,
    )
    return UserPaths(ctx, repo_root=root)

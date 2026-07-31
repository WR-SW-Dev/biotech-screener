"""Per-user data-namespacing tests (design §3).

Three properties are asserted here:

1. **Legacy compatibility** — ``LEGACY_TENANT`` resolves to the exact pre-multi-tenant
   layout, so introducing ``common.paths`` changes no existing behaviour. This is what
   makes the 1,894-reference migration safe to do incrementally.
2. **No collision** — two tenants writing the same snapshot date land in different
   directories, and neither can reach the other's tree.
3. **Shared data stays shared** — market facts are not duplicated per tenant, because
   duplication both multiplies the tree and lets two tenants hold divergent "truth" for
   the same date, which breaks PIT provenance.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from common.paths import SHARED_CACHE_DIRS, SHARED_MARKET_FILES, UserPaths, for_user, legacy_paths
from common.tenancy import InvalidUserIdError, UserContext, resolve_user_context


def _ctx(user_id: str, account: str, root: Path) -> UserContext:
    return UserContext(
        user_id=user_id,
        account_number=account,
        broker_server="srv-" + user_id,
        data_root=root / "tenants" / user_id,
    )


@pytest.fixture()
def alice(tmp_path):
    return for_user(_ctx("alice", "111", tmp_path), repo_root=tmp_path)


@pytest.fixture()
def bob(tmp_path):
    return for_user(_ctx("bob", "222", tmp_path), repo_root=tmp_path)


# ---------------------------------------------------------------------------------------
# 1. legacy compatibility
# ---------------------------------------------------------------------------------------


def test_legacy_layout_is_unchanged(tmp_path):
    """The legacy tenant must resolve to today's paths exactly."""
    p = legacy_paths(repo_root=tmp_path)
    assert p.snapshots_root == tmp_path / "data" / "snapshots"
    assert p.snapshot("2026-07-31") == tmp_path / "data" / "snapshots" / "2026-07-31"
    assert p.rankings_csv("2026-07-31") == tmp_path / "data" / "snapshots" / "2026-07-31" / "rankings.csv"
    assert p.production_data == tmp_path / "production_data"
    assert p.artifacts_root == tmp_path / "artifacts"
    assert p.caches_root == tmp_path / "data" / "caches"


def test_legacy_base_is_repo_root(tmp_path):
    p = legacy_paths(repo_root=tmp_path)
    assert p.base == tmp_path
    assert p.ctx.is_legacy


def test_legacy_has_no_tenants_segment(tmp_path):
    """A stray 'tenants/' in a legacy path would mean existing data silently moved."""
    p = legacy_paths(repo_root=tmp_path)
    for path in (p.snapshots_root, p.production_data, p.artifacts_root, p.caches_root):
        assert "tenants" not in path.relative_to(tmp_path).parts


# ---------------------------------------------------------------------------------------
# 2. no collision between tenants
# ---------------------------------------------------------------------------------------


def test_same_date_resolves_to_different_dirs_per_tenant(alice, bob):
    a = alice.snapshot("2026-07-31")
    b = bob.snapshot("2026-07-31")
    assert a != b
    assert a.name == b.name == "2026-07-31"


def test_tenant_paths_are_namespaced_under_tenant_id(tmp_path, alice):
    rel = alice.snapshots_root.relative_to(tmp_path)
    assert rel.parts[:2] == ("tenants", "alice")


@pytest.mark.parametrize(
    "attr",
    ["snapshots_root", "artifacts_root", "caches_root", "production_data", "logs_root"],
)
def test_every_per_tenant_root_differs_between_tenants(alice, bob, attr):
    assert getattr(alice, attr) != getattr(bob, attr)


def test_owns_rejects_other_tenants_paths(alice, bob):
    """The containment predicate must be a real boundary, both directions."""
    assert alice.owns(alice.snapshot("2026-07-31"))
    assert not alice.owns(bob.snapshot("2026-07-31"))
    assert bob.owns(bob.snapshot("2026-07-31"))
    assert not bob.owns(alice.snapshot("2026-07-31"))


def test_owns_rejects_paths_outside_repo(alice):
    assert not alice.owns(Path("/etc/passwd"))
    assert not alice.owns(alice.repo_root / "production_data" / "price_history.csv")


def test_owns_is_not_prefix_confusable(tmp_path):
    """'alice2' must not be treated as inside 'alice' — a plain startswith would."""
    a = for_user(_ctx("alice", "1", tmp_path), repo_root=tmp_path)
    a2 = for_user(_ctx("alice2", "2", tmp_path), repo_root=tmp_path)
    assert not a.owns(a2.snapshot("2026-07-31"))
    assert not a2.owns(a.snapshot("2026-07-31"))


def test_ensure_dirs_creates_only_that_tenants_tree(alice, bob):
    alice.ensure_dirs()
    assert alice.snapshots_root.is_dir()
    assert alice.artifacts_root.is_dir()
    assert not bob.snapshots_root.exists()


def test_tenant_id_traversal_cannot_build_a_path(tmp_path):
    """Traversal is blocked at context construction, so paths can never be built."""
    with pytest.raises(InvalidUserIdError):
        resolve_user_context("../bob", repo_root=tmp_path)


# ---------------------------------------------------------------------------------------
# 3. shared market data stays shared
# ---------------------------------------------------------------------------------------


def test_shared_market_files_are_not_tenant_scoped(alice, bob):
    for name in SHARED_MARKET_FILES:
        a = alice.shared_market_file(name)
        b = bob.shared_market_file(name)
        assert a == b, name + " must resolve to one shared copy"
        assert "tenants" not in a.parts


def test_shared_caches_are_not_tenant_scoped(alice, bob):
    for name in SHARED_CACHE_DIRS:
        assert alice.shared_cache_dir(name) == bob.shared_cache_dir(name)
        assert "tenants" not in alice.shared_cache_dir(name).parts


def test_shared_accessor_refuses_non_allowlisted_names(alice):
    """Otherwise the shared accessor becomes a way to read a per-user file."""
    with pytest.raises(ValueError):
        alice.shared_market_file("rankings.csv")
    with pytest.raises(ValueError):
        alice.shared_market_file("../../etc/passwd")
    with pytest.raises(ValueError):
        alice.shared_cache_dir("not_shared")


def test_massive_options_is_declared_shared():
    """Regression guard: this cache holds non-re-fetchable PIT options data."""
    assert "massive_options" in SHARED_CACHE_DIRS


def test_price_history_is_declared_shared():
    """Two tenants must never hold divergent price history for the same date."""
    assert "price_history.csv" in SHARED_MARKET_FILES


# ---------------------------------------------------------------------------------------
# construction
# ---------------------------------------------------------------------------------------


def test_for_user_and_direct_construction_agree(tmp_path):
    ctx = _ctx("alice", "111", tmp_path)
    assert for_user(ctx, repo_root=tmp_path).base == UserPaths(ctx, repo_root=tmp_path).base


def test_legacy_and_tenant_trees_do_not_overlap(tmp_path, alice):
    legacy = legacy_paths(repo_root=tmp_path)
    # A tenant's snapshots live under the legacy base (repo root) by construction, but the
    # reverse must not hold: legacy snapshots are never inside a tenant tree.
    assert not alice.owns(legacy.snapshot("2026-07-31"))

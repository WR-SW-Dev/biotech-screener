"""Tests for the behavioral model-hash boundary (HASH_SCHEME = ast-v1).

Regression guard for the 2026-07-10 finding: the raw-bytes model hash flipped
the frozen forward-validation candidate (a9983a67 -> a7a80e85) on a one-line
type-annotation edit despite byte-for-byte identical runtime behavior. The
behavioral fingerprint must be insensitive to annotations/docstrings/comments/
whitespace and sensitive to real logic changes.

See docs/governance/2026-07-10-dem-candidate-hash-equivalence.md.
"""

from __future__ import annotations

import tools.run_forward_validation as m


def _hash_with_files(monkeypatch, tmp_path, sources: dict[str, str]) -> str:
    paths = []
    for name, src in sources.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(src, encoding="utf-8")
        paths.append(p)
    monkeypatch.setattr(m, "MODEL_FILES", paths)
    return m.compute_model_hash()


BASE = '''\
"""Original docstring."""
import math

THRESHOLD = 0.5


def score(alpha: float, beta: float = 1.0) -> float:
    """Compute a score."""
    # weighting comment
    total: float = alpha * 2 + beta
    return total
'''

# Same runtime behavior — only annotations, docstrings, comments, whitespace differ.
COSMETIC = """\
import math

THRESHOLD = 0.5

def score(alpha, beta=1.0):
    total = alpha * 2 + beta
    return total
"""

# Real logic change: the multiplier 2 -> 3.
LOGIC = '''\
"""Original docstring."""
import math

THRESHOLD = 0.5


def score(alpha: float, beta: float = 1.0) -> float:
    """Compute a score."""
    total: float = alpha * 3 + beta
    return total
'''


def test_cosmetic_edits_do_not_change_hash(monkeypatch, tmp_path):
    h_base = _hash_with_files(monkeypatch, tmp_path / "a", {"m.py": BASE})
    h_cos = _hash_with_files(monkeypatch, tmp_path / "b", {"m.py": COSMETIC})
    assert h_base == h_cos, "annotation/docstring/comment/whitespace edits must not move the hash"


def test_logic_edit_changes_hash(monkeypatch, tmp_path):
    h_base = _hash_with_files(monkeypatch, tmp_path / "a", {"m.py": BASE})
    h_logic = _hash_with_files(monkeypatch, tmp_path / "b", {"m.py": LOGIC})
    assert h_base != h_logic, "a real logic change must move the hash"


def test_legacy_scheme_is_fooled_by_annotations(monkeypatch, tmp_path):
    """Documents the original defect the behavioral scheme fixes."""
    for name, src in {"a": BASE, "b": COSMETIC}.items():
        p = tmp_path / name
        p.mkdir()
        (p / "m.py").write_text(src, encoding="utf-8")
    monkeypatch.setattr(m, "MODEL_FILES", [tmp_path / "a" / "m.py"])
    legacy_base = m.compute_model_hash_legacy()
    monkeypatch.setattr(m, "MODEL_FILES", [tmp_path / "b" / "m.py"])
    legacy_cos = m.compute_model_hash_legacy()
    assert legacy_base != legacy_cos  # raw bytes differ -> false drift


def test_scheme_tag_is_mixed_in(monkeypatch, tmp_path):
    """A scheme bump must change the hash so schemes never collide."""
    p = tmp_path / "m.py"
    p.write_text(BASE, encoding="utf-8")
    monkeypatch.setattr(m, "MODEL_FILES", [p])
    baseline = m.compute_model_hash()
    monkeypatch.setattr(m, "HASH_SCHEME", "ast-v-other")
    assert m.compute_model_hash() != baseline


def test_bare_annotation_dropped_valued_annotation_preserved(monkeypatch, tmp_path):
    # `x: int` (no value) has no runtime effect and must be ignored; `x: int = 5`
    # must be preserved as a real assignment (so changing its value moves the hash).
    with_bare = "def f():\n    x: int\n    return 1\n"
    without = "def f():\n    return 1\n"
    h1 = _hash_with_files(monkeypatch, tmp_path / "a", {"m.py": with_bare})
    h2 = _hash_with_files(monkeypatch, tmp_path / "b", {"m.py": without})
    assert h1 == h2

    valued_5 = "def f():\n    x: int = 5\n    return x\n"
    valued_6 = "def f():\n    x: int = 6\n    return x\n"
    h5 = _hash_with_files(monkeypatch, tmp_path / "c", {"m.py": valued_5})
    h6 = _hash_with_files(monkeypatch, tmp_path / "d", {"m.py": valued_6})
    assert h5 != h6

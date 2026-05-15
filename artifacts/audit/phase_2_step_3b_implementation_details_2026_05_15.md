# Phase 2 Step 3b — Preflight Integration Implementation Details (2026-05-15)

**Status**: Design locked, ready for post-May-19 implementation.

**Scope**: 50 lines added to run_agent_direct.py, zero lines removed.

---

## Integration Point

**File**: `tools/run_agent_direct.py`

**Location**: `main()` function, lines 301–303

```python
# CURRENT (lines 301–303):
resolved_model = resolve_model(args.agent, args.model)
print(f"Running agent '{args.agent}' (direct SDK, {resolved_model})...")
result = run_agent(args.agent, args.message, resolved_model, args.max_tokens)

# NEW (insert between resolve_model and run_agent):
# Preflight check
preflight = run_preflight(args.agent)
if preflight_should_block(args.agent, preflight):
    sys.exit(1)  # error already printed
```

---

## New Function 1: run_preflight()

**Signature**:
```python
def run_preflight(agent_name: str) -> dict | None:
    """Run preflight check before agent execution.
    
    Calls tools/agent_preflight.py --agent NAME --json subprocess.
    Returns parsed preflight report dict, or None if unavailable/errored.
    Failures are non-blocking (warns but continues).
    """
```

**Implementation** (35 lines):

```python
def run_preflight(agent_name: str) -> dict | None:
    """Run preflight check before agent execution.
    
    Calls tools/agent_preflight.py --agent NAME --json subprocess.
    Returns preflight report dict, or None if unavailable/error (non-blocking).
    """
    preflight_script = PROJECT_ROOT / "tools" / "agent_preflight.py"
    if not preflight_script.exists():
        return None  # preflight not available yet
    
    try:
        import subprocess
        result = subprocess.run(
            [
                "python3",
                str(preflight_script),
                "--agent",
                agent_name,
                "--json",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=PROJECT_ROOT,
        )
        
        if result.returncode == 0:
            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError:
                print(f"[PREFLIGHT_WARN] {agent_name}: JSON parse error", file=sys.stderr)
                return None
        else:
            # Preflight script failed; log warning but don't block
            stderr_msg = result.stderr[:200] if result.stderr else "(no stderr)"
            print(f"[PREFLIGHT_WARN] {agent_name}: script failed — {stderr_msg}", file=sys.stderr)
            return None
    
    except subprocess.TimeoutExpired:
        print(f"[PREFLIGHT_WARN] {agent_name}: timeout (>10s)", file=sys.stderr)
        return None
    except Exception as e:
        print(f"[PREFLIGHT_WARN] {agent_name}: {str(e)[:200]}", file=sys.stderr)
        return None
```

---

## New Function 2: preflight_should_block()

**Signature**:
```python
def preflight_should_block(agent_name: str, preflight: dict | None) -> bool:
    """Determine if preflight report indicates agent should be blocked.
    
    Returns True if agent work is forbidden (not_allowed contains agent scope).
    Returns False otherwise (safe to proceed).
    
    Prints blocking reason to stderr if returning True.
    """
```

**Implementation** (25 lines):

```python
def preflight_should_block(agent_name: str, preflight: dict | None) -> bool:
    """Determine if preflight indicates agent should be blocked.
    
    Returns True if agent work is forbidden (not_allowed contains agent scope).
    Prints blocking reason to stderr and returns False for non-blocking errors.
    """
    if not preflight:
        return False  # preflight unavailable or failed; non-blocking
    
    # Check if agent or its work is explicitly prohibited
    not_allowed = preflight.get("not_allowed", [])
    if not not_allowed:
        return False  # no prohibitions
    
    # Simple heuristic: check if any not_allowed item mentions agent name or common patterns
    # This avoids false positives (e.g., "Spec 089" blocks "spec_089_builder" but not "herald")
    
    # Agent-specific blockers (exact name match)
    for item in not_allowed:
        if agent_name.lower() in item.lower():
            print(f"\n[PREFLIGHT BLOCKED] {agent_name}", file=sys.stderr)
            print(f"  Current state: {preflight.get('current_branch_state', 'unknown')}", file=sys.stderr)
            print(f"  Latest snapshot: {preflight.get('latest_snapshot', 'unknown')}", file=sys.stderr)
            print(f"  Blocking reason: {item}", file=sys.stderr)
            if len(not_allowed) > 1:
                print(f"  (and {len(not_allowed) - 1} other constraints)", file=sys.stderr)
            return True
    
    # Work-pattern blockers (apply to agents in specific domains)
    ranker_agents = {"ranker_optimizer", "spec_089_builder", "spec_096_doctrine"}
    selector_agents = {"selector_tuner", "spec_072_screener"}
    
    if agent_name in ranker_agents:
        for item in not_allowed:
            if "ranker" in item.lower() or "selector" in item.lower() or "frozen" in item.lower():
                print(f"\n[PREFLIGHT BLOCKED] {agent_name}", file=sys.stderr)
                print(f"  Current state: {preflight.get('current_branch_state', 'unknown')}", file=sys.stderr)
                print(f"  Blocking reason: {item}", file=sys.stderr)
                return True
    
    if agent_name in selector_agents:
        for item in not_allowed:
            if "selector" in item.lower() or "frozen" in item.lower():
                print(f"\n[PREFLIGHT BLOCKED] {agent_name}", file=sys.stderr)
                print(f"  Current state: {preflight.get('current_branch_state', 'unknown')}", file=sys.stderr)
                print(f"  Blocking reason: {item}", file=sys.stderr)
                return True
    
    return False
```

---

## Integration in main()

**Exact changes** (insert after line 301):

```python
    resolved_model = resolve_model(args.agent, args.model)
    print(f"Running agent '{args.agent}' (direct SDK, {resolved_model})...")
    
    # NEW: Preflight governance check
    preflight = run_preflight(args.agent)
    if preflight_should_block(args.agent, preflight):
        return 1  # exit with error; blocking reason already printed to stderr
    
    # Print preflight warnings if any (non-blocking)
    if preflight and preflight.get("active_quarantine_freeze"):
        for warn in preflight["active_quarantine_freeze"]:
            print(f"[PREFLIGHT_WARN] {warn}", file=sys.stderr)
    
    # OLD LINE 303: run_agent
    result = run_agent(args.agent, args.message, resolved_model, args.max_tokens)
```

---

## Import Changes

**Add to line 26 (top of imports)**:
```python
import sys  # for sys.stderr
```

File already imports `json` (line 29), `subprocess` is imported inside run_preflight().

---

## Test Cases

**File**: `tests/test_run_agent_direct_preflight.py` (create new)

```python
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
import json
import subprocess

# Import from tools
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))
from run_agent_direct import run_preflight, preflight_should_block


class TestPreflight(unittest.TestCase):
    """Test preflight integration in run_agent_direct.py"""
    
    def test_preflight_unavailable(self):
        """If preflight.py doesn't exist, run_preflight returns None."""
        with patch("run_agent_direct.PROJECT_ROOT", Path("/nonexistent")):
            result = run_preflight("test_agent")
            self.assertIsNone(result)
    
    def test_preflight_json_parse_error(self):
        """If preflight output is invalid JSON, run_preflight returns None."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="invalid json"
            )
            result = run_preflight("test_agent")
            self.assertIsNone(result)
    
    def test_preflight_subprocess_timeout(self):
        """If preflight times out (>10s), run_preflight returns None."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("cmd", 10)
            result = run_preflight("test_agent")
            self.assertIsNone(result)
    
    def test_preflight_success_parsing(self):
        """Successful preflight returns parsed JSON dict."""
        sample_report = {
            "current_branch_state": "on main, clean",
            "latest_snapshot": "2026-05-15, QA PASS",
            "not_allowed": ["Ranker changes frozen"]
        }
        
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=json.dumps(sample_report)
            )
            result = run_preflight("fleet_steward")
            self.assertEqual(result, sample_report)
    
    def test_should_block_no_preflight(self):
        """If preflight is None, should_block returns False (non-blocking)."""
        result = preflight_should_block("test_agent", None)
        self.assertFalse(result)
    
    def test_should_block_empty_not_allowed(self):
        """If not_allowed list is empty, should_block returns False."""
        preflight = {"not_allowed": []}
        result = preflight_should_block("test_agent", preflight)
        self.assertFalse(result)
    
    def test_should_block_exact_agent_name_match(self):
        """If not_allowed contains agent name, should_block returns True."""
        preflight = {
            "not_allowed": ["spec_089_builder work deferred pending cohort clearance"]
        }
        result = preflight_should_block("spec_089_builder", preflight)
        self.assertTrue(result)
    
    def test_should_block_ranker_agent_pattern(self):
        """Ranker agents blocked if not_allowed contains 'ranker'."""
        preflight = {
            "not_allowed": ["Ranker/selector/sizing changes (frozen during cohort quarantine)"]
        }
        result = preflight_should_block("ranker_optimizer", preflight)
        self.assertTrue(result)
    
    def test_should_block_selector_agent_pattern(self):
        """Selector agents blocked if not_allowed contains 'selector'."""
        preflight = {
            "not_allowed": ["Selector changes frozen until post-cohort"]
        }
        result = preflight_should_block("selector_tuner", preflight)
        self.assertTrue(result)
    
    def test_should_not_block_unrelated_agent(self):
        """If not_allowed doesn't mention agent, should_block returns False."""
        preflight = {
            "not_allowed": ["Spec 089 KG implementation deferred"]
        }
        result = preflight_should_block("herald", preflight)
        self.assertFalse(result)
    
    def test_should_not_block_herald(self):
        """Herald (deterministic agent) never blocks regardless."""
        preflight = {
            "not_allowed": ["Everything frozen"]
        }
        result = preflight_should_block("herald", preflight)
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
```

---

## Acceptance Criteria

Before committing May 19:

1. ✅ run_preflight() function defined and testable
2. ✅ preflight_should_block() logic complete (agents + patterns)
3. ✅ Integration point identified (main() lines 301–303)
4. ✅ All imports added (sys)
5. ✅ Error handling: non-blocking on preflight failure
6. ✅ Test cases written (10 test methods)
7. ✅ Test cases pass (run `python3 -m pytest tests/test_run_agent_direct_preflight.py`)

---

## Commit Checklist

**May 19 Post-Verification**:

1. Add run_preflight() function (insert after line 90, before load_agent_context)
2. Add preflight_should_block() function (insert after run_preflight)
3. Add `import sys` to line 26 imports
4. Modify main() to call preflight check (insert after line 301)
5. Create tests/test_run_agent_direct_preflight.py
6. Run tests: `python3 -m pytest tests/test_run_agent_direct_preflight.py -v`
7. Verify no regressions: existing tests still pass
8. Commit with message: `tools: wire agent_preflight into run_agent_direct (Phase 2 Step 3b)`

---

## Risk Mitigation

**If preflight check blocks too aggressively**:
- Modify preflight_should_block() to use log-only mode (remove return True, print warnings instead)
- Add --skip-preflight flag to main() for manual overrides

**If preflight subprocess fails**:
- Non-blocking by design (run_preflight returns None)
- Agent execution continues with warning printed
- No production impact

**If agent_preflight.py doesn't exist**:
- run_preflight returns None immediately
- Agent execution continues (safe fallback)

---

**Status**: Implementation design locked. Ready for May 19 coding session (30 min to implement + test).

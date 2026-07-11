import textwrap

import tools.test_trust_audit as audit


def _analyze(source: str, rel_path: str = "tests/test_sample_subject.py"):
    findings, test_count = audit.analyze_source_text(
        textwrap.dedent(source),
        rel_path,
        frozen_markers=["decision_engine", "decision_engine.py"],
    )
    return findings, test_count


def _detectors(findings):
    return {f.detector for f in findings}


def test_t2_no_effective_assert():
    findings, test_count = _analyze("""
        def test_no_assertions():
            x = 1 + 1
            y = x * 2
        """)
    assert test_count == 1
    assert "T2" in _detectors(findings)


def test_t3_tautological_assertion():
    findings, _ = _analyze("""
        def test_tautology():
            lhs = compute()
            rhs = compute()
            assert lhs == lhs
        """)
    assert "T3" in _detectors(findings)


def test_t4_mock_of_subject_is_critical_and_model_path():
    findings, _ = _analyze(
        """
        from unittest.mock import patch

        @patch("decision_engine.score_position")
        def test_decision_engine_behavior(mock_score):
            assert mock_score is not None
        """,
        rel_path="tests/test_decision_engine_behavior.py",
    )
    t4 = [f for f in findings if f.detector == "T4"]
    assert t4
    assert t4[0].severity == "CRITICAL"
    assert t4[0].model_path is True
    assert t4[0].report_only is True


def test_t5_swallowed_failure():
    findings, _ = _analyze("""
        def test_swallowed():
            try:
                assert False
            except Exception:
                pass
        """)
    assert "T5" in _detectors(findings)


def test_t6_vacuous_parametrize():
    findings, _ = _analyze("""
        import pytest

        @pytest.mark.parametrize("x", [])
        def test_empty_parametrize(x):
            assert x
        """)
    assert "T6" in _detectors(findings)


def test_t7_silent_skip():
    findings, _ = _analyze("""
        import pytest

        @pytest.mark.skip
        def test_skipped():
            assert False
        """)
    assert "T7" in _detectors(findings)


def test_t12_over_broad_snapshot_only_shape_assertions():
    findings, _ = _analyze("""
        def test_snapshot_shape_only():
            payload = {"a": 1, "b": 2}
            assert payload is not None
            assert len(payload) > 0
            assert isinstance(payload, dict)
        """)
    assert "T12" in _detectors(findings)


def test_l0_warning_parser_finds_t1_and_grouped_t11():
    warning_text = textwrap.dedent("""
        tests/test_pos_model_v2.py::test_enum_parsing
          /home/x/_pytest/python.py:170: PytestReturnNotNoneWarning: Test functions should return None, but tests/test_pos_model_v2.py::test_enum_parsing returned <class 'tests.test_pos_model_v2.TestResults'>.

        tests/test_options_diagnostics.py::TestFetchWithMock::test_basic_fetch
        tests/test_options_diagnostics.py::TestFetchWithMock::test_term_slope_computed
          /home/x/tastytrade/streamer.py:397: RuntimeWarning: coroutine 'AsyncMockMixin._execute_mock_call' was never awaited
        """)
    test_index = {
        "tests/test_pos_model_v2.py::test_enum_parsing": 44,
        "tests/test_options_diagnostics.py::TestFetchWithMock::test_basic_fetch": 1,
    }
    findings = audit.parse_l0_warnings(warning_text, test_index, frozen_markers=["decision_engine"])
    detectors = [f.detector for f in findings]
    assert detectors.count("T1") == 1
    assert detectors.count("T11") == 1


def test_uncertain_emitted_for_unparsable_test_file():
    findings, test_count = _analyze("def test_broken(:\n    pass\n")
    assert test_count == 0
    assert "UNCERTAIN" in _detectors(findings)

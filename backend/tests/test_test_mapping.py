from app.core.test_mapping import map_source_to_tests
from app.core.test_runner import build_test_checklist


def test_only_related_tests_are_selected_and_unrelated_tests_are_skipped(tmp_path):
    source = tmp_path / "src"
    tests = tmp_path / "tests"
    source.mkdir()
    tests.mkdir()
    (source / "billing.py").write_text("def total(): return 0\n")
    (tests / "test_billing.py").write_text("def test_total(): pass\n")
    (tests / "test_users.py").write_text("def test_user(): pass\n")

    selected = map_source_to_tests(["src/billing.py"], tmp_path)
    checklist = build_test_checklist(
        tmp_path,
        selected,
        [{"test_file": "tests/test_billing.py", "status": "passed"}],
    )

    # The changed module's test runs while unrelated discovered tests are explicit skips.
    assert selected == ["tests/test_billing.py"]
    assert checklist == {
        "affected": [{"test_file": "tests/test_billing.py", "status": "passed"}],
        "skipped": ["tests/test_users.py"],
    }

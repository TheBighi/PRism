import json

from app.core.dependency_diff import diff_dependencies, dependency_state


def test_dependency_changes_for_package_json_and_requirements_txt(tmp_path):
    base = tmp_path / "base"
    head = tmp_path / "head"
    base.mkdir()
    head.mkdir()

    (base / "package.json").write_text(json.dumps({
        "dependencies": {"removed-js": "1.0.0", "changed-js": "1.0.0"},
    }))
    (head / "package.json").write_text(json.dumps({
        "dependencies": {"added-js": "1.0.0", "changed-js": "2.0.0"},
    }))
    (base / "requirements.txt").write_text(
        "removed-py==1.0.0\nchanged-py==1.0.0\n"
    )
    (head / "requirements.txt").write_text(
        "added-py==1.0.0\nchanged-py==2.0.0\n"
    )

    changes = diff_dependencies(dependency_state(head), dependency_state(base))

    # Both manifest formats report additions, removals, and version changes.
    actual = {
        (change.file, change.name, change.kind, change.old_version, change.new_version)
        for change in changes
    }
    assert actual == {
        ("package.json", "added-js", "added", None, "1.0.0"),
        ("package.json", "removed-js", "removed", "1.0.0", None),
        ("package.json", "changed-js", "changed", "1.0.0", "2.0.0"),
        ("requirements.txt", "added-py", "added", None, "1.0.0"),
        ("requirements.txt", "removed-py", "removed", "1.0.0", None),
        ("requirements.txt", "changed-py", "changed", "1.0.0", "2.0.0"),
    }

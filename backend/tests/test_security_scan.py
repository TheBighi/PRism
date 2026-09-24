import json
import subprocess

from app.core.security_scan import scan_files


def test_npm_audit_runs_for_node_project_in_subfolder(tmp_path, monkeypatch):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "package.json").write_text("{}\n")
    (frontend / "package-lock.json").write_text("{}\n")
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs["cwd"]))
        output = {"vulnerabilities": {"demo": {"severity": "high", "via": []}}}
        return subprocess.CompletedProcess(command, 1, json.dumps(output), "")

    monkeypatch.setattr("app.core.security_scan.subprocess.run", fake_run)

    findings = scan_files(tmp_path, [])

    # Monorepo projects must be audited from their own working directory.
    assert calls == [(["npm", "audit", "--json"], frontend)]
    assert findings[0]["file"] == "frontend/package.json"

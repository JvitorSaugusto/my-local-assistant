from backend.graph import audit_core as ac


def test_spacing_detects_and_fixes_e301_e302_e305(tmp_path):
    sample = tmp_path / "models.py"
    sample.write_text(
        "class First:\n"
        "    def a(self):\n"
        "        return 1\n"
        "    def b(self):\n"
        "        return 2\n"
        "class Second:\n"
        "    pass\n"
        "# comentario colado\n"
        "def helper():\n"
        "    return 3\n"
        "VALUE = 42\n",
        encoding="utf-8",
    )

    audit = ac.run_audit(str(tmp_path), tools=("spacing",), use_registry=False)
    rules = {f["rule"] for f in audit["findings"]}
    assert {"E301", "E302", "E305"}.issubset(rules)

    report = ac.format_report(audit)
    assert "@audit fix" in report

    res = ac.fix_spacing(str(tmp_path), ["models.py"])
    assert len(res["fixed"]) == 1
    assert res["errors"] == []

    after = sample.read_text(encoding="utf-8")
    assert "return 1\n\n    def b(self):" in after
    assert "return 2\n\n\nclass Second:" in after
    assert "pass\n\n\n# comentario colado\ndef helper():" in after
    assert "return 3\n\n\nVALUE = 42" in after

    audit_after = ac.run_audit(str(tmp_path), tools=("spacing",), use_registry=False)
    assert audit_after["findings"] == []


def test_parse_audit_fix_command():
    assert ac.parse_command("@audit fix") == {"cmd": "fix", "incremental": False, "base": None, "paths": []}
    assert ac.parse_command("@audit fix diff") == {"cmd": "fix", "incremental": True, "base": None, "paths": []}
    assert ac.parse_command("@audit fix proxy_api/core/models.py") == {
        "cmd": "fix",
        "incremental": False,
        "base": None,
        "paths": ["proxy_api/core/models.py"],
    }

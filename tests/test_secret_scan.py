"""The pre-push secret scan finds keys, and the repo itself is clean.

Fake keys are built at run time so this file never contains a key-shaped string.
"""

from scripts.secret_scan import ROOT, scan


def test_finds_a_google_key_and_a_filled_env_example(tmp_path):
    fake = "AIza" + "x" * 35
    (tmp_path / "config.py").write_text(f'KEY = "{fake}"\n', encoding="utf-8")
    (tmp_path / ".env.example").write_text("GEMINI_API_KEY=" + "abc123" + "\n", encoding="utf-8")
    findings = scan(tmp_path, [tmp_path / "config.py", tmp_path / ".env.example"])
    assert any("Google API key" in f for f in findings)
    assert any("GEMINI_API_KEY has a value" in f for f in findings)


def test_flags_an_env_file_about_to_be_published(tmp_path):
    env = tmp_path / ".env"
    env.write_text("PROVIDER=gemini\n", encoding="utf-8")
    assert any("an .env file would be published" in f for f in scan(tmp_path, [env]))


def test_the_project_itself_is_clean():
    assert scan(ROOT) == []


def test_an_empty_key_followed_by_another_line_is_not_flagged(tmp_path):
    env = tmp_path / ".env.example"
    env.write_text("GEMINI_API_KEY=\nGEMINI_MODEL=gemini-3.6-flash\n", encoding="utf-8")
    assert scan(tmp_path, [env]) == []

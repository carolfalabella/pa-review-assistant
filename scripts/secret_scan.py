"""Check every file that git would publish for secrets, before pushing.

  python -m scripts.secret_scan

Uses `git ls-files` (tracked plus new, not ignored) when git is available, so it
checks exactly what a push would include. Without git it walks the folder and
skips the usual local-only paths. Exits with code 1 if anything is found.

A small, readable check, not a replacement for a dedicated scanner such as
gitleaks. It looks for:
- Google API keys, OpenAI-style keys, GitHub tokens, private key blocks
- an .env file (other than .env.example) about to be published
- KEY=value lines with a non-empty value in .env-style files
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PATTERNS = {
    "Google API key": re.compile(r"AIza[0-9A-Za-z_\-]{35}"),
    "OpenAI-style key": re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    "Private key block": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
}
# [ \t]* (not \s*) so an empty "KEY=" never reads on into the next line.
SECRET_ASSIGNMENT = re.compile(
    r"^[ \t]*([A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD)[A-Z0-9_]*)[ \t]*=[ \t]*([^\s#]+)", re.M)
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "runs", ".idea", ".vscode"}
BINARY_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".zip", ".pyc"}


def files_to_publish(root: Path) -> list[Path]:
    try:
        out = subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], cwd=root,
                             capture_output=True, text=True, check=True).stdout
        return [root / line for line in out.splitlines() if line.strip()]
    except (OSError, subprocess.CalledProcessError):
        found = []
        for path in root.rglob("*"):
            rel = path.relative_to(root)
            if path.is_file() and not (set(rel.parts) & SKIP_DIRS) and path.name != ".env":
                found.append(path)
        return found


def scan(root: Path, files: list[Path] | None = None) -> list[str]:
    findings = []
    for path in files if files is not None else files_to_publish(root):
        rel = path.relative_to(root).as_posix()
        if path.name == ".env" or (path.name.startswith(".env.") and path.name != ".env.example"):
            findings.append(f"{rel}: an .env file would be published")
        if path.suffix.lower() in BINARY_SUFFIXES or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for name, pattern in PATTERNS.items():
            for m in pattern.finditer(text):
                line = text.count("\n", 0, m.start()) + 1
                findings.append(f"{rel}:{line}: possible {name}")
        if path.name.startswith(".env"):
            for m in SECRET_ASSIGNMENT.finditer(text):
                line = text.count("\n", 0, m.start()) + 1
                findings.append(f"{rel}:{line}: {m.group(1)} has a value; .env.example must keep it blank")
    return findings


def main() -> int:
    files = files_to_publish(ROOT)
    findings = scan(ROOT, files)
    if findings:
        print("Possible secrets found. Do not push until these are fixed:")
        for f in findings:
            print(f"  {f}")
        return 1
    print(f"No secrets found in {len(files)} files that would be published.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

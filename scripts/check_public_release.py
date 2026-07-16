"""Fail fast when a proposed public release contains private or generated files."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAX_PUBLIC_FILE_BYTES = 10 * 1024 * 1024
FORBIDDEN_PARTS = {
    ".env", ".idea", ".pytest_cache", ".venv", "__pycache__", "node_modules",
    "outputs", "portfolio-site", "work", "dist", "build",
}
FORBIDDEN_PREFIXES = {("data", "raw"), ("data", "processed")}
TEXT_SUFFIXES = {
    "", ".py", ".md", ".txt", ".toml", ".yaml", ".yml", ".json", ".csv",
    ".ts", ".tsx", ".js", ".mjs", ".css", ".html", ".sh", ".example",
}
TOKEN_ASSIGNMENT = re.compile(
    r"(?im)^\s*(?:TUSHARE_TOKEN|TS_TOKEN|TUSHARE_API_TOKEN)\s*=\s*"
    r"(?P<value>[^#\s][^\r\n]*)$"
)


def git_candidates() -> list[Path] | None:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], cwd=ROOT, capture_output=True, text=True
    )
    if result.returncode:
        return None
    listed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT, capture_output=True, check=True,
    ).stdout
    return [ROOT / item.decode() for item in listed.split(b"\0") if item]


def filesystem_candidates() -> list[Path]:
    candidates: list[Path] = []
    for directory, names, files in os.walk(ROOT):
        relative = Path(directory).relative_to(ROOT)
        names[:] = [
            name for name in names
            if name not in FORBIDDEN_PARTS and name != ".git"
            and (relative.parts + (name,))[:2] not in FORBIDDEN_PREFIXES
        ]
        for file in files:
            relative_file = relative / file
            if file == ".env" or file.startswith(".env.") and file != ".env.example":
                continue
            if forbidden_reason(relative_file):
                continue
            candidates.append(Path(directory) / file)
    return candidates


def forbidden_reason(relative: Path) -> str | None:
    if relative.name == ".env" or any(part in FORBIDDEN_PARTS for part in relative.parts):
        return "private/generated path"
    if relative.parts[:2] in FORBIDDEN_PREFIXES:
        return "market-data cache"
    return None


def main() -> int:
    failures: list[str] = []
    candidates = git_candidates() or filesystem_candidates()
    for path in candidates:
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        reason = forbidden_reason(relative)
        if reason:
            failures.append(f"{relative}: {reason}")
            continue
        if path.stat().st_size > MAX_PUBLIC_FILE_BYTES:
            failures.append(f"{relative}: larger than 10 MB")
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for match in TOKEN_ASSIGNMENT.finditer(content):
            value = match.group("value").strip().strip('"\'')
            if value and value.lower() not in {"your_token_here", "replace_me", "example"}:
                failures.append(f"{relative}: non-placeholder Tushare token assignment")

    required = ["README.md", "LICENSE", "SECURITY.md", ".env.example", ".gitignore"]
    failures.extend(f"{name}: required release file missing" for name in required if not (ROOT / name).exists())

    if failures:
        print("Public release check FAILED:")
        for failure in sorted(set(failures)):
            print(f"- {failure}")
        return 1
    print(f"Public release check passed: {len(candidates)} candidate files, no private cache or token assignment found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

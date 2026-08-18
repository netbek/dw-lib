#!/usr/bin/env python
"""Apply GitHub Action ref updates from a Renovate report."""

from collections.abc import Generator
from pathlib import Path
from typing import Any

import json
import re
import sys

VERSION_RE = re.compile(r"^[vV]?(\d+)(?:\.(\d+))?(?:\.(\d+))?")
USES_RE = re.compile(
    r"^(?P<indent>\s*(?:-\s+)?)uses:\s*(?P<dep>[^\s@]+)@(?P<ref>\S+)(?P<comment>\s+#.*)?$"
)


def load_updates(report_path: Path) -> Generator[tuple[Any, Any, Any, Any], Any]:
    """Read proposed updates as (file, depName, update, dep) tuples."""
    data = json.loads(report_path.read_text())
    for repo in data.get("repositories", {}).values():
        for package_file in repo.get("packageFiles", {}).get("github-actions", []):
            file = package_file["packageFile"]
            for dep in package_file.get("deps", []):
                updates = dep.get("updates") or []
                if updates:
                    chosen = max(updates, key=lambda u: u.get("newVersion") or "")
                    yield (file, dep["depName"], chosen, dep)


def comment_version(update: dict, dep: dict) -> str | None:
    """Version text for a digest comment, in vX.Y.Z form."""
    version = update.get("newVersion") or dep.get("currentVersion") or update.get("newValue")
    if not version:
        return None
    match = VERSION_RE.match(str(version))
    if not match:
        return str(version)
    major, minor, patch = match.groups()
    return f"v{major}.{minor or 0}.{patch or 0}"


def new_ref(update: dict, dep: dict) -> tuple[str, str | None] | None:
    """Compute the ref to write, plus the version comment."""
    if update.get("newDigest"):
        return update["newDigest"], comment_version(update, dep)
    if update.get("newValue"):
        return update["newValue"], None
    return None


def apply_updates(path: Path, updates: list[tuple[str, str, dict, dict]]) -> bool:
    """Rewrite action refs in one workflow file."""
    lines = path.read_text().splitlines()
    changed = False
    for i, line in enumerate(lines):
        match = USES_RE.match(line)
        if not match:
            continue
        dep = match.group("dep")
        update = next(
            (
                (up, dep_dict)
                for file, dep_name, up, dep_dict in updates
                if file == str(path) and (dep == dep_name or dep.endswith("/" + dep_name))
            ),
            None,
        )
        if not update:
            continue
        ref = new_ref(*update)
        if not ref:
            continue
        new_ref_value, comment = ref
        comment_part = f" # {comment}" if comment else (match.group("comment") or "")
        lines[i] = f"{match.group('indent')}uses: {dep}@{new_ref_value}{comment_part}"
        changed = True
        print(f"  {path}: {dep}@{match.group('ref')} -> {dep}@{new_ref_value}")
    if changed:
        path.write_text("\n".join(lines) + "\n")
    return changed


def main() -> int:
    report_path = Path(sys.argv[1] if len(sys.argv) > 1 else "renovate-report.json")
    if not report_path.exists():
        print(f"Report not found: {report_path}", file=sys.stderr)
        return 1
    updates = list(load_updates(report_path))
    files = sorted({file for file, *_ in updates})
    any_changed = False
    for file in files:
        path = Path(file)
        if not path.exists():
            print(f"Skipping missing file: {file}", file=sys.stderr)
            continue
        any_changed = apply_updates(path, [up for up in updates if up[0] == file]) or any_changed
    if not any_changed:
        print("No updates to apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

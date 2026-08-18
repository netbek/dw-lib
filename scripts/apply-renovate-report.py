#!/usr/bin/env python3
"""Apply GitHub Action ref updates from a Renovate report."""

from pathlib import Path

import json
import re
import sys

USES_RE = re.compile(r"^(?P<indent>\s*)uses:\s*(?P<dep>[^\s@]+)@(?P<ref>\S+)(?P<comment>\s+#.*)?$")


def load_updates(report_path: Path) -> list[tuple[str, str, dict]]:
    """Read proposed updates as (file, depName, update) triples."""
    data = json.loads(report_path.read_text())
    for repo in data.get("repositories", {}).values():
        for package_file in repo.get("packageFiles", {}).get("github-actions", []):
            file = package_file["packageFile"]
            for dep in package_file.get("deps", []):
                updates = dep.get("updates") or []
                if updates:
                    yield (
                        file,
                        dep["depName"],
                        max(updates, key=lambda u: u.get("newVersion") or ""),
                    )


def new_ref(update: dict) -> tuple[str, str | None] | None:
    """Compute the ref to write, plus the version comment."""
    digest = update.get("newDigest")
    value = update.get("newValue")
    if digest:
        return digest, value or None
    if value:
        return value, None
    return None


def apply_updates(path: Path, updates: list[tuple[str, str, dict]]) -> bool:
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
                up
                for file, dep_name, up in updates
                if file == str(path) and (dep == dep_name or dep.endswith("/" + dep_name))
            ),
            None,
        )
        if not update:
            continue
        ref = new_ref(update)
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
    files = sorted({file for file, _, _ in updates})
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

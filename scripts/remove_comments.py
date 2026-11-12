#!/usr/bin/env python3
"""
tools/remove_comments.py (or scripts/remove_comments.py)
-------------------------------------------------------
Removes all comments from Python files in the project.

Features:
- Preserves shebang lines (#!/usr/bin/env python3)
- Preserves strings and docstrings containing '#' characters
- Preserves syntactical correctness and clean code formatting
- Supports --dry-run (preview), --backup (save .bak), and --restore
- Can target individual files, directories, or the entire codebase
"""

import argparse
import ast
import io
import os
import sys
import tokenize
from pathlib import Path
from typing import List, Tuple

# Default target directories relative to project root
DEFAULT_TARGETS = [
    "agent",
    "common",
    "server",
    "sdn",
    "experiments",
    "demo.py",
]

def strip_comments_from_source(source: str, keep_shebang: bool = True) -> str:
    """
    Remove all Python comments from source code string while:
    1. Preserving shebangs on line 1.
    2. Preserving '#' inside string literals and docstrings.
    3. Preserving indentation and line syntax.
    """
    tokens = list(tokenize.tokenize(io.BytesIO(source.encode("utf-8")).readline))
    lines = source.splitlines(keepends=True)
    lines_list = list(lines)

    # Filter comment tokens
    comments = [t for t in tokens if t.type == tokenize.COMMENT]
    # Reverse sort to delete from bottom-to-top and right-to-left
    comments.sort(key=lambda t: (t.start[0], t.start[1]), reverse=True)

    for c in comments:
        row, col = c.start[0] - 1, c.start[1]
        line = lines_list[row]

        # Preserve shebang on line 1 if requested
        if row == 0 and keep_shebang and line.startswith("#!"):
            continue

        prefix = line[:col].rstrip()
        if prefix:
            # Inline comment: retain prefix and preserve line ending
            lines_list[row] = prefix + ("\n" if line.endswith("\n") else "")
        else:
            # Full line comment: mark line for removal
            lines_list[row] = None

    # Reconstruct cleaned source with clean whitespace
    result_lines = []
    blank_count = 0
    for line in lines_list:
        if line is None:
            continue
        if line.strip() == "":
            blank_count += 1
            if blank_count <= 2:  # allow at most 2 consecutive blank lines
                result_lines.append(line)
        else:
            blank_count = 0
            result_lines.append(line)

    return "".join(result_lines)

def process_file(file_path: Path, dry_run: bool = False, backup: bool = False) -> Tuple[bool, int, int]:
    """
    Process a single Python file to strip comments.
    Returns (success, original_lines, new_lines).
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            original = f.read()
    except Exception as e:
        print(f"[ERROR] Could not read {file_path}: {e}")
        return False, 0, 0

    try:
        cleaned = strip_comments_from_source(original)
        # Verify valid Python syntax
        ast.parse(cleaned)
    except Exception as e:
        print(f"[FAIL] AST parse error after stripping comments in {file_path}: {e}")
        return False, 0, 0

    orig_len = len(original.splitlines())
    clean_len = len(cleaned.splitlines())

    if dry_run:
        print(f"[DRY-RUN] {file_path}: {orig_len} -> {clean_len} lines (diff: -{orig_len - clean_len})")
        return True, orig_len, clean_len

    if backup:
        bak_path = file_path.with_suffix(file_path.suffix + ".bak")
        with open(bak_path, "w", encoding="utf-8") as f:
            f.write(original)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(cleaned)

    print(f"[CLEANED] {file_path}: {orig_len} -> {clean_len} lines (diff: -{orig_len - clean_len})")
    return True, orig_len, clean_len

def restore_backups(root_dir: Path):
    """Restore all .bak files found in project."""
    count = 0
    for bak in root_dir.rglob("*.py.bak"):
        orig = bak.with_suffix("")
        bak.replace(orig)
        count += 1
        print(f"[RESTORED] {orig}")
    print(f"Restored {count} backup files.")

def collect_py_files(root_dir: Path, targets: List[str]) -> List[Path]:
    """Collect all target python files."""
    files = []
    for target in targets:
        p = root_dir / target
        if p.is_file() and p.suffix == ".py":
            files.append(p)
        elif p.is_dir():
            for py in sorted(p.rglob("*.py")):
                if not any(part.startswith(".") for part in py.parts) and "__pycache__" not in py.parts:
                    files.append(py)
    return sorted(list(set(files)))

def main():
    parser = argparse.ArgumentParser(description="Remove all comments from Python programs in the project.")
    parser.add_argument("--dry-run", action="store_true", help="Preview line changes without modifying files.")
    parser.add_argument("--backup", action="store_true", help="Create .bak backups before stripping comments.")
    parser.add_argument("--restore", action="store_true", help="Restore .bak backup files.")
    parser.add_argument("--all", action="store_true", help="Include tests/ directory in targets.")
    parser.add_argument("paths", nargs="*", help="Optional specific files or directories to process.")

    args = parser.parse_args()
    project_root = Path(__file__).resolve().parent.parent

    if args.restore:
        restore_backups(project_root)
        return

    targets = args.paths if args.paths else list(DEFAULT_TARGETS)
    if args.all and "tests" not in targets:
        targets.append("tests")

    py_files = collect_py_files(project_root, targets)
    if not py_files:
        print("[WARN] No Python files matched targets.")
        return

    print(f"Found {len(py_files)} Python file(s) to process in {project_root}...")
    total_orig = 0
    total_clean = 0
    success_count = 0

    for py_file in py_files:
        success, orig_lines, clean_lines = process_file(py_file, dry_run=args.dry_run, backup=args.backup)
        if success:
            success_count += 1
            total_orig += orig_lines
            total_clean += clean_lines

    print("-" * 60)
    mode = "DRY-RUN COMPLETE" if args.dry_run else "STRIPPING COMPLETE"
    print(f"{mode}: Processed {success_count}/{len(py_files)} files.")
    print(f"Total lines: {total_orig} -> {total_clean} (Removed {total_orig - total_clean} comment/empty lines).")

if __name__ == "__main__":
    main()

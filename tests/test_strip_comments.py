import pytest
import io
import ast
import tempfile
from pathlib import Path
from scripts.remove_comments import strip_comments_from_source, process_file

def test_strip_comments_basic():
    sample = """#!/usr/bin/env python3
# Top level comment
x = 10  # Inline comment
# Middle comment
name = "Node #1"  # Hash in string should be preserved
def foo():
    # Function comment
    return x * 2
"""
    cleaned = strip_comments_from_source(sample)
    assert "# Top level comment" not in cleaned
    assert "# Middle comment" not in cleaned
    assert "# Function comment" not in cleaned
    assert "# Inline comment" not in cleaned
    assert 'name = "Node #1"' in cleaned
    assert "x = 10" in cleaned
    assert "def foo():" in cleaned
    assert cleaned.startswith("#!/usr/bin/env python3")
    ast.parse(cleaned)

def test_process_file_dry_run_and_backup(tmp_path):
    test_file = tmp_path / "sample.py"
    test_file.write_text("""# Initial comment
a = 1  # inline
b = 2
""")
    success, orig, clean = process_file(test_file, dry_run=True)
    assert success
    assert orig == 3
    assert clean == 2
    # File should not be modified in dry run
    assert "# Initial comment" in test_file.read_text()

    # Real run with backup
    success, orig, clean = process_file(test_file, dry_run=False, backup=True)
    assert success
    assert test_file.with_suffix(".py.bak").exists()
    content = test_file.read_text()
    assert "# Initial comment" not in content
    assert "a = 1" in content

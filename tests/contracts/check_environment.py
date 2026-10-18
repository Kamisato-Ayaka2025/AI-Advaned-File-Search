"""Reproducible syntax/import probe; not Python 3.11 runtime or network audit proof."""
import ast
import importlib
from pathlib import Path
import socket
import sys

root = Path(__file__).resolve().parents[2]
paths = list((root / "src/original_words/contracts").glob("*.py"))
paths += list((root / "tests/contracts").glob("*.py"))
for path in paths:
    ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path), feature_version=(3, 11))
print(f"Python 3.11 grammar: {len(paths)} files passed (not runtime proof)")


def blocked(*args, **kwargs):
    raise AssertionError("Network is forbidden during contract import")


socket.socket = blocked
socket.create_connection = blocked
sys.path.insert(0, str(root / "src"))
for path in (root / "src/original_words/contracts").glob("*.py"):
    if path.stem != "__init__":
        importlib.import_module("original_words.contracts." + path.stem)
print("Isolated stdlib-only imports passed with socket access blocked")

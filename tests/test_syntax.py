"""Alla Python-filer ska gå att kompilera (fångar syntaxfel innan en bild byggs och rullas ut)."""
import py_compile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FILES = sorted(p for d in ("smartbox", "ewapp", "smartdashboard", "webdashboard") for p in (ROOT / d).glob("*.py"))


@pytest.mark.parametrize("fil", FILES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_kompilerar(fil):
    py_compile.compile(str(fil), doraise=True)

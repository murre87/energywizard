"""Appens fit(): alla krympsteg tas bort före omräkningen. t5 saknades, så när sidan en gång blivit för full satt
t5 kvar - "Just nu"-raderna doldes och flödesdiagrammet krympte till en liten ruta med tomma sidor (2026-11-14)."""
import os
import re


def test_fit_tar_bort_alla_steg():
    js = open(os.path.join(os.path.dirname(__file__), "..", "ewapp", "static", "app.js"), encoding="utf-8").read()
    body = js[js.index("function fit()"):]
    body = body[:body.index("\n}\n")]
    removed = set(re.findall(r'"(t\d)"', re.search(r"classList\.remove\(([^)]*)\)", body).group(1)))
    added = int(re.search(r"l <= (\d)", body).group(1))
    assert removed == {f"t{i}" for i in range(1, added + 1)}

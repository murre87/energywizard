"""Översättningsmallar: den mest specifika (mest fast text) går före en allmän som också matchar - i både
i18n_py.py och i18n.js. Förut vann katalogordningen, så "beställt paus, uppmätt 0 A" blev "objednáno paus"."""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "smartbox"))

import i18n_py

ROOT = os.path.join(os.path.dirname(__file__), "..")


def test_python_specifik_mall_först():
    assert i18n_py.tr("beställt paus, uppmätt 0 A", "cs") == "objednáno pauza, změřeno 0 A"
    assert i18n_py.tr("beställt 9 A, uppmätt 8 A", "cs") == "objednáno 9 A, změřeno 8 A"


def test_js_samma_ordning():
    js = open(os.path.join(ROOT, "smartbox", "i18n", "i18n.js"), encoding="utf-8").read()
    assert "templates.sort((a, b) => b[3] - a[3]);" in js
    node = subprocess.run(["node", "-e", """
      const keys = ["beställt {o}, uppmätt {a}", "beställt paus, uppmätt {a}"];
      const lit = (k) => k.replace(/\\{([a-z][a-z0-9_]*)\\}/gi, "").length;
      const s = keys.map((k, i) => [k, lit(k), i]).sort((a, b) => b[1] - a[1]);
      console.log(s[0][0]);"""], capture_output=True, text=True)
    assert node.stdout.strip() == "beställt paus, uppmätt {a}"

"""Hälsningen ("God morgon, Emil") och "Data 16 h gammal" stod på svenska i tjeckisk vy (2026-11-14)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "smartbox"))

import i18n_py


def test_hälsning_med_namn():
    assert i18n_py.tr("God morgon, Emil!", "cs") == "Dobré ráno, Emil!"
    assert i18n_py.tr("God kväll, Elin", "en") == "Good evening, Elin"


def test_hälsning_utan_namn():
    assert i18n_py.tr("God kväll, du!", "cs") == "Dobrý večer!"
    assert i18n_py.tr("Hej, gäst", "en") == "Hello, guest"


def test_gammal_data():
    assert i18n_py.tr("Data 16 h gammal", "cs") == "Data stará 16 h"
    assert i18n_py.tr("Data 3 dygn gammal", "en") == "Data 3 days old"
    assert i18n_py.tr("Data 40 min gammal", "cs") == "Data stará 40 min"

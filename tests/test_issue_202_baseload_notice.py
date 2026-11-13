"""#202: brödtexten i aviseringen om onormal baslast stod kvar på svenska ("Huset drar 4.5 kW.")."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "smartbox"))

import i18n_py


def test_baslast_brodtext_oversatt():
    assert i18n_py.tr("Huset drar 4.5 kW.", "en") == "The house is using 4.5 kW."
    assert i18n_py.tr("Huset drar 4.5 kW.", "cs") == "Dům odebírá 4.5 kW."
    assert i18n_py.tr("🚨 Onormal Baslast Upptäckt!", "en") == "🚨 Abnormal base load detected!"

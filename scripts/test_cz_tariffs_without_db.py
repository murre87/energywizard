"""Run price arithmetic/adapter tests without installing PostgreSQL client packages.

Only unused DB/network imports are stubbed; all tariff and parser code is real.
Run the same tests normally under pytest in the complete upstream environment.
"""
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / 'smartbox'), str(ROOT / 'tests')]
for name in ('requests', 'psycopg'):
    try:
        __import__(name)
    except ImportError:
        sys.modules[name] = types.ModuleType(name)
# The arithmetic tests never access the price database.
logger = types.ModuleType('logger')
def no_database(*args, **kwargs):
    raise AssertionError('Unexpected database access in isolated tariff tests')
logger.get_db = no_database
sys.modules['logger'] = logger
suite = unittest.defaultTestLoader.loadTestsFromName('test_cz_tariffs')
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(not result.wasSuccessful())

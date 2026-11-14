"""Smoke test: the toolchain (yosys + sby + bitwuzla) works.

tests/conftest.py is not above this directory, so the sby fixture is loaded
from it by file path under its own module name (not via a second conftest.py,
so that the 'conftest' module name does not clash).
"""
import importlib.util
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent

_spec = importlib.util.spec_from_file_location(
    'uf_tests_common', HERE.parent / 'tests' / 'conftest.py')
_common = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_common)
sby = _common.sby


@pytest.mark.parametrize('task', ['bmc', 'prove'])
def test_counter(sby, task):
    r = sby(HERE, 'counter.sby', task)
    assert r.status == 'PASS', r.log[-3000:]

"""Effect of the UF argument and return value width on the BMC time.

Question: does widening the argument or the return value of a UF (e.g. from
10 to 110 bits) cost the solver anything? The measured grid is in the
docstring of scaling.py.

Default run: small points (depth 10), correctness (PASS / BAD -> FAIL) and the
UF signature. Run times are not checked (the load varies); measurements are
made with the driver scaling.py (grid).

validation: PASS/FAIL results of the whole grid (tens of seconds to minutes
per point).
"""
import re

import pytest

import scaling


def run(tmp_path, *pt, timeout=600):
    st, _, log = scaling.run_point(tmp_path, *pt, timeout=timeout)
    return st, log


def model(tmp_path, *pt):
    return (tmp_path / scaling.point_name(*pt) / 'w' / 'model' / 'design_smt2.smt2').read_text()


@pytest.mark.parametrize('wi,wo', [(10, 10), (110, 10), (10, 110), (4, 4)])
def test_uf_pass(tmp_path, wi, wo):
    pt = ('uf', wi, wo, 10, 'bitwuzla', False)
    st, log = run(tmp_path, *pt)
    assert st == 'PASS', log[-3000:]
    smt = model(tmp_path, *pt)
    # box is one UF (a, b) -> y; stim CW=16 -> WI. The box module's own
    # definition (bvmul) stays in the model unused; chan/top must not refer to it.
    assert re.search(rf'^\(declare-fun \|mul\| \(\(_ BitVec {wi}\) \(_ BitVec {wi}\)\) '
                     rf'\(_ BitVec {wo}\)\)', smt, flags=re.M), smt[:2000]
    assert re.search(rf'^\(declare-fun \|stim\| \(\(_ BitVec 16\)\) \(_ BitVec {wi}\)\)',
                     smt, flags=re.M)
    secs = re.split(r'^; yosys-smt2-module ', smt, flags=re.M)[1:]
    users = [x for x in secs if x.split('\n', 1)[0].endswith(('/chan', 'top'))]
    assert len(users) == 2, [x.split('\n', 1)[0] for x in secs]
    for x in users:
        assert 'bvmul' not in x and '/box_h' not in x and '/box_s' not in x


@pytest.mark.parametrize('wi,wo', [(10, 10), (110, 10), (10, 110)])
def test_uf_bad_fails(tmp_path, wi, wo):
    st, log = run(tmp_path, 'uf', wi, wo, 10, 'bitwuzla', True)
    assert st == 'FAIL', log[-3000:]
    assert 'a_match' in log


def test_nouf_small(tmp_path):
    """Interpreted multiplication (W=4): PASS, BAD -> FAIL, bvmul in the model, mul not a UF."""
    pt = ('nouf', 4, 4, 10, 'bitwuzla', False)
    st, log = run(tmp_path, *pt)
    assert st == 'PASS', log[-3000:]
    smt = model(tmp_path, *pt)
    assert 'bvmul' in smt
    assert 'declare-fun |mul|' not in smt
    st, log = run(tmp_path, 'nouf', 4, 4, 10, 'bitwuzla', True)
    assert st == 'FAIL', log[-3000:]


@pytest.mark.parametrize('mode,val', [('uf', 1), ('nouf', 0)])
def test_sby_text_uses_param(mode, val):
    """The mode is selected with the parameter UF_MODE (chparam only gives the
    value); the sby neither removes nor sets marks, and the guard checks the
    uf_disable value."""
    for bad in (False, True):
        t = scaling.sby_text(mode, 10, 10, 10, bad=bad)
        assert 'setattr' not in t, t
        assert f'-set UF_MODE {val} top' in t, t
        assert f"a:uf_disable=1'{1 - val} %i" in t, t


def test_yices_reference(tmp_path):
    st, log = run(tmp_path, 'uf', 110, 10, 10, 'yices', False)
    assert st == 'PASS', log[-3000:]


# Grid points that finished in under 300 s in the measurements.
VALIDATION = [pt for pt in scaling.grid('all') if pt[3] <= 20 and not (pt[0] == 'nouf' and pt[1] == 32)]


@pytest.mark.validation
@pytest.mark.parametrize('pt', VALIDATION, ids=[scaling.point_name(*p) for p in VALIDATION])
def test_grid_point(tmp_path, pt):
    st, log = run(tmp_path, *pt, timeout=1800)
    assert st == ('FAIL' if pt[5] else 'PASS'), log[-3000:]

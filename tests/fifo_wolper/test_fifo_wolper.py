"""fifo_wolper: Wolper checker (two symbolic values) for the same FIFO.

Checkers (axis_fifo_wolper.sby):
- wolper: anyconst k, a, b; input a on beat k, otherwise b; assertion
  m_data = (a when ocnt = k, otherwise b). BMC depth 2*DEPTH+6 as in
  fifo_checkers.
- prove_wolper: the same as k-induction with auxiliary invariants
  (tb_axis_fifo_wolper_formal_inv.psl; DUT internal state through probes).
- uf, sb: the UF checker and a traditional shadow-queue scoreboard, for the
  timing comparison (compare.py).

The mutations are the same as in fifo_checkers/test_fifo_checkers.py
(imported from there, not copied), so the checkers face the same set of
mutants. Parameters: the line "D, W = 4, 8" in both pycode blocks of the sby
file is replaced in a copy; the sources are never touched.
"""
import importlib.util
import re
import shutil
from pathlib import Path

import pytest

from conftest import (_ignore_subdirs, cover_steps, failed_asserts,
                      insert_before_arch_end, run_sby, sby_model, uf_decls)

HERE = Path(__file__).resolve().parent
SBY = 'axis_fifo_wolper.sby'
PARAM_LINE = 'D, W = 4, 8'
TB = 'tb_axis_fifo_wolper_formal.vhdl'
INV = 'tb_axis_fifo_wolper_formal_inv.psl'

_spec = importlib.util.spec_from_file_location(
    'fifo_checkers_mutations', HERE.parent / 'fifo_checkers' / 'test_fifo_checkers.py')
_fc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fc)
MUTATIONS = _fc.MUTATIONS
CTRL_ASSERTS = _fc.CTRL_ASSERTS

GRID = [(d, w) for d in (2, 3, 4) for w in (8, 32)]
GRID_SLOW = [(8, 8), (8, 32)]
PROVE_GRID = [(d, w) for d in (2, 3, 4, 8) for w in (8, 32)]
PROVE_SLOW = [(16, 8), (16, 110)]


def _params(grid, marks=()):
    return [pytest.param(d, w, id=f'D{d}-W{w}', marks=marks) for d, w in grid]


def bmc_depth(depth):
    return 2 * depth + 6


def param_copy(dst, depth, width, edits=None, cover=False):
    """Copy the sources to dst and set the parameters; edits as in test_fifo_checkers."""
    dst = Path(dst)
    shutil.copytree(HERE, dst, dirs_exist_ok=True, ignore=_ignore_subdirs)
    sby = dst / SBY
    t = sby.read_text()
    assert t.count(PARAM_LINE) == 2, t.count(PARAM_LINE)
    t = t.replace(PARAM_LINE, f'D, W = {depth}, {width}')
    if cover:
        assert t.count('bmc: mode bmc') == 1
        t = t.replace('bmc: mode bmc', 'bmc: mode cover')
    sby.write_text(t)
    for f, pairs in (edits or {}).items():
        p = dst / f
        txt = p.read_text()
        for old, new in pairs:
            assert txt.count(old) == 1, (f, old, txt.count(old))
            txt = txt.replace(old, new)
        p.write_text(txt)
    return dst


def _run(tmp_path, task, depth, width, edits=None, cover=False):
    src = param_copy(tmp_path / 'param' / 'fifo_wolper', depth, width, edits, cover)
    return run_sby(src, SBY, task, tmp_path)


def _fail_names(r):
    return [re.sub(r'.*\.', '', n) for n in failed_asserts(r.log)]


# ---------------------------------------------------------------- BMC and prove

@pytest.mark.parametrize('depth,width', _params(GRID) + _params(GRID_SLOW, pytest.mark.slow))
def test_bmc(tmp_path, depth, width):
    """Correct FIFO: Wolper checker PASS; the model has no UF declarations."""
    r = _run(tmp_path, 'wolper', depth, width)
    assert r.status == 'PASS', r.log[-3000:]
    assert uf_decls(sby_model(r, 'axis_fifo_wolper_wolper')) == {}


@pytest.mark.parametrize('depth,width',
                         _params(PROVE_GRID) + _params(PROVE_SLOW, pytest.mark.slow))
def test_prove(tmp_path, depth, width):
    """k-induction: the Wolper assertion and the auxiliary invariants are proven unbounded."""
    r = _run(tmp_path, 'prove_wolper', depth, width)
    assert r.status == 'PASS', r.log[-3000:]
    assert 'Status returned by engine for induction: pass' in r.log, r.log[-3000:]


def test_prove_probe_guard(tmp_path):
    """An unconnected probe (p_count) would stay free: the sby script's guard stops the run."""
    edits = {SBY: [('    output("connect -set tb_axis_fifo_wolper_formal_inv.p_count dut.count")\n',
                    '')]}
    r = _run(tmp_path, 'prove_wolper', 3, 8, edits=edits)
    assert r.status == 'ERROR', r.log[-3000:]
    assert 'select -assert-none' in r.log or 'Assertion failed' in r.log, r.log[-3000:]


# Removing an invariant: condition -> false (inv_mem: a cover, so that the
# probe p_mem and its connection stay in the model). A removed invariant
# breaks the induction (UNKNOWN). DEPTH=3: the pointers have the unused value
# 3, so a_inv_range is needed.
INVARIANTS = ('range', 'count', 'wr', 'mem')


def _drop_invariant(name):
    if name == 'mem':
        return {INV: [("    a_inv_mem : assert always\n        (started = '1') -> (mem_ok = '1');",
                       "    a_inv_mem : cover {started = '1' and mem_ok = '1'};")]}
    return {INV: [(f"    a_inv_{name} : assert always\n        (",
                   f"    a_inv_{name} : assert always\n        (false and ")]}


@pytest.mark.parametrize('inv', INVARIANTS)
def test_prove_invariant_needed(tmp_path, inv):
    """Every auxiliary invariant is needed: without it the induction does not go through."""
    r = _run(tmp_path, 'prove_wolper', 3, 8, edits=_drop_invariant(inv))
    assert r.status == 'UNKNOWN', r.log[-3000:]
    assert 'Status returned by engine for basecase: pass' in r.log, r.log[-3000:]
    assert 'Status returned by engine for induction: FAIL' in r.log, r.log[-3000:]


def test_prove_k1(tmp_path):
    """The smallest working induction depth is 1 (PROVE_K = 2 in sby = 1 + margin)."""
    edits = {SBY: [('PROVE_K = 2', 'PROVE_K = 1')]}
    r = _run(tmp_path, 'prove_wolper', 3, 8, edits=edits)
    assert r.status == 'PASS', r.log[-3000:]


# ---------------------------------------------------------------- vacuity

def _cover_text(depth):
    return ("    c_full_drained : cover {rst_in = '0' and was_full = '1' and "
            f"icnt = ocnt and ocnt >= {depth + 1}}};\n")


NEVER_READY = "    v_never_ready : assume always m_ready_in = '0';\n"
# The tracked beat k comes out (the check of value a really happens).
COVER_K_OUT = ("    c_k_out : cover {rst_in = '0' and m_valid = '1' and m_ready_in = '1' "
               "and ocnt = k and a /= b};\n")


def _cover(tmp_path, depth, width, text):
    src = param_copy(tmp_path / 'param' / 'fifo_wolper', depth, width, cover=True)
    p = src / TB
    p.write_text(insert_before_arch_end(p.read_text(), text))
    return run_sby(src, SBY, 'wolper', tmp_path)


@pytest.mark.parametrize('depth,width', _params(GRID))
def test_vacuity_cover(tmp_path, depth, width):
    """The FIFO fills and drains within the horizon; the tracked beat k comes out."""
    r = _cover(tmp_path, depth, width, _cover_text(depth) + COVER_K_OUT)
    assert r.status == 'PASS', r.log[-3000:]
    steps = cover_steps(r.log)
    assert len(steps) == 2 and 'Unreached cover' not in r.log, r.log[-3000:]
    assert max(steps) == 2 * depth + 2, steps


@pytest.mark.parametrize('depth,width', _params(GRID))
def test_vacuity_sensitivity(tmp_path, depth, width):
    """Contradictory assumption (m_ready always low) -> cover unreachable."""
    r = _cover(tmp_path, depth, width, _cover_text(depth) + NEVER_READY)
    assert r.status == 'FAIL', r.log[-3000:]
    assert 'Unreached cover statement' in r.log, r.log[-3000:]
    assert cover_steps(r.log) == []


# ---------------------------------------------------------------- mutations
#
# The same mutations as in test_fifo_checkers.py (D4-W8). full: all
# assertions; the expected failing assertions are as with the UF checker.
# data: control assertions disabled; the Wolper data assertion alone.

EXPECT_FULL = {m: {'a_wolper_match'} for m in MUTATIONS}
EXPECT_FULL['overflow'] = {'a_no_overflow'}
EXPECT_FULL['never_ready'] = {'a_ready_not_full'}
EXPECT_FULL['wr_wrap_early'] = {'a_wolper_match', 'a_m_data_stable'}

# Data mode: never_ready is left out, because with no transfers the data
# assertion has nothing to check; a_ready_not_full catches it in full mode.
DATA_MUTATIONS = [m for m in MUTATIONS if m != 'never_ready']


def _disable_ctrl_asserts(dst):
    p = dst / 'tb_axis_ctrl_formal.vhdl'
    t, n = re.subn(r'(a_(?:occ_max|no_underflow|no_overflow|ready_not_full|valid_not_empty'
                   r'|m_valid_hold|m_data_stable)'
                   r' : assert always\n\s+\()', r'\1false and ', p.read_text())
    assert n == len(CTRL_ASSERTS), n
    p.write_text(t)


def _mut(tmp_path, task, mut, data_only=False):
    src = param_copy(tmp_path / 'param' / 'fifo_wolper', 4, 8, MUTATIONS[mut])
    if data_only:
        _disable_ctrl_asserts(src)
    return run_sby(src, SBY, task, tmp_path)


@pytest.mark.parametrize('mut', list(MUTATIONS))
def test_mutation_fails(tmp_path, mut):
    """A mutation fails with the Wolper checker on the expected assertion (D4-W8)."""
    r = _mut(tmp_path, 'wolper', mut)
    assert r.status == 'FAIL', r.log[-3000:]
    assert EXPECT_FULL[mut] & set(_fail_names(r)), (_fail_names(r), r.log[-3000:])
    assert (r.workdir / 'axis_fifo_wolper_wolper' / 'engine_0' / 'trace.vcd').exists()


@pytest.mark.parametrize('mut', DATA_MUTATIONS)
def test_mutation_data_only(tmp_path, mut):
    """Control assertions disabled: a_wolper_match alone fails."""
    r = _mut(tmp_path, 'wolper', mut, data_only=True)
    assert r.status == 'FAIL', r.log[-3000:]
    assert _fail_names(r) == ['a_wolper_match'], (_fail_names(r), r.log[-3000:])


# The prove task's probes connect to the DUT signals count, rd, wr and mem.
# Mutations that fold these into constants (dup_beat: rd never advances;
# never_ready: s_ready = 0 makes mem and wr dead) or change the memory
# structure (stale_capture) are covered by the BMC task instead
# (test_mutation_fails).
PROVE_MUTATIONS = [m for m in MUTATIONS if m not in ('dup_beat', 'stale_capture', 'never_ready')]


@pytest.mark.parametrize('mut', PROVE_MUTATIONS)
def test_mutation_prove_not_pass(tmp_path, mut):
    """prove_wolper does not prove a mutant: the basecase fails or the induction does not go through."""
    r = _mut(tmp_path, 'prove_wolper', mut)
    assert r.status in ('FAIL', 'UNKNOWN'), r.log[-3000:]


def test_data_only_correct_passes(tmp_path):
    """Disabling the control assertions does not by itself fail a correct FIFO."""
    src = param_copy(tmp_path / 'param' / 'fifo_wolper', 2, 8)
    _disable_ctrl_asserts(src)
    r = run_sby(src, SBY, 'wolper', tmp_path)
    assert r.status == 'PASS', r.log[-3000:]


_RESET_FIRST_ONLY = {'tb_axis_ctrl_formal.vhdl': [(
    "        (first = '1') -> (rst_in = '1');",
    "        (first = '1') = (rst_in = '1');")]}


def test_stale_capture_without_midrun_reset(tmp_path):
    """stale_capture is caught without a reset in the middle of the run (s_data_idle_in)."""
    edits = {**MUTATIONS['stale_capture'], **_RESET_FIRST_ONLY}
    src = param_copy(tmp_path / 'param' / 'fifo_wolper', 4, 8, edits)
    r = run_sby(src, SBY, 'wolper', tmp_path)
    assert r.status == 'FAIL', r.log[-3000:]
    assert 'a_wolper_match' in _fail_names(r), (_fail_names(r), r.log[-3000:])

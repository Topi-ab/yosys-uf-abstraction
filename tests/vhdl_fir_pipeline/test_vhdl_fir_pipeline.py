"""vhdl_fir_pipeline: pipelined complex FIR; data does not depend on control
AND control does not depend on data, in two handshake styles (SKID false/true).

Two properties of the same DUT (fir_complex_pipe.vhdl):
- data (tb_fir_pipe_data_formal.vhdl): channel A at full rate ties out_f
  (a_define); channel B with free s_valid/m_ready sequences is checked
  (a_match, symbolic beat index j), and the stability of B's m-side stall is
  checked (a_m_stable_b). Bounded progress of B (a_prog_m_b, a_prog_s_b): a
  DUT that deadlocks or loses beats fails.
- ctrl (tb_fir_pipe_ctrl_formal.vhdl): instances C and D with the same
  control inputs and independent free data; assertions a_s_ready_eq and
  a_m_valid_eq (non-interference).

The parameters (TAPS, WIDTH) are given to GHDL as top-level generic overrides
in a copied sby file; the TAPS-dependent guard counts and depths are replaced
at the same time. The handshake style is in the task name (_comb/_skid). The
sources are not touched.
"""
import re
import shutil
from pathlib import Path

import pytest

from conftest import (SMT2_CELL_RE, _ignore_subdirs, cover_steps, failed_asserts, run_cover,
                      run_sby, sby_model, sby_script, smt2_module_sections, uf_decls)

HERE = Path(__file__).resolve().parent
SBY = 'fir_complex_pipe.sby'
PFX = 'fir_complex_pipe'

DEFAULT = (5, 8)
# Mutations and assumption-necessity tests: the smallest grid point (data_bmc is heavy).
MUT_P = (3, 8)
GRID = [(t, w) for t in (3, 5) for w in (8, 16)]
STYLES = ['comb', 'skid']

DATA_SOURCES = ['fir_complex_pipe_pkg.vhdl', 'cmul.vhdl', 'cadd.vhdl', 'fir_complex_pipe.vhdl',
                'tb_fir_pipe_stim_formal.vhdl', 'tb_fir_pipe_out_formal.vhdl',
                'tb_fir_pipe_data_formal.vhdl']
INV_SOURCES = ['fir_pipe_ref.vhdl', 'fir_complex_pipe_inv.psl', 'tb_fir_pipe_data_formal_inv.psl']
CTRL_SOURCES = ['fir_complex_pipe_pkg.vhdl', 'cmul.vhdl', 'cadd.vhdl', 'fir_complex_pipe.vhdl',
                'tb_fir_pipe_ctrl_formal.vhdl']
CTRL_INV = 'tb_fir_pipe_ctrl_formal_inv.psl'
DUT_INV = 'fir_complex_pipe_inv.psl'
DATA_INV = 'tb_fir_pipe_data_formal_inv.psl'
DATA_TB = 'tb_fir_pipe_data_formal.vhdl'
CTRL_TB = 'tb_fir_pipe_ctrl_formal.vhdl'
DUT = 'fir_complex_pipe.vhdl'


def _task_tags():
    """[tasks] lines of the sby file: task -> tags."""
    out, on = {}, False
    for line in (HERE / SBY).read_text().splitlines():
        if line.startswith('['):
            on = line.strip() == '[tasks]'
            continue
        if on and line.strip() and not line.startswith('#'):
            name, *tags = line.split()
            out[name] = set(tags)
    return out


TASK_TAGS = _task_tags()

DUT_INVARIANTS = ['inv_dl', 'inv_mn', 'inv_sk']
TB_INVARIANTS = ['inv_live', 'inv_cnt_a', 'inv_cnt_b', 'inv_hist_a', 'inv_hist_b', 'inv_a_full',
                 'inv_ent', 'inv_order', 'inv_bound', 'inv_prog_m', 'inv_prog_s']
PROG_ASSERTS = {'a_prog_m_b', 'a_prog_s_b'}
DATA_ASSERTS = {'a_match', 'a_m_stable_b'} | PROG_ASSERTS
PROVE_ASSERTS = (DATA_ASSERTS
                 | {f'tb_fir_pipe_data_formal_inv.{n}' for n in TB_INVARIANTS}
                 | {f'fir_complex_pipe_inv.{n}' for n in DUT_INVARIANTS})
CTRL_ASSERTS = {'a_s_ready_eq', 'a_m_valid_eq'}
CTRL_PROVE_ASSERTS = CTRL_ASSERTS | {'tb_fir_pipe_ctrl_formal_inv.inv_v_eq'}
ASSERT_RE = re.compile(r'^; yosys-smt2-assert \d+ (\S+)', flags=re.M)


def clog2(n):
    return (n - 1).bit_length()


def depth_of(taps):
    """Number of pipeline stages D = clog2(TAPS) + 2."""
    return clog2(taps) + 2


def hist_len(taps):
    return 2 * depth_of(taps) + taps - 1


def bmc_depth(taps):
    """data_bmc depth: the vacuity cover (D+2 beats on both channels, bubbles
    and back pressure) is reached at step 2*D+4, plus a margin of 2."""
    return 2 * depth_of(taps) + 6


def prod_width(w):
    return 2 * w + 1


def out_width(taps, w):
    return prod_width(w) + clog2(taps)


# ---------------------------------------------------------------- parametrisation

def _sub_once(text, old, new):
    assert text.count(old) == 1, (old, text.count(old))
    return text.replace(old, new)


def _sub_n(text, old, new, n):
    assert text.count(old) == n, (old, text.count(old))
    return text.replace(old, new)


def param_copy(dst, taps, width, edits=None, depth=None, prove_depth=None, nouf_depth=None):
    """Copy the sources to dst and set the generics, the TAPS-dependent guards
    and the depths.

    edits: {file: [(old, new), ...]}, each old text exactly once.
    depth: depth of data_bmc (default bmc_depth(taps)); nouf_depth: depth of
    data_bmc_nouf (default the same as depth). prove_depth: depth of the
    data_prove and ctrl_prove tasks (default 3 and 2 from the sby file).
    """
    dst = Path(dst)
    shutil.copytree(HERE, dst, dirs_exist_ok=True, ignore=_ignore_subdirs)
    sby = dst / SBY
    text = sby.read_text()
    text = _sub_n(text, '-gTAPS=5 -gWIDTH=8', f'-gTAPS={taps} -gWIDTH={width}', 14)
    d = depth or bmc_depth(taps)
    text = _sub_once(text, 'bmc_d:   depth 16\n', f'bmc_d:   depth {d}\n')
    text = _sub_once(text, 'bmc_dc:  depth 16\n', f'bmc_dc:  depth {nouf_depth or d}\n')
    if prove_depth:
        text = _sub_once(text, 'prove_d: depth 3\n', f'prove_d: depth {prove_depth}\n')
        text = _sub_once(text, 'prove_c: depth 2\n', f'prove_c: depth {prove_depth}\n')
    text = _sub_n(text, 'select -assert-count 5 fir_complex_pipe_Brtl_*/a:uf_instance=cmul',
                  f'select -assert-count {taps} fir_complex_pipe_Brtl_*/a:uf_instance=cmul', 2)
    text = _sub_n(text, 'select -assert-count 4 fir_complex_pipe_Brtl_*/a:uf_instance=cadd',
                  f'select -assert-count {taps - 1} fir_complex_pipe_Brtl_*/a:uf_instance=cadd', 2)
    for val in ("1'0", "1'1"):
        text = _sub_once(text, f'select -assert-count 9 fir_complex_pipe_Brtl_*/a:uf_disable={val}',
                         f'select -assert-count {2 * taps - 1} '
                         f'fir_complex_pipe_Brtl_*/a:uf_disable={val}')
    text = _sub_once(text, 'select -assert-count 5 fir_pipe_ref_Brtl_*/a:uf_instance=cmul',
                     f'select -assert-count {taps} fir_pipe_ref_Brtl_*/a:uf_instance=cmul')
    text = _sub_once(text, 'select -assert-count 4 fir_pipe_ref_Brtl_*/a:uf_instance=cadd',
                     f'select -assert-count {taps - 1} fir_pipe_ref_Brtl_*/a:uf_instance=cadd')
    text = _sub_once(text, 'dinv:  select -assert-count 35 tb_fir_pipe_data_formal/a:uf_instance=stim_f',
                     f'dinv:  select -assert-count {2 + 2 * hist_len(taps) + taps} '
                     'tb_fir_pipe_data_formal/a:uf_instance=stim_f')
    sby.write_text(text)
    for f, pairs in (edits or {}).items():
        p = dst / f
        t = p.read_text()
        for old, new in pairs:
            t = _sub_once(t, old, new)
        p.write_text(t)
    return dst


def _run(tmp_path, task, taps=DEFAULT[0], width=DEFAULT[1], edits=None, **kw):
    src = param_copy(tmp_path / 'param' / PFX, taps, width, edits, **kw)
    return run_sby(src, SBY, task, tmp_path)


def _code(line):
    return line.split(' ;', 1)[0]


def _bv(*ws):
    return ' '.join(f'(_ BitVec {w})' for w in ws)


def expected_decls(task, taps, width):
    """UF declarations in the task's model: symbol -> declare-fun line."""
    pw, ow = prod_width(width), out_width(taps, width)
    if '_nouf' in task:
        return {}
    dut = {
        'cmul': f'(declare-fun |cmul| ({_bv(width, width, width, width)}) (_ BitVec {2 * pw}))',
        'cadd': f'(declare-fun |cadd| ({_bv(ow, ow, ow, ow)}) (_ BitVec {2 * ow}))',
    }
    tb = {
        'stim_f': f'(declare-fun |stim_f| ({_bv(16)}) (_ BitVec {2 * width}))',
        'out_f': f'(declare-fun |out_f| ({_bv(16)}) (_ BitVec {2 * ow}))',
    }
    return {**dut, **tb} if task.startswith('data') else dut


def _check_model(r, task, taps, width):
    smt = sby_model(r, f'{PFX}_{task}')
    decls = uf_decls(smt)
    exp = expected_decls(task, taps, width)
    assert {k: [_code(l) for l in v] for k, v in decls.items()} == \
        {k: [v] for k, v in exp.items()}, decls
    return smt


def _params(grid=GRID):
    return [pytest.param(t, w, s, id=f'T{t}-W{w}-{s}') for t, w in grid for s in STYLES]


# ---------------------------------------------------------------- data: BMC

def _bmc_params():
    # data_bmc is heavy: T3-W8 takes about 1 min, T3-W16 and T5-W8 several
    # minutes (slow), T5-W16 more than 20 min (validation).
    marks = {(3, 8): [], (3, 16): [pytest.mark.slow], (5, 8): [pytest.mark.slow],
             (5, 16): [pytest.mark.validation]}
    return [pytest.param(t, w, s, id=f'T{t}-W{w}-{s}', marks=marks[(t, w)])
            for t, w in GRID for s in STYLES]


@pytest.mark.parametrize('taps,width,style', _bmc_params())
def test_data_bmc(tmp_path, taps, width, style):
    """Data does not depend on control: PASS at depth bmc_depth; the model has
    the UFs cmul, cadd, stim_f and out_f with the correct port widths."""
    task = f'data_bmc_{style}'
    r = _run(tmp_path, task, taps, width)
    assert r.status == 'PASS', r.log[-3000:]
    assert r.uf_warnings == [], r.uf_warnings
    smt = _check_model(r, task, taps, width)
    assert set(ASSERT_RE.findall(smt)) == DATA_ASSERTS


@pytest.mark.validation
@pytest.mark.parametrize('style', STYLES)
def test_data_bmc_nouf(tmp_path, style):
    """Non-UF comparison run (all marks switched off, UF_MODE = false): A is
    checked against the FIR reference (a_define_chk), B as in the UF run.
    TAPS=3, WIDTH=8, the same depth as data_bmc (14). Takes more than 20 min
    (stopped at step 10/14 in both styles; the UF run at the same depth takes
    about 40-60 s), hence validation."""
    task = f'data_bmc_nouf_{style}'
    r = _run(tmp_path, task, 3, 8)
    assert r.status == 'PASS', r.log[-3000:]
    smt = _check_model(r, task, 3, 8)
    assert set(ASSERT_RE.findall(smt)) == DATA_ASSERTS | {'g_nouf.a_define_chk',
                                                          'g_nouf.a_tab_range_chk'}


# ---------------------------------------------------------------- data: prove

@pytest.mark.parametrize('taps,width,style', _params())
def test_data_prove(tmp_path, taps, width, style):
    """k-induction with auxiliary invariants: PASS (depth 3). The model has the
    testbench assertions, the invariants of the testbench vunit and the
    invariants of the DUT vunit for both instances (a, b)."""
    task = f'data_prove_{style}'
    r = _run(tmp_path, task, taps, width)
    assert r.status == 'PASS', r.log[-3000:]
    assert 'successful proof by k-induction' in r.log, r.log[-3000:]
    assert r.uf_warnings == [], r.uf_warnings
    smt = _check_model(r, task, taps, width)
    asserts = ASSERT_RE.findall(smt)
    assert set(asserts) == PROVE_ASSERTS and len(asserts) == len(PROVE_ASSERTS), asserts
    assert 'yosys-smt2-anyconst' in smt
    # The assertions of the DUT vunit are in the DUT module, whose two
    # instances (a, b) are hierarchy cells: smtbmc checks them in both.
    sec = smt2_module_sections(smt)
    dut = [m for m in sec if m.startswith('fir_complex_pipe_Brtl_')]
    assert len(dut) == 1, dut
    assert {f'fir_complex_pipe_inv.{n}' for n in DUT_INVARIANTS} == set(ASSERT_RE.findall(sec[dut[0]]))
    cells = SMT2_CELL_RE.findall(sec['tb_fir_pipe_data_formal'])
    assert sorted(i for t, i in cells if t == dut[0]) == ['a', 'b'], cells


def test_sby_sources():
    """Vunits only in the prove tasks; assertions are not modified in the sby file."""
    for task, tags in TASK_TAGS.items():
        ghdl = [l for l in sby_script(HERE / SBY, tags | {task}) if l.startswith('ghdl ')]
        assert len(ghdl) == 1, ghdl
        g = ghdl[0]
        assert (DUT_INV in g) == (DATA_INV in g) == task.startswith('data_prove'), (task, g)
        assert (CTRL_INV in g) == task.startswith('ctrl_prove'), (task, g)
        assert ('-gSKID=true' in g) == task.endswith('_skid'), (task, g)
        assert ('-gUF_MODE=false' in g) == ('_nouf' in task), (task, g)
        assert ('-gUF_MODE=true' in g) == ('_nouf' not in task), (task, g)
    text = (HERE / SBY).read_text()
    assert 'chformal' not in text
    # UF vs. non-UF is selected by the generic (uf_disable = not UF_MODE on
    # the DUT's marks); the sby file does not remove marks.
    assert 'setattr' not in text


# ---------------------------------------------------------------- ctrl

CTRL_KINDS = ['bmc_uf', 'bmc_nouf', 'prove_uf', 'prove_nouf']


@pytest.mark.parametrize('kind', CTRL_KINDS)
@pytest.mark.parametrize('taps,width,style', _params())
def test_ctrl(tmp_path, kind, taps, width, style):
    """Control does not depend on data: PASS. uf: cmul/cadd as UFs, nouf: interpreted."""
    task = f'ctrl_{kind}_{style}'
    r = _run(tmp_path, task, taps, width)
    assert r.status == 'PASS', r.log[-3000:]
    assert r.uf_warnings == [], r.uf_warnings
    smt = _check_model(r, task, taps, width)
    if 'prove' in kind:
        assert 'successful proof by k-induction' in r.log, r.log[-3000:]
        assert set(ASSERT_RE.findall(smt)) == CTRL_PROVE_ASSERTS
    else:
        assert set(ASSERT_RE.findall(smt)) == CTRL_ASSERTS


# ---------------------------------------------------------------- vacuity

def _data_cover_text(taps):
    # Both channels have transferred D+2 beats; B has had an s-side bubble and
    # back pressure as well as m-side back pressure.
    n = depth_of(taps) + 2
    return ("    c_both : cover {armed = '1' and rst_in = '0' and "
            f"ocnt_a >= {n} and ocnt_b >= {n} and "
            "b_s_idle = '1' and b_s_wait = '1' and b_m_wait = '1'};\n")


def _cover_j_text(taps):
    # The antecedent of a_match holds with a full window (j >= TAPS-1) after
    # stalls.
    return ("    c_b_checked_j : cover {armed = '1' and rst_in = '0' and m_xfer_b = '1' and "
            f"ocnt_b = j and j >= {taps - 1} and b_s_idle = '1' and b_m_wait = '1'}};\n")


# The antecedent of a_m_stable_b and a transfer after the stall on the same cycle.
COVER_STALL = ("    c_b_stall_xfer : cover {armed = '1' and rst_in = '0' and "
               "m_wait_b_q = '1' and m_xfer_b = '1'};\n")


# Antecedents of the progress assertions at the bound (a_prog_m_b,
# a_prog_s_b): the condition has held for bound-1 consecutive cycles and still
# holds.
# m: m_ready up for M_WAIT = D-1 cycles with beats in flight and no m_valid.
COVER_PROG_M = "    c_prog_m : cover {prog_m_b = '1' and cnt_m_b = M_WAIT - 1};\n"
# s (skid): an input beat waits S_WAIT = D cycles while m_ready is up.
COVER_PROG_S = "    c_prog_s : cover {prog_s_b = '1' and cnt_s_b = S_WAIT - 1};\n"
# s (comb): the condition never holds (S_WAIT = 0, combinational ready chain).
COVER_PROG_S_ANY = "    c_prog_s_any : cover {prog_s_b = '1'};\n"


def _ctrl_cover_text(taps):
    n = depth_of(taps) + 2
    return ("    c_traffic : cover {rst_in = '0' and "
            f"icnt >= {n} and ocnt >= {n} and in_bp = '1' and out_bp = '1'}};\n")


# Sensitivity: an assumption under which the cover must not be reachable.
DATA_INJECT = {
    # The negation of a_define: every transfer of A is forbidden (the state space empties).
    'a_define_contradiction': (
        "    v_contra : assume always\n"
        "        (armed = '1' and rst_in = '0' and m_xfer_a = '1') -> (m_re_a /= uf_re_a);\n"),
    'b_never_valid': "    v_b_never_valid : assume always s_valid_b_in = '0';\n",
    'b_never_stalled': "    v_b_never_stalled : assume always m_ready_b_in = '1';\n",
}
# Sensitivity of the progress cover: B's m_ready is never up on two
# consecutive cycles, so the progress condition cannot last bound-1 cycles
# (bound-1 >= 1).
PROG_INJECT = {
    'b_ready_pulse': ("    v_b_ready_pulse : assume always\n"
                      "        (m_ready_b_in = '1') -> next (m_ready_b_in = '0');\n"),
}
CTRL_INJECT = {
    'never_valid': "    v_never_valid : assume always s_valid_in = '0';\n",
    'never_stalled': "    v_never_stalled : assume always m_ready_in = '1';\n",
}


def _data_cover(tmp_path, task, taps, width, cover, extra='', depth=None):
    src = param_copy(tmp_path / 'param' / PFX, taps, width)
    tags = TASK_TAGS[task] | {task}
    srcs = DATA_SOURCES + (INV_SOURCES if task.startswith('data_prove') else [])
    return run_cover(src, srcs, sby_script(src / SBY, tags), tmp_path, tb=DATA_TB,
                     extra=extra, depth=depth or bmc_depth(taps), cover=cover)


def _ctrl_cover(tmp_path, task, taps, width, extra=''):
    src = param_copy(tmp_path / 'param' / PFX, taps, width)
    return run_cover(src, CTRL_SOURCES, sby_script(src / SBY, TASK_TAGS[task] | {task}),
                     tmp_path, tb=CTRL_TB, extra=extra, depth=20,
                     cover=_ctrl_cover_text(taps))


def _assert_reached(r, limit):
    assert r.status == 'PASS', r.log[-3000:]
    steps = cover_steps(r.log)
    assert steps and 'Unreached cover' not in r.log, r.log[-3000:]
    assert steps[0] < limit, steps
    assert r.uf_warnings == [], r.uf_warnings
    return steps


def _assert_unreached(r):
    assert r.status == 'FAIL', r.log[-3000:]
    assert 'Unreached cover statement' in r.log, r.log[-3000:]
    assert cover_steps(r.log) == []


@pytest.mark.parametrize('taps,width,style', _params())
def test_data_vacuity_cover(tmp_path, taps, width, style):
    """In the data_bmc model both channels transfer D+2 beats and B stalls on
    both sides within the BMC horizon (step 2*D+4)."""
    r = _data_cover(tmp_path, f'data_bmc_{style}', taps, width, _data_cover_text(taps))
    steps = _assert_reached(r, bmc_depth(taps))
    assert steps[0] == 2 * depth_of(taps) + 4, steps
    assert set(uf_decls(sby_model(r, 'cov'))) == {'cmul', 'cadd', 'stim_f', 'out_f'}


@pytest.mark.slow
@pytest.mark.parametrize('style', STYLES)
def test_data_nouf_vacuity_cover(tmp_path, style):
    """In the non-UF comparison run (a_define_chk as an assertion) the cover
    is reached at the same step: the run is not vacuous."""
    r = _data_cover(tmp_path, f'data_bmc_nouf_{style}', 3, 8, _data_cover_text(3))
    steps = _assert_reached(r, bmc_depth(3))
    assert steps[0] == 2 * depth_of(3) + 4, steps
    assert uf_decls(sby_model(r, 'cov')) == {}


@pytest.mark.parametrize('style', STYLES)
@pytest.mark.parametrize('kind', ['bmc', 'prove'])
def test_data_vacuity_cover_j(tmp_path, kind, style):
    """The check at the symbolic index is reached in the task's model (prove:
    with the vunits and expose/connect) with a full window after stalls."""
    taps, width = DEFAULT
    r = _data_cover(tmp_path, f'data_{kind}_{style}', taps, width, _cover_j_text(taps))
    _assert_reached(r, bmc_depth(taps))


@pytest.mark.parametrize('style', STYLES)
def test_data_vacuity_cover_stall(tmp_path, style):
    """The antecedent of a_m_stable_b is reached, and the stalled beat is transferred."""
    taps, width = DEFAULT
    r = _data_cover(tmp_path, f'data_bmc_{style}', taps, width, COVER_STALL)
    _assert_reached(r, bmc_depth(taps))


@pytest.mark.parametrize('style', STYLES)
@pytest.mark.parametrize('kind', ['bmc', 'prove'])
def test_data_vacuity_cover_prog_m(tmp_path, kind, style):
    """The antecedent of a_prog_m_b at the bound is reached (m_ready up for
    D-1 cycles, beats in flight, no m_valid): the assertion is not vacuous and
    the bound is not loose. Step D: reset (0), acceptance (1), beat in stage
    0 (2) and D-2 cycles onward."""
    taps, width = DEFAULT
    r = _data_cover(tmp_path, f'data_{kind}_{style}', taps, width, COVER_PROG_M)
    steps = _assert_reached(r, bmc_depth(taps))
    assert steps[0] == depth_of(taps), steps


@pytest.mark.parametrize('kind', ['bmc', 'prove'])
def test_data_vacuity_cover_prog_s(tmp_path, kind):
    """skid: the antecedent of a_prog_s_b at the bound is reached (an input
    beat waits D cycles while m_ready is up, after all 2*D slots have been
    full). Measured step 3*D (< bmc_depth when D <= 6)."""
    taps, width = DEFAULT
    r = _data_cover(tmp_path, f'data_{kind}_skid', taps, width, COVER_PROG_S)
    steps = _assert_reached(r, bmc_depth(taps))
    assert steps[0] == 3 * depth_of(taps), steps


def test_data_prog_s_comb_never(tmp_path):
    """comb: an input beat never waits while m_ready is up (S_WAIT = 0 is the
    exact bound, not just a sufficient one)."""
    taps, width = DEFAULT
    r = _data_cover(tmp_path, 'data_bmc_comb', taps, width, COVER_PROG_S_ANY)
    _assert_unreached(r)


@pytest.mark.parametrize('inject', sorted(PROG_INJECT))
@pytest.mark.parametrize('style', STYLES)
def test_data_vacuity_sensitivity_prog(tmp_path, style, inject):
    """The progress cover is sensitive: an assumption that pulses m_ready -> unreachable."""
    taps, width = DEFAULT
    r = _data_cover(tmp_path, f'data_bmc_{style}', taps, width, COVER_PROG_M,
                    extra=PROG_INJECT[inject])
    _assert_unreached(r)


# A bound one tighter: the correct DUT fails, i.e. the bounds are exact.
TIGHT = {
    'm': ({DATA_TB: [("    constant M_WAIT : natural := D - 1;\n",
                      "    constant M_WAIT : natural := D - 2;\n")]}, 'a_prog_m_b'),
    's': ({DATA_TB: [("            return depth;\n",
                      "            return depth - 1;\n")]}, 'a_prog_s_b'),
}


@pytest.mark.parametrize('side,style', [('m', 'comb'), ('m', 'skid'), ('s', 'skid')])
def test_prog_bound_tight(tmp_path, side, style):
    """A progress bound one tighter fails on the correct DUT at the named
    assertion (FAIL): the bound is the DUT's real worst case. (comb s-side:
    bound 0, test_data_prog_s_comb_never.)"""
    edits, name = TIGHT[side]
    r = _run(tmp_path, f'data_bmc_{style}', *MUT_P, edits=edits)
    assert r.status == 'FAIL', r.log[-3000:]
    assert failed_asserts(r.log) == [name], r.log[-3000:]


@pytest.mark.parametrize('inject', sorted(DATA_INJECT))
@pytest.mark.parametrize('style', STYLES)
def test_data_vacuity_sensitivity(tmp_path, style, inject):
    """A contradictory assumption or one that closes B -> data cover unreachable (FAIL)."""
    taps, width = DEFAULT
    r = _data_cover(tmp_path, f'data_bmc_{style}', taps, width, _data_cover_text(taps),
                    extra=DATA_INJECT[inject])
    _assert_unreached(r)


@pytest.mark.parametrize('kind', ['bmc_uf', 'bmc_nouf'])
@pytest.mark.parametrize('taps,width,style', _params())
def test_ctrl_vacuity_cover(tmp_path, kind, taps, width, style):
    """In the ctrl model traffic flows (D+2 beats in and out) and back
    pressure occurs on both sides."""
    r = _ctrl_cover(tmp_path, f'ctrl_{kind}_{style}', taps, width)
    _assert_reached(r, 20)


@pytest.mark.parametrize('inject', sorted(CTRL_INJECT))
@pytest.mark.parametrize('style', STYLES)
def test_ctrl_vacuity_sensitivity(tmp_path, style, inject):
    """An assumption that prevents traffic or back pressure -> ctrl cover unreachable."""
    taps, width = DEFAULT
    r = _ctrl_cover(tmp_path, f'ctrl_bmc_uf_{style}', taps, width, extra=CTRL_INJECT[inject])
    _assert_unreached(r)


# ---------------------------------------------------------------- mutations

COMB_LOAD = ("                    elsif rdy(i) = '1' then\n"
             "                        mn_v(i) <= in_v(i);\n")
# The branch of a skid stage in which the skid beat moves to the main slot.
SKID_MOVE = ("                            mn_re(i) <= sk_re(i);\n"
             "                            mn_im(i) <= sk_im(i);\n"
             "                            mn_v(i)  <= '1';\n"
             "                            sk_v(i)  <= '0';\n")

MUTATIONS = {
    # --- both styles
    # g_dl_on_valid: the delay line also advances on a rejected beat (s_valid
    # without s_ready): data depends on control.
    'g_dl_on_valid': ('both', {DUT: [(
        "            elsif accept = '1' then\n",
        "            elsif s_valid_in = '1' then\n")]}),
    # g_ready_on_sign: control depends on data: a negative sample is not
    # accepted (s_ready and the input valid low).
    'g_ready_on_sign': ('both', {DUT: [
        ("    in_v(0)          <= s_valid_in;\n",
         "    in_v(0)          <= s_valid_in and not s_re_in(WIDTH - 1);\n"),
        ("    accept           <= s_valid_in and rdy(0);\n",
         "    accept           <= s_valid_in and rdy(0) and not s_re_in(WIDTH - 1);\n"),
        ("    s_ready_out <= rdy(0);\n",
         "    s_ready_out <= rdy(0) and not s_re_in(WIDTH - 1);\n")]}),
    # g_valid_on_sign: control depends on data: m_valid is hidden for a
    # negative result.
    'g_valid_on_sign': ('both', {DUT: [(
        "    m_valid_out <= mn_v(D - 1);\n",
        "    m_valid_out <= mn_v(D - 1) and not mn_re(D - 1)(0)(OW - 1);\n")]}),
    # g_stall_glitch: the output data depends combinationally on m_ready
    # during a stall (correct on the transfer cycle).
    'g_stall_glitch': ('both', {DUT: [(
        "    m_re_out    <= mn_re(D - 1)(0);\n",
        "    m_re_out    <= mn_re(D - 1)(0) when m_ready_in = '1' else not mn_re(D - 1)(0);\n")]}),
    # g_never_valid: m_valid never rises: all beats disappear (a black hole).
    # a_match and a_m_stable_b see nothing (no transfers), and the control is
    # the same for all data: only the progress assertion catches it.
    'g_never_valid': ('both', {DUT: [(
        "    m_valid_out <= mn_v(D - 1);\n",
        "    m_valid_out <= '0';\n")]}),
    # --- combinational ready chain
    # c_capture_stall: stage 1 captures data on the wrong cycle: while stalled
    # its data is overwritten by the waiting beat.
    'c_capture_stall': ('comb', {DUT: [(
        COMB_LOAD,
        "                    elsif rdy(i) = '0' and i = 1 and in_v(i) = '1' then\n"
        "                        mn_re(i) <= nx_re(i);\n"
        "                        mn_im(i) <= nx_im(i);\n" + COMB_LOAD)]}),
    # c_bubble_beat: a bubble produces a beat: stage 2 becomes valid whenever
    # it loads.
    'c_bubble_beat': ('comb', {DUT: [(
        COMB_LOAD,
        COMB_LOAD + "                        if i = 2 then\n"
                    "                            mn_v(i) <= '1';\n"
                    "                        end if;\n")]}),
    # c_valid_stuck: the valid of stage 1 is not cleared when the beat leaves: the beat is duplicated.
    'c_valid_stuck': ('comb', {DUT: [(
        COMB_LOAD,
        COMB_LOAD + "                        if i = 1 and mn_v(i) = '1' then\n"
                    "                            mn_v(i) <= '1';\n"
                    "                        end if;\n")]}),
    # c_wrong_valid: data is captured based on the stage's own (old) valid,
    # not the input valid: the beat after a bubble is not captured.
    'c_wrong_valid': ('comb', {DUT: [(
        "                        mn_v(i) <= in_v(i);\n"
        "                        if in_v(i) = '1' then\n",
        "                        mn_v(i) <= in_v(i);\n"
        "                        if mn_v(i) = '1' then\n")]}),
    # c_deadlock: the ready of stage 2 is low whenever stage 1 holds a beat:
    # stage 1 never frees up and stage 2 never loads, so the pipeline
    # deadlocks on the first beat (the comb counterpart of s_deadlock).
    'c_deadlock': ('comb', {DUT: [(
        "            rdy(i) <= not mn_v(i) or rdy(i + 1);\n",
        "            rdy(i) <= (not mn_v(i) or rdy(i + 1)) and not mn_v(maximum(i - 1, 0)) when i = 2 else\n"
        "                      not mn_v(i) or rdy(i + 1);\n")]}),
    # c_stall_on_sign: control depends on data inside the pipeline: stage 2
    # stalls when its data is negative.
    'c_stall_on_sign': ('comb', {DUT: [(
        "            rdy(i) <= not mn_v(i) or rdy(i + 1);\n",
        "            rdy(i) <= not mn_v(i) or (rdy(i + 1) and not mn_re(i)(0)(OW - 1)) when i = 2 else\n"
        "                      not mn_v(i) or rdy(i + 1);\n")]}),
    # --- skid buffer
    # s_skid_lost: the accepted beat of a stalled stage is not kept in the skid slot (it is lost).
    's_skid_lost': ('skid', {DUT: [(
        "                        sk_v(i)  <= '1';\n",
        "                        sk_v(i)  <= '0';\n")]}),
    # s_skid_dup: the skid beat moves to the main register, but the skid slot
    # does not empty (the beat is duplicated).
    's_skid_dup': ('skid', {DUT: [(
        "                            sk_v(i)  <= '0';\n", "")]}),
    # s_skid_stale: the skid slot captures data also when full (a waiting,
    # unaccepted beat overwrites the skid beat).
    's_skid_stale': ('skid', {DUT: [(
        "                    elsif in_v(i) = '1' and sk_v(i) = '0' then\n",
        "                    elsif in_v(i) = '1' then\n")]}),
    # s_deadlock: when the main slot frees up, the skid beat does not move;
    # instead the main slot empties and the skid slot stays full: the stage no
    # longer accepts or delivers anything (a permanent deadlock with the skid
    # beat stuck).
    's_deadlock': ('skid', {DUT: [(SKID_MOVE, "                            mn_v(i)  <= '0';\n")]}),
    # s_stall_on_sign: control depends on data: the main register of stage 2
    # does not free up when its data is negative.
    's_stall_on_sign': ('skid', {DUT: [(
        "                    elsif mn_v(i) = '0' or rdy(i + 1) = '1' then\n",
        "                    elsif mn_v(i) = '0' or (rdy(i + 1) = '1' and\n"
        "                          not (i = 2 and mn_re(i)(0)(OW - 1) = '1')) then\n")]}),
}

# Expectation per mutation: (data_bmc, ctrl_bmc), the assertions that fail
# with status FAIL. The progress assertions (a_prog_m_b, a_prog_s_b) catch
# deadlocks and lost beats (g_never_valid, c_deadlock, s_deadlock), and also
# the control mutations (*_on_sign): in those the control stalls permanently
# on certain data (ready low, or the beat hidden and lost), which is a
# progress failure on channel B. The recorded name is the assertion of
# smtbmc's shortest counterexample (TAPS=3, WIDTH=8).
EXPECT = {
    'g_dl_on_valid': ({'a_match'}, 'PASS'),
    'g_ready_on_sign': ({'a_prog_s_b'}, {'a_s_ready_eq'}),
    'g_valid_on_sign': ({'a_prog_m_b'}, {'a_m_valid_eq'}),
    'g_stall_glitch': ({'a_m_stable_b'}, 'PASS'),
    'g_never_valid': ({'a_prog_m_b'}, 'PASS'),
    'c_capture_stall': ({'a_match'}, 'PASS'),
    'c_bubble_beat': ({'a_match'}, 'PASS'),
    'c_valid_stuck': ({'a_match'}, 'PASS'),
    'c_wrong_valid': ({'a_match'}, 'PASS'),
    'c_deadlock': ({'a_prog_s_b'}, 'PASS'),
    'c_stall_on_sign': ({'a_prog_s_b'}, {'a_s_ready_eq', 'a_m_valid_eq'}),
    's_skid_lost': ({'a_match'}, 'PASS'),
    's_skid_dup': ({'a_match'}, 'PASS'),
    's_skid_stale': ({'a_match'}, 'PASS'),
    's_deadlock': ({'a_prog_m_b'}, 'PASS'),
    's_stall_on_sign': ({'a_prog_s_b'}, {'a_s_ready_eq', 'a_m_valid_eq'}),
}


def _mut_cases(pred=lambda m: True):
    out = []
    for m in sorted(MUTATIONS):
        styles = STYLES if MUTATIONS[m][0] == 'both' else [MUTATIONS[m][0]]
        out += [pytest.param(m, s, id=f'{m}-{s}') for s in styles if pred(m)]
    return out


def _check_expect(r, exp, task):
    if exp == 'PASS':
        assert r.status == 'PASS', r.log[-3000:]
        return
    assert r.status == 'FAIL', r.log[-3000:]
    fa = failed_asserts(r.log)
    assert fa and set(fa) <= exp, fa
    assert (r.workdir / f'{PFX}_{task}' / 'engine_0' / 'trace.vcd').exists()


def mut_bmc_depth(taps, style):
    """data_bmc depth in the mutation runs. comb: bmc_depth. skid: s_ready
    drops only when all 2*D slots are full; only then is a rejected beat
    (g_dl_on_valid) possible, and a beat computed with the wrong window can be
    checked only after the 2*D beats ahead of it. Measured (TAPS=3, D=4):
    g_dl_on_valid-skid fails at depth 15, not 14 (= bmc_depth). 4*D is used
    (= 16, one step of margin)."""
    return bmc_depth(taps) if style == 'comb' else max(bmc_depth(taps), 4 * depth_of(taps))


@pytest.mark.parametrize('mut,style', _mut_cases())
@pytest.mark.parametrize('kind', ['data_bmc', 'ctrl_bmc_uf', 'ctrl_bmc_nouf'])
def test_mutation(tmp_path, kind, mut, style):
    """Control mutations fail the ctrl property, data mutations the data
    property (a_match or a_m_stable_b), deadlocks and lost beats the progress
    assertions (a_prog_m_b, a_prog_s_b; also the control mutations, see
    EXPECT); with data mutations ctrl stays PASS. FAIL (not ERROR) at a named
    assertion, and a trace is written.
    A data_bmc run expected to fail runs at depth mut_bmc_depth (skid: 4*D)."""
    data_exp, ctrl_exp = EXPECT[mut]
    task = f'{kind}_{style}'
    # A deeper horizon only for runs expected to fail (detection); PASS
    # expectations run at bmc_depth (depth 16 with skid takes minutes).
    kw = ({'depth': mut_bmc_depth(MUT_P[0], style)}
          if kind == 'data_bmc' and data_exp != 'PASS' else {})
    r = _run(tmp_path, task, *MUT_P, edits=MUTATIONS[mut][1], **kw)
    _check_expect(r, data_exp if kind == 'data_bmc' else ctrl_exp, task)


@pytest.mark.parametrize('mut,style', _mut_cases(lambda m: EXPECT[m][0] != 'PASS'))
def test_prove_mutation_fails(tmp_path, mut, style):
    """The invariants do not mask data bugs or progress failures: data_prove is
    never PASS (UNKNOWN or FAIL at the default depth)."""
    r = _run(tmp_path, f'data_prove_{style}', *MUT_P, edits=MUTATIONS[mut][1])
    assert r.status in ('UNKNOWN', 'FAIL'), r.log[-3000:]
    if r.status == 'FAIL':
        assert set(failed_asserts(r.log)) <= PROVE_ASSERTS, r.log[-3000:]


@pytest.mark.parametrize('mut,style', _mut_cases(lambda m: EXPECT[m][1] != 'PASS'))
def test_ctrl_prove_mutation_fails(tmp_path, mut, style):
    """A control mutation is not proven in the ctrl_prove task; at depth 20 the
    basecase fails at a named assertion (FAIL)."""
    r = _run(tmp_path, f'ctrl_prove_uf_{style}', *MUT_P, edits=MUTATIONS[mut][1])
    assert r.status in ('UNKNOWN', 'FAIL'), r.log[-3000:]
    r = _run(tmp_path / 'deep', f'ctrl_prove_uf_{style}', *MUT_P, edits=MUTATIONS[mut][1],
             prove_depth=20)
    assert r.status == 'FAIL', r.log[-3000:]
    fa = failed_asserts(r.log)
    assert fa and set(fa) <= CTRL_PROVE_ASSERTS, r.log[-3000:]


# ---------------------------------------------------------------- necessity of the assumptions

NO_A_REF_RATE = {DATA_TB: [(
    "    a_ref_rate : assume always\n"
    "        (rst_in = '0') -> (s_valid_a_in = '1' and m_ready_a_in = '1');\n", '')]}
NO_WRAP = {DATA_TB: [(
    "    a_no_wrap : assume always\n"
    "        (rst_in = '0') -> (icnt_a /= x\"FFFF\");\n", '')]}


def test_a_ref_rate_needed(tmp_path):
    """Without a_ref_rate out_f stays untied at the indices that A did not
    produce: a_match fails (FAIL, not ERROR)."""
    r = _run(tmp_path, 'data_bmc_comb', *MUT_P, edits=NO_A_REF_RATE)
    assert r.status == 'FAIL', r.log[-3000:]
    assert failed_asserts(r.log) == ['a_match'], r.log[-3000:]


@pytest.mark.parametrize('style', STYLES)
def test_a_no_wrap_needed_for_prove(tmp_path, style):
    """Without the counter wrap bound the induction does not succeed (UNKNOWN)."""
    r = _run(tmp_path, f'data_prove_{style}', *MUT_P, edits=NO_WRAP)
    assert r.status == 'UNKNOWN', r.log[-3000:]
    assert 'Temporal induction failed' in r.log

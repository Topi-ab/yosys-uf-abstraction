"""Complex FIR: data does not depend on control AND control does not depend on data.

Two properties of the same DUT (fir_complex.vhdl):
- data (tb_fir_data_formal.vhdl): channel A at full rate defines out_f
  (a_define), channel B with free s_valid/m_ready sequences is checked
  (a_match, symbolic beat index j). The input stim_f(icnt) is a UF.
  UF_MODE (testbench generic, -gUF_MODE per task) selects UF or non-UF: the
  DUT receives it through its generic map and switches its marks off
  (uf_disable); data_bmc_nouf uses a free stimulus table and an interpreted
  FIR reference, and a_define is an assertion (a_define_chk).
- ctrl (tb_fir_ctrl_formal.vhdl): instances C and D with the same control
  inputs and independent free data; assertions a_s_ready_eq and a_m_valid_eq
  (non-interference).

The parameters (TAPS, WIDTH) are given to GHDL as top-level generic overrides
(-gTAPS=.. -gWIDTH=..) in a copied sby file; the TAPS-dependent guard counts
and the data_bmc depth are replaced at the same time. The sources are not touched.
"""
import re
import shutil
from pathlib import Path

import pytest

from conftest import (_ignore_subdirs, cover_steps, failed_asserts, run_cover, run_sby,
                      sby_model, sby_script, uf_decls)

HERE = Path(__file__).resolve().parent
SBY = 'fir_complex.sby'

DEFAULT = (5, 8)
GRID = [(t, w) for t in (3, 5) for w in (8, 16)]

DATA_SOURCES = ['fir_complex_pkg.vhdl', 'cmul.vhdl', 'csum.vhdl', 'fir_complex.vhdl',
                'tb_fir_stim_formal.vhdl', 'tb_fir_out_formal.vhdl', 'tb_fir_data_formal.vhdl']
CTRL_SOURCES = ['fir_complex_pkg.vhdl', 'cmul.vhdl', 'csum.vhdl', 'fir_complex.vhdl',
                'tb_fir_ctrl_formal.vhdl']
INV = 'tb_fir_data_formal_inv.psl'
DATA_TB = 'tb_fir_data_formal.vhdl'
CTRL_TB = 'tb_fir_ctrl_formal.vhdl'

# [tasks] lines of the sby file: task -> tags
TASK_TAGS = {
    'data_bmc': {'data', 'uf_dut', 'plain', 'dpu', 'bmc_d'},
    'data_bmc_nouf': {'data', 'nouf_dut', 'plain', 'dpc', 'bmc_dc'},
    'data_prove': {'data', 'uf_dut', 'inv', 'prove_d'},
    'ctrl_bmc_uf': {'ctrl', 'uf_dut', 'cu', 'bmc_c'},
    'ctrl_bmc_nouf': {'ctrl', 'nouf_dut', 'cc', 'bmc_c'},
    'ctrl_prove_uf': {'ctrl', 'uf_dut', 'cu', 'prove_c'},
    'ctrl_prove_nouf': {'ctrl', 'nouf_dut', 'cc', 'prove_c'},
}

INVARIANTS = ['inv_cnt_a', 'inv_cnt_b', 'inv_icnt', 'inv_dl_a', 'inv_dl_b', 'inv_out_b',
              'inv_order', 'inv_bound']
PROVE_ASSERTS = {'a_match'} | {f'tb_fir_data_formal_inv.{n}' for n in INVARIANTS}
CTRL_ASSERTS = {'a_s_ready_eq', 'a_m_valid_eq'}
# data_bmc_nouf (UF_MODE=false): a_match + the checks of the g_nouf branch.
NOUF_ASSERTS = {'a_match', 'g_nouf.a_define_chk', 'g_nouf.a_tab_range_chk'}
ASSERT_RE = re.compile(r'^; yosys-smt2-assert \d+ (\S+)', flags=re.M)


def bmc_depth(taps):
    """data_bmc depth: the vacuity cover is reached at step TAPS+5 (+2 margin)."""
    return taps + 7


def nouf_depth(taps):
    """data_bmc_nouf depth: vacuity cover at step TAPS+5, no margin (expensive)."""
    return taps + 6


def prod_width(w):
    return 2 * w + 1


def out_width(taps, w):
    return prod_width(w) + (taps - 1).bit_length()


# ---------------------------------------------------------------- parametrization

def _sub_once(text, old, new):
    assert text.count(old) == 1, (old, text.count(old))
    return text.replace(old, new)


def param_copy(dst, taps, width, edits=None, depth=None, prove_depth=None):
    """Copy the sources to dst and set the generics, TAPS-dependent guards and depths.

    edits: {file: [(old, new), ...]}, each old text exactly once.
    depth: data_bmc depth (default bmc_depth(taps)).
    prove_depth: depth of the data_prove and ctrl_prove tasks (default 3 and 2 from the sby file).
    """
    dst = Path(dst)
    shutil.copytree(HERE, dst, dirs_exist_ok=True, ignore=_ignore_subdirs)
    sby = dst / SBY
    text = sby.read_text()
    assert text.count('-gTAPS=5 -gWIDTH=8') == 5
    text = text.replace('-gTAPS=5 -gWIDTH=8', f'-gTAPS={taps} -gWIDTH={width}')
    text = _sub_once(text, 'bmc_d:   depth 12\n', f'bmc_d:   depth {depth or bmc_depth(taps)}\n')
    text = _sub_once(text, 'bmc_dc:  depth 9\n', f'bmc_dc:  depth {nouf_depth(taps)}\n')
    if prove_depth:
        text = _sub_once(text, 'prove_d: depth 3\n', f'prove_d: depth {prove_depth}\n')
        text = _sub_once(text, 'prove_c: depth 2\n', f'prove_c: depth {prove_depth}\n')
    text = _sub_once(text, '\nselect -assert-count 5 fir_complex_Brtl_*/a:uf_instance=cmul',
                     f'\nselect -assert-count {taps} fir_complex_Brtl_*/a:uf_instance=cmul')
    for grp, val in (('uf_dut:  ', "1'0"), ('nouf_dut:', "1'1")):
        text = _sub_once(text, f'{grp} select -assert-count 6 fir_complex_Brtl_*/a:uf_disable={val}',
                         f'{grp} select -assert-count {taps + 1} fir_complex_Brtl_*/a:uf_disable={val}')
    text = _sub_once(text, 'inv:   select -assert-count 15 tb_fir_data_formal/a:uf_instance=stim_f',
                     f'inv:   select -assert-count {3 * taps} tb_fir_data_formal/a:uf_instance=stim_f')
    text = _sub_once(text, 'inv:   select -assert-count 5 tb_fir_data_formal/a:uf_instance=cmul',
                     f'inv:   select -assert-count {taps} tb_fir_data_formal/a:uf_instance=cmul')
    sby.write_text(text)
    for f, pairs in (edits or {}).items():
        p = dst / f
        t = p.read_text()
        for old, new in pairs:
            t = _sub_once(t, old, new)
        p.write_text(t)
    return dst


def _run(tmp_path, task, taps=DEFAULT[0], width=DEFAULT[1], edits=None, depth=None,
         prove_depth=None):
    src = param_copy(tmp_path / 'param' / 'fir_complex', taps, width, edits, depth, prove_depth)
    return run_sby(src, SBY, task, tmp_path)


def _code(line):
    return line.split(' ;', 1)[0]


def _bv(*ws):
    return ' '.join(f'(_ BitVec {w})' for w in ws)


def expected_decls(task, taps, width):
    """UF declarations in the model of a task: symbol -> declare-fun line."""
    pw, ow = prod_width(width), out_width(taps, width)
    dut = {
        'cmul': f'(declare-fun |cmul| ({_bv(width, width, width, width)}) (_ BitVec {2 * pw}))',
        'csum': f'(declare-fun |csum| ({_bv(taps * pw, taps * pw)}) (_ BitVec {2 * ow}))',
    }
    tb = {
        'stim_f': f'(declare-fun |stim_f| ({_bv(16)}) (_ BitVec {2 * width}))',
        'out_f': f'(declare-fun |out_f| ({_bv(16)}) (_ BitVec {2 * ow}))',
    }
    if task in ('data_bmc', 'data_prove'):
        return {**dut, **tb}
    if task == 'data_bmc_nouf':
        return {}
    if task.endswith('_uf'):
        return dut
    return {}


def _check_model(r, task, taps, width):
    smt = sby_model(r, f'fir_complex_{task}')
    decls = uf_decls(smt)
    exp = expected_decls(task, taps, width)
    assert {k: [_code(l) for l in v] for k, v in decls.items()} == \
        {k: [v] for k, v in exp.items()}, decls
    return smt


# ---------------------------------------------------------------- data: BMC

@pytest.mark.parametrize('taps,width', [pytest.param(t, w, id=f'T{t}-W{w}') for t, w in GRID])
def test_data_bmc(tmp_path, taps, width):
    """Data does not depend on control: PASS at depth TAPS+7; the model has the
    UFs cmul, csum, stim_f and out_f with the right port widths."""
    r = _run(tmp_path, 'data_bmc', taps, width)
    assert r.status == 'PASS', r.log[-3000:]
    assert r.uf_warnings == [], r.uf_warnings
    smt = _check_model(r, 'data_bmc', taps, width)
    # The DUT's TAPS multipliers; the two DUT instances share one module.
    assert smt.count('(|cmul|') >= taps
    assert ASSERT_RE.findall(smt) == ['a_match']


@pytest.mark.validation
def test_data_bmc_nouf(tmp_path):
    """Non-UF reference run (UF_MODE=false): cmul and csum as real
    multiplication and sum, a free stimulus table and an interpreted FIR
    reference, a_define is checked (a_define_chk): PASS. TAPS=3, depth TAPS+6.
    Takes well over 10 minutes, hence validation (like data_bmc_nouf in
    tests/vhdl_fir_pipeline). The model has no UF declarations, and the
    assertions are a_match and the checks of the g_nouf branch."""
    r = _run(tmp_path, 'data_bmc_nouf', 3, 8)
    assert r.status == 'PASS', r.log[-3000:]
    assert r.uf_warnings == [], r.uf_warnings
    smt = _check_model(r, 'data_bmc_nouf', 3, 8)
    assert set(ASSERT_RE.findall(smt)) == NOUF_ASSERTS, ASSERT_RE.findall(smt)


# ---------------------------------------------------------------- data: prove

@pytest.mark.parametrize('taps,width', [pytest.param(t, w, id=f'T{t}-W{w}') for t, w in GRID])
def test_data_prove(tmp_path, taps, width):
    """k-induction with auxiliary invariants: PASS (depth 3). The model has the
    testbench's a_match and exactly the auxiliary invariants of the vunit."""
    r = _run(tmp_path, 'data_prove', taps, width)
    assert r.status == 'PASS', r.log[-3000:]
    assert 'successful proof by k-induction' in r.log, r.log[-3000:]
    assert r.uf_warnings == [], r.uf_warnings
    smt = _check_model(r, 'data_prove', taps, width)
    asserts = ASSERT_RE.findall(smt)
    assert set(asserts) == PROVE_ASSERTS and len(asserts) == len(PROVE_ASSERTS), asserts
    assert 'yosys-smt2-anyconst' in smt


def test_sby_sources():
    """Auxiliary invariants only in the data_prove task; UF_MODE per task; no
    assertions are modified and no marks are removed in the sby file."""
    for task, tags in TASK_TAGS.items():
        ghdl = [l for l in sby_script(HERE / SBY, tags | {task}) if l.startswith('ghdl ')]
        assert len(ghdl) == 1, ghdl
        assert (INV in ghdl[0]) == (task == 'data_prove'), (task, ghdl)
        uf_mode = 'false' if 'nouf_dut' in tags else 'true'
        assert f' -gUF_MODE={uf_mode} ' in ghdl[0], (task, ghdl)
    text = (HERE / SBY).read_text()
    assert 'chformal' not in text
    # UF vs. non-UF is selected by the generic; the sby file does not remove marks.
    assert 'setattr' not in text


# ---------------------------------------------------------------- ctrl

CTRL_TASKS = ['ctrl_bmc_uf', 'ctrl_bmc_nouf', 'ctrl_prove_uf', 'ctrl_prove_nouf']


@pytest.mark.parametrize('task', CTRL_TASKS)
@pytest.mark.parametrize('taps,width', [pytest.param(t, w, id=f'T{t}-W{w}') for t, w in GRID])
def test_ctrl(tmp_path, task, taps, width):
    """Control does not depend on data: PASS. uf: cmul/csum as UFs, nouf: interpreted."""
    r = _run(tmp_path, task, taps, width)
    assert r.status == 'PASS', r.log[-3000:]
    assert r.uf_warnings == [], r.uf_warnings
    if 'prove' in task:
        assert 'successful proof by k-induction' in r.log, r.log[-3000:]
    smt = _check_model(r, task, taps, width)
    assert set(ASSERT_RE.findall(smt)) == CTRL_ASSERTS


# ---------------------------------------------------------------- vacuity

def _data_cover_text(taps):
    # Both channels have transferred TAPS+2 beats; B has had an s-side bubble
    # and backpressure as well as m-side backpressure.
    return ("    c_both : cover {armed = '1' and rst_in = '0' and "
            f"ocnt_a >= {taps + 2} and ocnt_b >= {taps + 2} and "
            "b_s_idle = '1' and b_s_wait = '1' and b_m_wait = '1'};\n")


def _cover_j_text(taps):
    # The antecedent of a_match holds with a full window (j >= TAPS-1, all taps
    # use real samples) after stalls.
    return ("    c_b_checked_j : cover {armed = '1' and rst_in = '0' and m_xfer_b = '1' and "
            f"ocnt_b = j and j >= {taps - 1} and b_s_idle = '1' and b_m_wait = '1'}};\n")


def _ctrl_cover_text(taps):
    return ("    c_traffic : cover {rst_in = '0' and "
            f"icnt >= {taps + 2} and ocnt >= {taps + 2} and in_bp = '1' and out_bp = '1'}};\n")


# Sensitivity: an assumption under which the cover must not be reachable.
DATA_INJECT = {
    # The negation of a_define: every transfer of A is forbidden (the state space empties).
    'a_define_contradiction': (
        "    v_contra : assume always\n"
        "        (armed = '1' and rst_in = '0' and m_xfer_a = '1') -> (m_re_a /= uf_re_a);\n"),
    'b_never_valid': "    v_b_never_valid : assume always s_valid_b_in = '0';\n",
    'b_never_stalled': "    v_b_never_stalled : assume always m_ready_b_in = '1';\n",
}
CTRL_INJECT = {
    'never_valid': "    v_never_valid : assume always s_valid_in = '0';\n",
    'never_stalled': "    v_never_stalled : assume always m_ready_in = '1';\n",
}


def _data_cover(tmp_path, task, taps, width, cover, extra=''):
    src = param_copy(tmp_path / 'param' / 'fir_complex', taps, width)
    tags = TASK_TAGS[task] | {task}
    srcs = DATA_SOURCES + ([INV] if task == 'data_prove' else [])
    depth = {'data_bmc': bmc_depth(taps), 'data_bmc_nouf': nouf_depth(taps),
             'data_prove': bmc_depth(taps)}[task]
    return run_cover(src, srcs, sby_script(src / SBY, tags), tmp_path, tb=DATA_TB,
                     extra=extra, depth=depth, cover=cover)


def _ctrl_cover(tmp_path, task, taps, width, extra=''):
    src = param_copy(tmp_path / 'param' / 'fir_complex', taps, width)
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


@pytest.mark.parametrize('taps,width', [pytest.param(t, w, id=f'T{t}-W{w}') for t, w in GRID])
def test_data_vacuity_cover(tmp_path, taps, width):
    """In the data_bmc model both channels transfer TAPS+2 beats and B stalls on
    both sides within the BMC horizon (step TAPS+5)."""
    r = _data_cover(tmp_path, 'data_bmc', taps, width, _data_cover_text(taps))
    steps = _assert_reached(r, bmc_depth(taps))
    assert steps[0] == taps + 5, steps
    assert set(uf_decls(sby_model(r, 'cov'))) == {'cmul', 'csum', 'stim_f', 'out_f'}


def test_data_nouf_vacuity_cover(tmp_path):
    """In the non-UF reference run (UF_MODE=false) the cover is reached:
    a_define is an assertion (a_define_chk), so it does not close the state
    space."""
    r = _data_cover(tmp_path, 'data_bmc_nouf', 3, 8, _data_cover_text(3))
    steps = _assert_reached(r, nouf_depth(3))
    assert steps[0] == 3 + 5, steps
    assert uf_decls(sby_model(r, 'cov')) == {}


@pytest.mark.parametrize('task', ['data_bmc', 'data_prove'])
def test_data_vacuity_cover_j(tmp_path, task):
    """The check at the symbolic index happens in the task's model (data_prove:
    with the vunit and expose/connect) with a full window after stalls."""
    taps, width = DEFAULT
    r = _data_cover(tmp_path, task, taps, width, _cover_j_text(taps))
    _assert_reached(r, bmc_depth(taps))


@pytest.mark.parametrize('inject', sorted(DATA_INJECT))
def test_data_vacuity_sensitivity(tmp_path, inject):
    """A contradictory assumption or one that closes B -> data cover unreachable (FAIL)."""
    taps, width = DEFAULT
    r = _data_cover(tmp_path, 'data_bmc', taps, width, _data_cover_text(taps),
                    extra=DATA_INJECT[inject])
    _assert_unreached(r)


@pytest.mark.parametrize('task', ['ctrl_bmc_uf', 'ctrl_bmc_nouf'])
@pytest.mark.parametrize('taps,width', [pytest.param(t, w, id=f'T{t}-W{w}') for t, w in GRID])
def test_ctrl_vacuity_cover(tmp_path, task, taps, width):
    """In the ctrl model traffic flows (TAPS+2 beats in and out) and
    backpressure occurs on both sides."""
    r = _ctrl_cover(tmp_path, task, taps, width)
    _assert_reached(r, 20)


@pytest.mark.parametrize('inject', sorted(CTRL_INJECT))
def test_ctrl_vacuity_sensitivity(tmp_path, inject):
    """An assumption that prevents traffic or backpressure -> ctrl cover unreachable."""
    taps, width = DEFAULT
    r = _ctrl_cover(tmp_path, 'ctrl_bmc_uf', taps, width, extra=CTRL_INJECT[inject])
    _assert_unreached(r)


# ---------------------------------------------------------------- mutations

DUT = 'fir_complex.vhdl'

MUTATIONS = {
    # m1a: control depends on data: s_ready drops for a negative sample.
    'm1a_ready_on_sign': {DUT: [(
        's_ready <= not m_valid or m_ready_in;',
        's_ready <= (not m_valid or m_ready_in) and not s_re_in(WIDTH - 1);')]},
    # m1b: control depends on data: m_valid is hidden for a negative result.
    'm1b_valid_on_sign': {DUT: [(
        'm_valid_out <= m_valid;',
        'm_valid_out <= m_valid and not m_re_out(OW - 1);')]},
    # m2a: data depends on control: the delay line also advances on a rejected
    # beat (s_valid without s_ready).
    'm2a_dl_on_valid': {DUT: [(
        "                if accept = '1' then\n",
        "                if s_valid_in = '1' then\n"
        "                    dl_re <= s_re_in & dl_re(0 to TAPS - 3);\n"
        "                    dl_im <= s_im_in & dl_im(0 to TAPS - 3);\n"
        "                end if;\n"
        "                if accept = '1' then\n")]},
    # m2b: data depends on control: the output register reloads during a
    # stall (data changes while valid and not ready).
    'm2b_reload_on_stall': {DUT: [(
        "                elsif m_ready_in = '1' then\n"
        "                    m_valid <= '0';\n",
        "                elsif m_ready_in = '1' then\n"
        "                    m_valid <= '0';\n"
        "                else\n"
        "                    m_re_out <= sum_re;\n"
        "                    m_im_out <= sum_im;\n")]},
    # m3: dropped beat: s_ready always high, a stalled output is overwritten.
    'm3_drop_beat': {DUT: [(
        's_ready <= not m_valid or m_ready_in;',
        "s_ready <= '1';")]},
    # m4: wrong latency: m_valid one cycle behind the data.
    'm4_latency': {DUT: [
        ('    signal accept  : std_logic;\n',
         "    signal accept  : std_logic;\n    signal m_valid_q : std_logic := '0';\n"),
        ('m_valid_out <= m_valid;', 'm_valid_out <= m_valid_q;'),
        ('        if rising_edge(clk_in) then\n',
         '        if rising_edge(clk_in) then\n            m_valid_q <= m_valid and not rst_in;\n')]},
}

# Expectation per mutation: (data_bmc, ctrl_bmc_uf), the assertions that fail with FAIL status.
EXPECT = {
    'm1a_ready_on_sign': ('PASS', {'a_s_ready_eq'}),
    'm1b_valid_on_sign': ('PASS', {'a_m_valid_eq'}),
    'm2a_dl_on_valid': ({'a_match'}, 'PASS'),
    'm2b_reload_on_stall': ({'a_match'}, 'PASS'),
    'm3_drop_beat': ({'a_match'}, 'PASS'),
    'm4_latency': ({'a_match'}, 'PASS'),
}


def _check_expect(r, exp, task):
    if exp == 'PASS':
        assert r.status == 'PASS', r.log[-3000:]
        return
    assert r.status == 'FAIL', r.log[-3000:]
    fa = failed_asserts(r.log)
    assert fa and set(fa) <= exp, fa
    assert (r.workdir / f'fir_complex_{task}' / 'engine_0' / 'trace.vcd').exists()


@pytest.mark.parametrize('mut', sorted(MUTATIONS))
@pytest.mark.parametrize('task', ['data_bmc', 'ctrl_bmc_uf', 'ctrl_bmc_nouf'])
def test_mutation(tmp_path, mut, task):
    """Control mutations (m1) fail the ctrl property, data mutations (m2-m4) the
    data property; the other property stays PASS. FAIL (not ERROR) on a named
    assertion, and a trace is written."""
    data_exp, ctrl_exp = EXPECT[mut]
    r = _run(tmp_path, task, edits=MUTATIONS[mut])
    _check_expect(r, data_exp if task == 'data_bmc' else ctrl_exp, task)


@pytest.mark.parametrize('mut', sorted(m for m in MUTATIONS if EXPECT[m][0] != 'PASS'))
def test_nouf_mutation_fails(tmp_path, mut):
    """The non-UF reference run (UF_MODE=false, TAPS=3) checks and does not
    prune: a data mutation fails (FAIL) on a_match or a_define_chk (A's output
    deviates from the interpreted FIR reference). If a_define were an
    assumption, A's deviations would be pruned silently. The counterexample is
    found quickly (seconds), so the test is in the default run even though the
    PASS run is heavy."""
    r = _run(tmp_path, 'data_bmc_nouf', 3, 8, edits=MUTATIONS[mut])
    assert r.status == 'FAIL', r.log[-3000:]
    # m4 already shows in A (latency), the others only with B's free sequence.
    expected = {'g_nouf.a_define_chk'} if mut == 'm4_latency' else {'a_match'}
    assert set(failed_asserts(r.log)) == expected, failed_asserts(r.log)


@pytest.mark.parametrize('mut', sorted(m for m in MUTATIONS if EXPECT[m][0] != 'PASS'))
def test_prove_mutation_fails(tmp_path, mut):
    """The invariants do not hide data bugs: data_prove is never PASS.

    At the default depth 3 the basecase is too short for a counterexample for
    most of them and the induction fails (UNKNOWN); m4 already fails there on
    inv_cnt_a (the invariant encodes the latency). At depth bmc_depth (12) the
    basecase finds the bug (FAIL)."""
    r = _run(tmp_path, 'data_prove', edits=MUTATIONS[mut])
    assert r.status in ('UNKNOWN', 'FAIL'), r.log[-3000:]
    r = _run(tmp_path / 'deep', 'data_prove', edits=MUTATIONS[mut],
             prove_depth=bmc_depth(DEFAULT[0]))
    assert r.status == 'FAIL', r.log[-3000:]
    fa = failed_asserts(r.log)
    assert fa and set(fa) <= PROVE_ASSERTS, r.log[-3000:]


@pytest.mark.parametrize('mut', sorted(m for m in MUTATIONS if EXPECT[m][1] != 'PASS'))
def test_ctrl_prove_mutation_fails(tmp_path, mut):
    """A control mutation is not proven in the ctrl_prove task; at depth 20 the
    basecase fails on a named assertion (FAIL)."""
    r = _run(tmp_path, 'ctrl_prove_uf', edits=MUTATIONS[mut])
    assert r.status in ('UNKNOWN', 'FAIL'), r.log[-3000:]
    r = _run(tmp_path / 'deep', 'ctrl_prove_uf', edits=MUTATIONS[mut], prove_depth=20)
    assert r.status == 'FAIL', r.log[-3000:]
    assert set(failed_asserts(r.log)) <= CTRL_ASSERTS and failed_asserts(r.log)


# ---------------------------------------------------------------- assumptions are needed

NO_A_REF_RATE = {DATA_TB: [(
    "    a_ref_rate : assume always\n"
    "        (rst_in = '0') -> (s_valid_a_in = '1' and m_ready_a_in = '1');\n", '')]}
NO_WRAP = {DATA_TB: [(
    "    a_no_wrap : assume always\n"
    "        (rst_in = '0') -> (icnt_a /= x\"FFFF\");\n", '')]}


def test_a_ref_rate_needed(tmp_path):
    """Without a_ref_rate out_f stays undefined at indices A did not produce:
    a_match fails (FAIL, not ERROR)."""
    r = _run(tmp_path, 'data_bmc', edits=NO_A_REF_RATE)
    assert r.status == 'FAIL', r.log[-3000:]
    assert failed_asserts(r.log) == ['a_match'], r.log[-3000:]


def test_a_no_wrap_needed_for_prove(tmp_path):
    """Without the counter wrap bound the induction does not succeed (UNKNOWN):
    in a wrapped state the beat indices get mixed up. The bound does not affect BMC."""
    r = _run(tmp_path, 'data_prove', edits=NO_WRAP)
    assert r.status == 'UNKNOWN', r.log[-3000:]
    assert 'Temporal induction failed' in r.log

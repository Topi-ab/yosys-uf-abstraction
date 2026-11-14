"""vhdl_control_independence_setattr: DUT untouched, UF mark set with setattr (dsp2.sby, task uf).

- Task groups: nouf (UF_MODE=false: the testbench marks switched off with
  the uf_disable attribute), tbuf (the testbench's stim_f/out_f
  as UFs, DUT interpreted) and uf (tbuf + the DUT's $mul = mul16).
- sby tasks: bmc_nouf / bmc_uf / prove_nouf / prove_uf PASS.
- a_match checks B's beat at the symbolic index j (anyconst), which is
  equivalent to checking every beat and makes the property inductive.
- Helper invariants: tb_dsp_formal_inv.psl (a PSL vunit bound to the testbench
  architecture, only in the prove tasks, inv tag). The vunit contains only the
  helper invariants and their helper structures (a third DUT instance c, def_a);
  they are asserts, so they are proven themselves. The set is minimal: removing
  any one invariant makes the induction fail.
- Mutations M1/M3/M4 are caught both in bmc_uf and in the prove tasks.
- The bmc_tbuf-based tests are heavy (@pytest.mark.validation, not part of the
  default run):
  ./tc.sh pytest -m validation -n auto tests/vhdl_control_independence_setattr
  bmc_tbuf takes about 17 s at depth 8 with bitwuzla (much longer with yices).
- test_tbuf_independent_of_dut_operator (the actual independence proof):
  bmc_tbuf PASSes on a copy of the DUT with * -> +, and the cover is reached at
  the same depth (validation).
- test_uf_faster_than_tbuf: bmc_uf is at least 10x faster than bmc_tbuf at the
  same depth (validation).
- SMT2 checks: the DUT's $mul is truly uninterpreted (declare-fun |mul16|).
- Final model: sby's own model build (design_prep.ys: opt_clean, opt -fast
  without -keepdc) runs after the [script] section, so its select guards do not
  see a mark lost there. test_bmc therefore checks sby's own
  model/design_smt2.smt2.
- Vacuity: a cover variant shows that both channels produce checked beats
  (bmc_uf and bmc_nouf), i.e. the PASS is not empty; a sensitivity test
  shows that the cover detects contradictory assumptions.
"""
import re
import shutil
import time
from pathlib import Path

import pytest

from conftest import (COVER_DEEP, VACUITY_INJECT, cover_steps, failed_asserts, mutated_copy,
                      reachable_modules, run_cover, run_sby, run_yosys, sby_model, smt2_module_sections,
                      uf_decls)
from conftest import sby_script as _sby_script

HERE = Path(__file__).resolve().parent

SOURCES = ['dsp.vhdl', 'tb_stim_formal.vhdl', 'tb_out_formal.vhdl', 'tb_dsp_formal.vhdl',
           'tb_dsp_formal_inv.psl']
# Helper invariants (tb_dsp_formal_inv.psl); in the model the vunit name is the prefix.
INVARIANTS = ['inv_cnt_a', 'inv_cnt_b', 'inv_order', 'inv_bound']
INV = 'tb_dsp_formal_inv.psl'
UF_SETATTR = 'setattr -set uf_instance "mul16" dsp_Brtl/t:$mul'
# In the non-UF tasks (UF_MODE=false) a_define is an assert (g_nouf branch).
A_DEFINE_CHK = 'g_nouf.a_define_chk'

# sby [tasks] lines: task -> groups
TASK_GROUPS = {
    'bmc_nouf': {'bmc', 'nouf', 'plain'},
    'bmc_tbuf': {'bmc', 'tbuf', 'plain'},
    'bmc_uf': {'bmc', 'uf', 'tbuf', 'plain'},
    'prove_nouf': {'prove', 'nouf', 'inv'},
    'prove_uf': {'prove', 'uf', 'tbuf', 'inv'},
}


def task_depth(task, sby_file=HERE / 'dsp2.sby'):
    """The task's depth from the [options] section of dsp2.sby (given per task)."""
    m = re.search(rf'^{task}:\s+depth (\d+)\s*$', Path(sby_file).read_text(), flags=re.M)
    assert m, task
    return int(m.group(1))


TBUF_DEPTH = task_depth('bmc_tbuf')

# Change of the DUT datapath semantics (* -> +), control unchanged.
MUT_DUT_ADD = {'dsp.vhdl': [('resize(data_in * data_in, 16)', 'resize(data_in + data_in, 16)')]}

# Control mutations (the same as in vhdl_control_independence).
MUTATIONS = {
    # M3: s1 is captured on v1 instead of valid_in -> wrong beat in the pipeline.
    'M3_capture_on_v1': {'dsp.vhdl': [(
        "if valid_in = '1' then\n                    s1 <= resize(data_in * data_in, 16);",
        "if v1 = '1' then\n                    s1 <= resize(data_in * data_in, 16);")]},
    # M4: valid_out one cycle too early (latency).
    'M4_latency': {'dsp.vhdl': [('valid_out <= v1;', 'valid_out <= valid_in;')]},
}

# M1: the s1 stage is skipped, data_out <= the product of the current data_in
# (the data is read on the cycle after valid). Visible because the testbench
# drives data_in freely on valid = '0' cycles (data_b_idle_in); if stim_f(icnt)
# stayed constant between beats, M1 would go unnoticed.
MUT_SKIP_S1 = {'dsp.vhdl': [
    ('                    s1 <= resize(data_in * data_in, 16);\n', '                    null;\n'),
    ('                    data_out <= s1;\n',
     '                    data_out <= resize(data_in * data_in, 16);\n')]}


def sby_script(task, sby_file=HERE / 'dsp2.sby'):
    """The [script] of dsp2.sby for task `task` (the same as sby would run).

    Read from the sby file so that the test follows it (e.g. added keep
    attributes and select guards). 'plugin -i ghdl' is replaced by
    run_yosys(ghdl=True).
    """
    return [l for l in _sby_script(sby_file, {task} | TASK_GROUPS[task])
            if not l.startswith('plugin ')]


def test_sby_uf_script_marks_dut_mul():
    """Starting point for the other tests: the uf task script contains the DUT setattr."""
    uf = sby_script('bmc_uf')
    assert UF_SETATTR in uf
    assert UF_SETATTR not in sby_script('bmc_nouf')
    assert UF_SETATTR not in sby_script('bmc_tbuf')
    # UF vs. non-UF is selected by the generic (-gUF_MODE below), which drives
    # the uf_disable attribute of the testbench marks; sby does not remove
    # marks.
    assert 'setattr -unset' not in (HERE / 'dsp2.sby').read_text()
    for task in TASK_GROUPS:
        assert not [l for l in sby_script(task) if 'uf_disable' in l and 'setattr' in l], task
    # Helper invariants only in the prove tasks; the property is not edited in sby.
    for task in TASK_GROUPS:
        ghdl = [l for l in sby_script(task) if l.startswith('ghdl ')]
        assert len(ghdl) == 1, ghdl
        assert (INV in ghdl[0]) == task.startswith('prove'), (task, ghdl)
        uf_mode = 'false' if 'nouf' in TASK_GROUPS[task] else 'true'
        assert f' -gUF_MODE={uf_mode} ' in ghdl[0], (task, ghdl)
    assert 'chformal' not in (HERE / 'dsp2.sby').read_text()
    assert any(l.startswith('ghdl ') for l in uf)
    assert any(l.startswith('prep -top tb_dsp_formal') for l in uf)


# ---------------------------------------------------------------- sby tasks

@pytest.mark.parametrize('task', ['bmc_nouf', 'bmc_uf'])
def test_bmc(sby, task):
    """PASS plus a check of sby's final model (not of the [script] section state):
    in the uf task exactly one declaration per symbol (mul16, stim_f, out_f) and
    no bvmul in the DUT, in the non-UF task no UF declarations at all."""
    r = sby(HERE, 'dsp2.sby', task)
    assert r.status == 'PASS', r.log[-3000:]
    assert r.uf_warnings == [], r.uf_warnings
    smt = sby_model(r, f'dsp2_{task}')
    if task == 'bmc_uf':
        decls = [l for l in smt.splitlines() if 'declare-fun |mul16|' in l]
        assert len(decls) == 1, decls
        assert {k: len(v) for k, v in uf_decls(smt).items()} == \
            {'mul16': 1, 'stim_f': 1, 'out_f': 1}, uf_decls(smt)
        assert reachable_modules(smt) == {'tb_dsp_formal', 'dsp_Brtl'}
        sections = smt2_module_sections(smt)
        assert 'dsp_Brtl' in sections, list(sections)
        assert 'bvmul' not in sections['dsp_Brtl']
        assert '|mul16|' in sections['dsp_Brtl']
    else:
        assert 'mul16' not in smt
        assert uf_decls(smt) == {}
        assert reachable_modules(smt) == {'tb_dsp_formal', 'dsp_Brtl', 'tb_stim_formal_Brtl',
                                          'tb_out_formal_Brtl'}


@pytest.mark.parametrize('task', ['prove_nouf', 'prove_uf'])
def test_prove(sby, task):
    """k-induction with the helper invariants (tb_dsp_formal_inv.psl): PASS.

    The final model contains the testbench a_match (neither replaced nor
    removed) and exactly the vunit's invariants, the symbolic index j is
    anyconst, and in prove_uf the UFs are the same as in bmc_uf (the vunit's j
    instances use the same symbols).
    """
    r = sby(HERE, 'dsp2.sby', task)
    assert r.status == 'PASS', r.log[-3000:]
    assert 'successful proof by k-induction' in r.log, r.log[-3000:]
    assert r.uf_warnings == [], r.uf_warnings
    smt = sby_model(r, f'dsp2_{task}')
    asserts = re.findall(r'^; yosys-smt2-assert \d+ (\S+)', smt, flags=re.M)
    expected = ['a_match'] + [f'tb_dsp_formal_inv.{n}' for n in INVARIANTS]
    if task == 'prove_nouf':
        expected.append(A_DEFINE_CHK)
    assert sorted(asserts) == sorted(expected), asserts
    assert 'yosys-smt2-anyconst' in smt
    if task == 'prove_uf':
        assert {k: len(v) for k, v in uf_decls(smt).items()} == \
            {'mul16': 1, 'stim_f': 1, 'out_f': 1}, uf_decls(smt)
        assert reachable_modules(smt) == {'tb_dsp_formal', 'dsp_Brtl'}
        assert 'bvmul' not in smt2_module_sections(smt)['dsp_Brtl']
    else:
        assert uf_decls(smt) == {}


# ---------------------------------------------------------------- mutations

@pytest.mark.parametrize('mut', sorted(MUTATIONS))
def test_mutation_fails(tmp_path, mut):
    """A control mutation is caught in the UF run: bmc_uf FAIL in a_match, trace written."""
    src = mutated_copy(HERE, tmp_path / 'mut' / HERE.name, MUTATIONS[mut])
    r = run_sby(src, 'dsp2.sby', 'bmc_uf', tmp_path)
    assert r.status == 'FAIL', r.log[-3000:]
    assert failed_asserts(r.log) == ['a_match'], r.log[-3000:]
    assert (r.workdir / 'dsp2_bmc_uf' / 'engine_0' / 'trace.vcd').exists()


@pytest.mark.parametrize('task', ['prove_nouf', 'prove_uf'])
@pytest.mark.parametrize('mut', sorted(MUTATIONS))
def test_prove_mutation_fails(tmp_path, mut, task):
    """The invariants do not mask control bugs: the mutation fails the prove task
    in the basecase (FAIL, not UNKNOWN). M3 fails a_match; M4 already fails
    inv_cnt_a, because that invariant encodes the DUT latency."""
    src = mutated_copy(HERE, tmp_path / 'mut' / HERE.name, MUTATIONS[mut])
    r = run_sby(src, 'dsp2.sby', task, tmp_path)
    assert r.status == 'FAIL', r.log[-3000:]
    expected = {'a_match'} | {f'tb_dsp_formal_inv.{n}' for n in INVARIANTS}
    if task == 'prove_nouf':
        expected.add(A_DEFINE_CHK)
    assert failed_asserts(r.log) and set(failed_asserts(r.log)) <= expected, r.log[-3000:]


@pytest.mark.parametrize('task', ['bmc_uf', 'prove_uf'])
def test_skip_s1_fails(tmp_path, task):
    """M1 fails a_match in the UF tasks (prove_uf: basecase, depth 4)."""
    src = mutated_copy(HERE, tmp_path / 'mut' / HERE.name, MUT_SKIP_S1)
    r = run_sby(src, 'dsp2.sby', task, tmp_path)
    assert r.status == 'FAIL', r.log[-3000:]
    # prove: basecase and induction may both report the same assertion
    assert set(failed_asserts(r.log)) == {'a_match'}, r.log[-3000:]


@pytest.mark.parametrize('task', ['bmc_nouf', 'prove_nouf'])
def test_skip_s1_nouf_fails(tmp_path, task):
    """In the non-UF run M1 fails a_define_chk: A reads the next beat's data,
    so its output differs from the interpreted out_f. As an assume in the
    non-UF run, a_define would silently prune these paths (PASS, cover
    unreached); UF_MODE=false makes the condition an assert."""
    src = mutated_copy(HERE, tmp_path / 'mut' / HERE.name, MUT_SKIP_S1)
    r = run_sby(src, 'dsp2.sby', task, tmp_path)
    assert r.status == 'FAIL', r.log[-3000:]
    assert A_DEFINE_CHK in failed_asserts(r.log), r.log[-3000:]


# ---------------------------------------------------------------- SMT2

def _copy_sources(dst):
    dst.mkdir(parents=True, exist_ok=True)
    for f in SOURCES:
        shutil.copy2(HERE / f, dst / f)
    return dst


def _smt2(tmp_path, uf):
    work = _copy_sources(tmp_path / ('uf' if uf else 'nouf'))
    script = sby_script('bmc_uf' if uf else 'bmc_nouf')
    script += ['tee -q -o sel.txt select -list a:uf_instance=mul16',
               'write_smt2 -bv out.smt2']
    r = run_yosys(';\n'.join(script), work, ghdl=True)
    assert r.returncode == 0, r.log
    return r, (work / 'out.smt2').read_text(), (work / 'sel.txt').read_text()


@pytest.fixture
def uf_model_smt2(tmp_path):
    return _smt2(tmp_path, uf=True)


@pytest.fixture
def nouf_smt2(tmp_path):
    return _smt2(tmp_path, uf=False)


_module_sections = smt2_module_sections


def test_uf_single_declare_fun(uf_model_smt2):
    _, smt, _ = uf_model_smt2
    decls = [l for l in smt.splitlines() if 'declare-fun |mul16|' in l]
    assert len(decls) == 1, decls
    assert re.search(r'\(declare-fun \|mul16\| \(\(_ BitVec 16\) \(_ BitVec 16\)\) \(_ BitVec 16\)\)',
                     decls[0]), decls[0]


def test_uf_declare_precedes_use(uf_model_smt2):
    _, smt, _ = uf_model_smt2
    lines = smt.splitlines()
    uses = [i for i, l in enumerate(lines) if '|mul16|' in l]
    decl = next(i for i in uses if 'declare-fun |mul16|' in lines[i])
    assert len(uses) >= 2, 'mul16 declared but not used'
    assert decl == uses[0], (decl, uses[0])


def test_uf_no_bvmul_in_dut(uf_model_smt2):
    _, smt, _ = uf_model_smt2
    sections = _module_sections(smt)
    assert 'dsp_Brtl' in sections, list(sections)
    assert 'bvmul' not in sections['dsp_Brtl']
    assert '|mul16|' in sections['dsp_Brtl']


def _reachable_count(smt, term):
    sections = smt2_module_sections(smt)
    return sum(sections[m].count(term) for m in reachable_modules(smt))


def test_bvmul_count(uf_model_smt2, nouf_smt2):
    """bvmul terms only in the sections reachable from the top: the UF box modules
    are still written to the file, but they are dead text."""
    _, uf, _ = uf_model_smt2
    _, nouf, _ = nouf_smt2
    assert _reachable_count(nouf, 'bvmul') == 4
    assert _reachable_count(uf, 'bvmul') == 0
    assert 'mul16' not in nouf


def test_marked_cells(uf_model_smt2, nouf_smt2):
    """The marked set is exactly the single $mul of dsp_Brtl (no testbench multiplications)."""
    _, _, sel = uf_model_smt2
    marked = [l.strip() for l in sel.splitlines() if l.strip()]
    assert len(marked) == 1, marked
    assert marked[0].startswith('dsp_Brtl/'), marked
    # in the non-UF run nothing is marked mul16
    assert not [l for l in nouf_smt2[2].splitlines() if l.strip()]


def test_marked_cell_is_mul(tmp_path):
    work = _copy_sources(tmp_path / 'sel')
    r = run_yosys(';\n'.join(sby_script('bmc_uf') + [
        'tee -q -o all.txt select -list a:uf_instance=mul16',
        'tee -q -o mul.txt select -list a:uf_instance=mul16 t:$mul %i',
        'tee -q -o dutmul.txt select -list dsp_Brtl/t:$mul']), work, ghdl=True)
    assert r.returncode == 0, r.log
    read = lambda f: sorted(l.strip() for l in (work / f).read_text().splitlines() if l.strip())
    assert read('all.txt') == read('mul.txt') == read('dutmul.txt')
    assert len(read('dutmul.txt')) == 1


def test_no_uf_warnings(uf_model_smt2, nouf_smt2):
    """All marks (the DUT's $mul and the testbench hierarchical cells) are emitted:
    no ignored mark in either task."""
    assert uf_model_smt2[0].uf_warnings == [], uf_model_smt2[0].uf_warnings
    assert nouf_smt2[0].uf_warnings == [], nouf_smt2[0].uf_warnings


# ---------------------------------------------------------------- vacuity

def _cover(tmp_path, task, extra='', src=HERE, **kw):
    kw.setdefault('depth', task_depth(task))
    return run_cover(src, SOURCES, ['plugin -i ghdl'] + sby_script(task), tmp_path,
                     extra=extra, **kw)


# a_match must not be vacuous: its antecedent holds, i.e. B produces the
# symbolic beat j >= 2, which A has produced (and a_define has defined) earlier.
COVER_J = ("    c_b_checked_j : cover {armed = '1' and rst_in = '0' and yvalid_b = '1' and "
           "ocnt_b = j and j >= 2 and j < ocnt_a};\n")


@pytest.mark.parametrize('task', ['bmc_uf', 'prove_uf'])
def test_vacuity_cover_j(tmp_path, task):
    """The symbolic-index check is reached in the task's model (prove_uf: with the
    vunit): B produces beat j after A."""
    r = _cover(tmp_path, task, cover=COVER_J, depth=20)
    assert r.status == 'PASS', r.log[-3000:]
    assert 'Reached cover statement' in r.log, r.log[-3000:]
    assert 'Unreached cover' not in r.log, r.log[-3000:]
    assert r.uf_warnings == [], r.uf_warnings


def test_vacuity_cover_j_sensitivity(tmp_path):
    """Sensitivity: an assumption that closes channel B -> COVER_J is unreachable."""
    r = _cover(tmp_path, 'bmc_uf', VACUITY_INJECT['b_never_valid'], cover=COVER_J, depth=20)
    assert r.status == 'FAIL', r.log[-3000:]
    assert 'Unreached cover statement' in r.log, r.log[-3000:]


# bmc_tbuf in cover mode is as heavy as bmc_tbuf itself (the sensitivity test
# needs unreachability over the whole depth): validation marker.
VALIDATION_TBUF = pytest.param('bmc_tbuf', marks=pytest.mark.validation)


# Expected UF declarations in the cover run's model (symbol -> count), as in test_bmc.
COVER_UF_DECLS = {
    'bmc_uf': {'mul16': 1, 'stim_f': 1, 'out_f': 1},
    'bmc_nouf': {},
    'bmc_tbuf': {'stim_f': 1, 'out_f': 1},
}


@pytest.mark.parametrize('task', ['bmc_uf', 'bmc_nouf', VALIDATION_TBUF])
def test_vacuity_cover(tmp_path, task):
    """Under the task's assumptions both channels produce checked beats within
    the task's depth, and the first step reached + 2 <= depth.

    The cover run's own model is checked: the same UF declarations as in the
    corresponding bmc run (test_bmc), so that the cover does not prove something
    about a different model.
    """
    r = _cover(tmp_path, task)
    assert r.status == 'PASS', r.log[-3000:]
    assert 'Reached cover statement' in r.log, r.log[-3000:]
    assert 'Unreached cover' not in r.log, r.log[-3000:]
    assert cover_steps(r.log)[0] + 2 <= task_depth(task), cover_steps(r.log)
    assert r.uf_warnings == [], r.uf_warnings
    smt = sby_model(r, 'cov')
    assert {k: len(v) for k, v in uf_decls(smt).items()} == COVER_UF_DECLS[task], uf_decls(smt)
    if task == 'bmc_uf':
        assert re.search(r'^\(declare-fun \|mul16\| \(\(_ BitVec 16\) \(_ BitVec 16\)\) '
                         r'\(_ BitVec 16\)\)', smt, flags=re.M), uf_decls(smt)
        assert 'bvmul' not in smt2_module_sections(smt)['dsp_Brtl']


@pytest.mark.parametrize('task', ['bmc_uf', 'bmc_nouf'])
def test_vacuity_cover_deep(tmp_path, task):
    """The deep cover (ocnt_a >= 16, ocnt_b >= 3) is reached within the task's depth:
    at step 19 at the earliest, the last step of depth 20."""
    r = _cover(tmp_path, task, cover=COVER_DEEP)
    assert r.status == 'PASS', r.log[-3000:]
    assert 'Unreached cover' not in r.log, r.log[-3000:]
    assert cover_steps(r.log) and cover_steps(r.log)[0] < task_depth(task), cover_steps(r.log)
    assert r.uf_warnings == [], r.uf_warnings


@pytest.mark.parametrize('task', ['bmc_uf', VALIDATION_TBUF])
@pytest.mark.parametrize('inject', sorted(VACUITY_INJECT))
def test_vacuity_cover_sensitivity(tmp_path, inject, task):
    """Sensitivity: a contradictory / channel-B-closing assumption -> cover unreachable (FAIL).
    Shows that test_vacuity_cover would detect an empty state space."""
    r = _cover(tmp_path, task, VACUITY_INJECT[inject])
    assert r.status == 'FAIL', r.log[-3000:]
    assert 'Unreached cover statement' in r.log, r.log[-3000:]


# ---------------------------------------------------------------- bmc_tbuf (validation)

# Heavy runs (validation marker), not part of the default run.
# bmc_tbuf takes about 17 s at depth 8 with bitwuzla and much longer with other solvers, so a longer limit
# than run_sby's default timeout (1800 s) is used.
SLOW_TIMEOUT = 4 * 3600


def _timed_sby(src, task, tmp_path):
    t0 = time.monotonic()
    r = run_sby(src, 'dsp2.sby', task, tmp_path, timeout=SLOW_TIMEOUT)
    return r, time.monotonic() - t0


@pytest.mark.validation
def test_tbuf_independent_of_dut_operator(tmp_path):
    """The actual independence proof: the DUT operator is interpreted and its data
    comes from the testbench UFs (bmc_tbuf). The * -> + copy PASSes, and the
    same copy reaches the cover at the same depth, so the PASS is not vacuous.

    Validation marker: not part of the default run (pytest.ini).
    """
    src = mutated_copy(HERE, tmp_path / 'mut' / HERE.name, MUT_DUT_ADD)
    r = run_sby(src, 'dsp2.sby', 'bmc_tbuf', tmp_path, timeout=SLOW_TIMEOUT)
    assert r.status == 'PASS', r.log[-3000:]
    smt = sby_model(r, 'dsp2_bmc_tbuf')
    assert set(uf_decls(smt)) == {'stim_f', 'out_f'}, uf_decls(smt)
    assert 'bvadd' in smt2_module_sections(smt)['dsp_Brtl']
    c = _cover(tmp_path / 'c', 'bmc_tbuf', src=src)
    assert c.status == 'PASS', c.log[-3000:]
    assert 'Reached cover statement' in c.log, c.log[-3000:]
    assert cover_steps(c.log)[0] + 2 <= TBUF_DEPTH, cover_steps(c.log)


@pytest.mark.validation
def test_uf_faster_than_tbuf(tmp_path):
    """bmc_uf is at least 10x faster than bmc_tbuf at the same depth.

    Validation marker: not part of the default run (pytest.ini).

    bmc_tbuf (the DUT's $mul interpreted on UF data) PASSes, then bmc_uf on a copy
    whose depth is set to bmc_tbuf's depth. The time is the wall-clock time of
    the sby run. The UF run is compared with bmc_tbuf, not with the fully
    non-UF run (whose testbench data is a simple function of the counters).
    """
    r, t_tbuf = _timed_sby(HERE, 'bmc_tbuf', tmp_path / 'tbuf')
    assert r.status == 'PASS', r.log[-3000:]
    smt = sby_model(r, 'dsp2_bmc_tbuf')
    assert set(uf_decls(smt)) == {'stim_f', 'out_f'}, uf_decls(smt)
    assert 'bvmul' in smt2_module_sections(smt)['dsp_Brtl']
    src = mutated_copy(HERE, tmp_path / 'same_depth' / HERE.name, {'dsp2.sby': [
        ('bmc_uf:         depth 20', f'bmc_uf:         depth {TBUF_DEPTH}')]})
    u, t_uf = _timed_sby(src, 'bmc_uf', tmp_path / 'uf')
    assert u.status == 'PASS', u.log[-3000:]
    print(f'bmc_tbuf {t_tbuf:.1f} s, bmc_uf {t_uf:.1f} s, depth {TBUF_DEPTH}, '
          f'ratio {t_tbuf / t_uf:.1f}')
    assert t_tbuf >= 10 * t_uf, (t_tbuf, t_uf)

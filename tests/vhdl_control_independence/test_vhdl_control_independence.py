"""vhdl_control_independence: control independence, mark in the source code.

All uf_instance marks are on hierarchical cells (u_f in dsp_Brtl_*, and the
testbench's u_stim_a/b and u_out_a/b). write_smt2 -bv emits one declare-fun per
symbol, and the box outputs are bound to the call by equations (task bmc).
bmc_nouf (-gUF_MODE=false) switches all marks off with the uf_disable
attribute (testbench, vunit and, through the generic, the DUT) and runs every
box with its own architecture.

What the tests cover:
- test_bmc: end to end from the VHDL attribute to declare-fun; one declare-fun
  per symbol before its first use, signature, _h a/b. test_vacuity_cover*:
  both channels actually produce checked beats.
- test_mutation_fails / test_prove_mutation_fails: control mutations (M1, M3,
  M4) are caught under abstraction.
- test_dsp_f_semantics_not_in_model: a structural property, NOT a proof of
  independence (dsp_f's architecture is dead text under the UF), and
  test_nouf_mutation_fails (in the non-UF run a_define is an assert,
  UF_MODE=false).
- test_a_ref_rate_needed_*: the a_ref_rate assumption is required.

prove (k-induction) succeeds with helper invariants (tb_dsp_formal_inv.psl, a
vunit, only in the prove task). a_match is an ordinary testbench assert that
checks B's beat at the symbolic index j (anyconst); the vunit contains only the
helper invariants and their helper structures. The set is minimal: removing
any one invariant makes the induction fail.
"""
import re
from pathlib import Path

import pytest

from conftest import (COVER_DEEP, VACUITY_INJECT, cover_steps, failed_asserts, mutated_copy,
                      run_cover, run_sby, run_yosys, sby_model, sby_script, uf_decls)
from conftest import reachable_modules as _reachable_modules
from conftest import smt2_module_sections as _smt2_module_sections

HERE = Path(__file__).resolve().parent

# The DUT has the generic UF_MODE (the testbench passes it with a generic map),
# so GHDL names the DUT module with a hash of the generic values
# (dsp_Brtl_<sha1>). The tests compare module names without the hash.
_HASH_RE = re.compile(r'_[0-9a-f]{40}$')


def _norm(name):
    return _HASH_RE.sub('', name)


def reachable_modules(text):
    return {_norm(m) for m in _reachable_modules(text)}


def smt2_module_sections(text):
    out = {}
    for m, t in _smt2_module_sections(text).items():
        assert _norm(m) not in out, m
        out[_norm(m)] = t
    return out


SOURCES = ['dsp_f.vhdl', 'dsp.vhdl', 'tb_stim_formal.vhdl', 'tb_out_formal.vhdl',
           'tb_dsp_formal.vhdl']

# sby [tasks] lines: task -> tags
TASK_TAGS = {
    'bmc': {'bmc', 'uf', 'plain'},
    'prove': {'prove', 'uf', 'inv'},
    'bmc_nouf': {'bmc_nouf', 'nouf', 'plain'},
}

INV = 'tb_dsp_formal_inv.psl'
INVARIANTS = ['inv_cnt_a', 'inv_cnt_b', 'inv_order', 'inv_bound']
# Assertions of the prove model: the testbench a_match + the vunit helper invariants.
PROVE_ASSERTS = {'a_match'} | {f'tb_dsp_formal_inv.{n}' for n in INVARIANTS}
ASSERT_RE = re.compile(r'^; yosys-smt2-assert \d+ (\S+)', flags=re.M)

UF_DECL_16 = '(declare-fun |{}| ((_ BitVec 16)) (_ BitVec 16))'

# UF box instances that must not produce an _h member or a yosys-smt2-cell line
UF_CELLS = ['u_f', 'u_stim_a', 'u_stim_b', 'u_out_a', 'u_out_b']
UF_MODULES = ['dsp_f_Brtl', 'tb_stim_formal_Brtl', 'tb_out_formal_Brtl']

# Change of the DUT datapath semantics (* -> +): does not touch control.
MUT_DSP_F_ADD = {'dsp_f.vhdl': [('resize(data_in * data_in, 16)', 'resize(data_in + data_in, 16)')]}

# Remove a_ref_rate from the testbench.
NO_A_REF_RATE = {'tb_dsp_formal.vhdl': [(
    "    a_ref_rate : assume always\n"
    "        (rst_in = '0') -> (valid_a_in = '1');\n", '')]}


def _code(line):
    """SMT2 line without its trailing comment."""
    return line.split(' ;', 1)[0]


# ---------------------------------------------------------------- sby tasks

def test_bmc(sby):
    """Main end-to-end test: VHDL label attribute -> declare-fun -> PASS.

    Checks sby's final model (design_smt2.smt2), not the state of the [script] section.
    """
    r = sby(HERE, 'dsp2.sby', 'bmc')
    assert r.status == 'PASS', r.log[-3000:]
    assert r.uf_warnings == [], r.uf_warnings
    smt = sby_model(r, 'dsp2_bmc')

    # One declare-fun per symbol, signature from the port widths.
    decls = uf_decls(smt)
    assert set(decls) == {'dsp_f', 'stim_f', 'out_f'}, decls
    for sym, lines in decls.items():
        assert [_code(l) for l in lines] == [UF_DECL_16.format(sym)], lines
    # The comment names the first user and the port layout.
    assert re.search(
        r'; uf_instance, first use: dsp_Brtl_[0-9a-f]{40}\.u_f \(module dsp_f_Brtl\): '
        r'args data_in\[16\] -> data_out\[15:0\]$', decls['dsp_f'][0]), decls['dsp_f']

    # Declaration in the right section and before the first use.
    sections = smt2_module_sections(smt)
    assert UF_DECL_16.format('dsp_f') in sections['dsp_Brtl']
    for sym in ('stim_f', 'out_f'):
        assert UF_DECL_16.format(sym) in sections['tb_dsp_formal']
        # two instances -> at least two calls
        assert sections['tb_dsp_formal'].count(f'(|{sym}|') >= 2, sym
    assert sections['dsp_Brtl'].count('(|dsp_f|') >= 1
    lines = smt.splitlines()
    for sym in decls:
        uses = [i for i, l in enumerate(lines) if f'|{sym}|' in l and not l.startswith(';')]
        assert _code(lines[uses[0]]) == UF_DECL_16.format(sym), (sym, lines[uses[0]])

    # No hierarchy references to UF boxes (smtbmc would refer to non-existent state).
    assert not re.search(r'^; yosys-smt2-cell (%s) ' % '|'.join(UF_MODULES), smt, flags=re.M)
    for c in UF_CELLS:
        assert f'_h {c}|' not in smt, c
    # Unmarked DUT instances stay interpreted.
    assert '_h a|' in sections['tb_dsp_formal']
    assert '_h b|' in sections['tb_dsp_formal']
    assert reachable_modules(smt) == {'tb_dsp_formal', 'dsp_Brtl'}


def test_bmc_nouf(sby):
    """Comparison run: marks switched off (UF_MODE=false), no UF declarations."""
    r = sby(HERE, 'dsp2.sby', 'bmc_nouf')
    assert r.status == 'PASS', r.log[-3000:]
    assert r.uf_warnings == [], r.uf_warnings
    smt = sby_model(r, 'dsp2_bmc_nouf')
    assert uf_decls(smt) == {}
    assert reachable_modules(smt) == {'tb_dsp_formal', 'dsp_Brtl', *UF_MODULES}


def test_sby_sources():
    """Helper invariants only in the prove task; the property is not edited in sby."""
    for task, tags in TASK_TAGS.items():
        ghdl = [l for l in sby_script(HERE / 'dsp2.sby', tags | {task}) if l.startswith('ghdl ')]
        assert len(ghdl) == 1, ghdl
        assert (INV in ghdl[0]) == (task == 'prove'), (task, ghdl)
        uf_mode = 'false' if 'nouf' in tags else 'true'
        assert f' -gUF_MODE={uf_mode} ' in ghdl[0], (task, ghdl)
    text = (HERE / 'dsp2.sby').read_text()
    assert 'chformal' not in text
    # sby neither removes nor sets marks; the choice is in the generic.
    assert 'setattr' not in text


def test_prove(sby):
    """k-induction with helper invariants: PASS at depth 4 (k = 3 is enough).

    The model contains the UFs (the vunit's j instances use the same symbols)
    and, as assertions, the testbench a_match and exactly the vunit's helper
    invariants.
    """
    r = sby(HERE, 'dsp2.sby', 'prove')
    assert r.status == 'PASS', r.log[-3000:]
    assert 'successful proof by k-induction' in r.log, r.log[-3000:]
    assert r.uf_warnings == [], r.uf_warnings
    smt = sby_model(r, 'dsp2_prove')
    assert set(ASSERT_RE.findall(smt)) == PROVE_ASSERTS, ASSERT_RE.findall(smt)
    assert len(ASSERT_RE.findall(smt)) == len(PROVE_ASSERTS)
    decls = uf_decls(smt)
    assert {k: [_code(l) for l in v] for k, v in decls.items()} == \
        {s: [UF_DECL_16.format(s)] for s in ('dsp_f', 'stim_f', 'out_f')}, decls
    assert reachable_modules(smt) == {'tb_dsp_formal', 'dsp_Brtl'}
    assert 'yosys-smt2-anyconst' in smt


# ---------------------------------------------------------------- mutations

MUTATIONS = {
    # M3: s1 is captured on v1 instead of valid_in -> wrong beat in the pipeline.
    'M3_capture_on_v1': {'dsp.vhdl': [(
        "if valid_in = '1' then\n                    s1 <= f_out;",
        "if v1 = '1' then\n                    s1 <= f_out;")]},
    # M4: valid_out one cycle too early (latency).
    'M4_latency': {'dsp.vhdl': [('valid_out <= v1;', 'valid_out <= valid_in;')]},
    # M1: the s1 stage is skipped, data_out <= f_out (the data is read on the
    # cycle after valid). Visible because data_in is free on valid = '0' cycles.
    'M1_skip_s1': {'dsp.vhdl': [
        ('                    s1 <= f_out;\n', '                    null;\n'),
        ('                    data_out <= s1;\n', '                    data_out <= f_out;\n')]},
}


@pytest.mark.parametrize('mut', sorted(MUTATIONS))
def test_mutation_fails(tmp_path, mut):
    """A control mutation is caught also under abstraction: FAIL (not ERROR) in a_match, trace written.

    M1 (data_out <= f_out, the s1 stage skipped) is caught because the testbench
    drives data_in freely on valid = '0' cycles (data_b_idle_in). If stim_f(icnt)
    stayed constant between beats, M1 would go unnoticed.
    """
    src = mutated_copy(HERE, tmp_path / 'mut' / HERE.name, MUTATIONS[mut])
    r = run_sby(src, 'dsp2.sby', 'bmc', tmp_path)
    assert r.status == 'FAIL', r.log[-3000:]
    assert failed_asserts(r.log) == ['a_match'], r.log[-3000:]
    assert (r.workdir / 'dsp2_bmc' / 'engine_0' / 'trace.vcd').exists()


@pytest.mark.parametrize('mut', sorted(MUTATIONS))
def test_prove_mutation_fails(tmp_path, mut):
    """The invariants do not mask control bugs: the mutation also fails the prove
    task in the basecase (FAIL, depth 4). M3 fails a_match; M4 already fails
    inv_cnt_a, because that invariant encodes the DUT latency."""
    src = mutated_copy(HERE, tmp_path / 'mut' / HERE.name, MUTATIONS[mut])
    r = run_sby(src, 'dsp2.sby', 'prove', tmp_path)
    assert r.status == 'FAIL', r.log[-3000:]
    assert failed_asserts(r.log) and set(failed_asserts(r.log)) <= PROVE_ASSERTS, r.log[-3000:]


# a_match must not be vacuous: its antecedent holds, i.e. B produces the
# symbolic beat j >= 2, which A has produced (and a_define has defined) earlier.
COVER_J = ("    c_b_checked_j : cover {armed = '1' and rst_in = '0' and yvalid_b = '1' and "
           "ocnt_b = j and j >= 2 and j < ocnt_a};\n")


@pytest.mark.parametrize('task', ['bmc', 'prove'])
def test_vacuity_cover_j(tmp_path, task):
    """The symbolic-index check is reached in the task's model (prove: with the
    vunit): B produces beat j after A."""
    srcs = SOURCES + [INV] if task == 'prove' else SOURCES
    r = run_cover(HERE, srcs, sby_script(HERE / 'dsp2.sby', TASK_TAGS[task] | {task}),
                  tmp_path, cover=COVER_J)
    assert r.status == 'PASS', r.log[-3000:]
    assert 'Reached cover statement' in r.log, r.log[-3000:]
    assert 'Unreached cover' not in r.log, r.log[-3000:]
    assert r.uf_warnings == [], r.uf_warnings


def test_vacuity_cover_j_sensitivity(tmp_path):
    """Sensitivity: an assumption that closes channel B -> COVER_J is unreachable."""
    r = run_cover(HERE, SOURCES, sby_script(HERE / 'dsp2.sby', TASK_TAGS['bmc'] | {'bmc'}),
                  tmp_path, cover=COVER_J, extra=VACUITY_INJECT['b_never_valid'])
    assert r.status == 'FAIL', r.log[-3000:]
    assert 'Unreached cover statement' in r.log, r.log[-3000:]


# ---------------------------------------------------------------- structure

def _write_model(tmp_path, name, edits=None):
    src = mutated_copy(HERE, tmp_path / name, edits)
    script = [l for l in sby_script(HERE / 'dsp2.sby', TASK_TAGS['bmc'])
              if not l.startswith('plugin ')]
    r = run_yosys(';\n'.join(script + ['write_smt2 -bv out.smt2']), src, ghdl=True)
    assert r.returncode == 0, r.log[-3000:]
    assert r.uf_warnings == [], r.uf_warnings
    return (src / 'out.smt2').read_text()


def test_dsp_f_semantics_not_in_model(tmp_path):
    """A STRUCTURAL property, not a proof of independence.

    dsp_f's architecture is dead text under the UF: dsp_f_Brtl is written to the
    file, but no reachable section refers to it. So * -> + cannot change the
    model, and a PASS would be guaranteed by structure. The actual proof is the
    bmc_tbuf run of vhdl_control_independence_setattr
    (test_vhdl_control_independence_setattr.py::test_tbuf_independent_of_dut_operator).
    """
    orig = _write_model(tmp_path, 'orig')
    mut = _write_model(tmp_path, 'mut', MUT_DSP_F_ADD)
    so, sm = smt2_module_sections(orig), smt2_module_sections(mut)
    # The mutation was applied: the dead dsp_f_Brtl changes.
    assert 'bvmul' in so['dsp_f_Brtl'] and 'bvmul' not in sm['dsp_f_Brtl']
    assert 'bvadd' in sm['dsp_f_Brtl']
    reach = reachable_modules(orig)
    assert reach == reachable_modules(mut) == {'tb_dsp_formal', 'dsp_Brtl'}
    for mod in reach:
        assert so[mod] == sm[mod], mod
        assert 'bvmul' not in so[mod], mod
    # The only bvadd in the reachable sections is in the testbench counters, not in the DUT.
    assert 'bvadd' not in so['dsp_Brtl']


# ---------------------------------------------------------------- vacuity

def _cover(tmp_path, task='bmc', extra='', src=HERE):
    return run_cover(src, SOURCES, sby_script(HERE / 'dsp2.sby', TASK_TAGS[task]), tmp_path,
                     extra=extra)


@pytest.mark.parametrize('task', ['bmc', 'bmc_nouf'])
def test_vacuity_cover(tmp_path, task):
    """Under the task's assumptions both channels produce checked beats at depth 20.

    The cover run's own model is checked: in the bmc task the same UF
    declarations as in test_bmc (otherwise the cover would prove something
    about a different model), in bmc_nouf none.
    """
    r = _cover(tmp_path, task)
    assert r.status == 'PASS', r.log[-3000:]
    assert 'Reached cover statement' in r.log, r.log[-3000:]
    assert 'Unreached cover' not in r.log, r.log[-3000:]
    assert cover_steps(r.log)[0] + 2 <= 20, cover_steps(r.log)
    assert r.uf_warnings == [], r.uf_warnings
    smt = sby_model(r, 'cov')
    decls = uf_decls(smt)
    if task == 'bmc':
        assert {k: [_code(l) for l in v] for k, v in decls.items()} == \
            {s: [UF_DECL_16.format(s)] for s in ('dsp_f', 'stim_f', 'out_f')}, decls
        assert reachable_modules(smt) == {'tb_dsp_formal', 'dsp_Brtl'}
    else:
        assert decls == {}, decls
        assert reachable_modules(smt) == {'tb_dsp_formal', 'dsp_Brtl', *UF_MODULES}


@pytest.mark.parametrize('task', ['bmc', 'bmc_nouf'])
def test_vacuity_cover_deep(tmp_path, task):
    """The deep cover (ocnt_a >= 16, ocnt_b >= 3) is reached within the BMC horizon:
    at step 19 at the earliest, the last step of depth 20."""
    r = run_cover(HERE, SOURCES, sby_script(HERE / 'dsp2.sby', TASK_TAGS[task]), tmp_path,
                  cover=COVER_DEEP)
    assert r.status == 'PASS', r.log[-3000:]
    assert 'Unreached cover' not in r.log, r.log[-3000:]
    assert cover_steps(r.log) and cover_steps(r.log)[0] < 20, cover_steps(r.log)
    assert r.uf_warnings == [], r.uf_warnings


# In the non-UF tasks (UF_MODE=false) a_define is an assert (g_nouf branch).
A_DEFINE_CHK = 'g_nouf.a_define_chk'

# s1 is truncated to 8 bits. In the non-UF run, beat 8 of channel A
# ((3*8-7)^2 = 289 > 255) does not match out_f. If a_define were an assume in
# the non-UF run as well, it would prune these paths: bmc_nouf would PASS
# and only the deep cover would reveal the bug. As an assert (UF_MODE=false)
# it fails directly.
MUT_TRUNC8 = {'dsp.vhdl': [('s1 <= f_out;', 's1 <= resize(f_out(7 downto 0), 16);')]}


def test_nouf_catches_late_truncation(tmp_path):
    """The non-UF run fails a_define_chk (an assume would give a vacuous PASS)."""
    src = mutated_copy(HERE, tmp_path / 'mut' / HERE.name, MUT_TRUNC8)
    r = run_sby(src, 'dsp2.sby', 'bmc_nouf', tmp_path)
    assert r.status == 'FAIL', r.log[-3000:]
    assert A_DEFINE_CHK in failed_asserts(r.log), r.log[-3000:]


@pytest.mark.parametrize('inject', sorted(VACUITY_INJECT))
def test_vacuity_cover_sensitivity(tmp_path, inject):
    """Sensitivity: a contradictory / channel-B-closing assumption -> cover unreachable (FAIL)."""
    r = _cover(tmp_path, 'bmc', VACUITY_INJECT[inject])
    assert r.status == 'FAIL', r.log[-3000:]
    assert 'Unreached cover statement' in r.log, r.log[-3000:]


def test_nouf_mutation_fails(tmp_path):
    """* -> + in the non-UF run fails a_define_chk: the interpreted out_f cannot
    match the changed datapath. (As an assume in the non-UF run, a_define would
    empty the state space and the PASS would be vacuous; only the cover would
    reveal it.)"""
    src = mutated_copy(HERE, tmp_path / 'mut' / HERE.name, MUT_DSP_F_ADD)
    r = run_sby(src, 'dsp2.sby', 'bmc_nouf', tmp_path)
    assert r.status == 'FAIL', r.log[-3000:]
    assert A_DEFINE_CHK in failed_asserts(r.log), r.log[-3000:]


# ---------------------------------------------------------------- a_ref_rate

def test_a_ref_rate_needed_uf(tmp_path):
    """Without a_ref_rate the UF run fails: out_f is unconstrained at indices that A
    did not produce, so B's comparison against it fails. Status FAIL (not ERROR)."""
    src = mutated_copy(HERE, tmp_path / 'mut' / HERE.name, NO_A_REF_RATE)
    r = run_sby(src, 'dsp2.sby', 'bmc', tmp_path)
    assert r.status == 'FAIL', r.log[-3000:]
    assert failed_asserts(r.log) == ['a_match'], r.log[-3000:]
    assert (r.workdir / 'dsp2_bmc' / 'engine_0' / 'trace.vcd').exists()


def test_a_ref_rate_needed_nouf(tmp_path):
    """Control: the same testbench run without UFs PASSes and the cover is reached
    at the same depth. Without the cover, the PASS could be due to channel B
    being unreachable."""
    src = mutated_copy(HERE, tmp_path / 'mut' / HERE.name, NO_A_REF_RATE)
    r = run_sby(src, 'dsp2.sby', 'bmc_nouf', tmp_path)
    assert r.status == 'PASS', r.log[-3000:]
    c = _cover(tmp_path / 'c', 'bmc_nouf', src=src)
    assert c.status == 'PASS', c.log[-3000:]
    assert 'Reached cover statement' in c.log, c.log[-3000:]
    assert cover_steps(c.log)[0] + 2 <= 20, cover_steps(c.log)

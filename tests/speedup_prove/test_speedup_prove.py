"""speedup_prove: UF vs. classical k-induction on the same assertion.

- The testbench, the helper invariants (tb_dsp_formal_inv.psl) and the
  assertion (a_match, symbolic index j) are the same as in
  tests/vhdl_control_independence_setattr, but the data width is the generic
  WIDTH (uf_prove.sby: PROVE_WIDTH -> ghdl -gWIDTH=..). The counters and j
  stay 16 bits wide.
- prove_uf:   testbench stim_f/out_f as UFs and the DUT $mul = mulw (UF).
  prove_nouf: testbench stim_f/out_f as UFs, the DUT multiplication
  interpreted ("classical": symbolic data through the real multiplier).
- test_models_differ_only_in_mul: the final sby models differ only in the
  multiplication (declare-fun |mulw| + one define-fun bvmul <-> |mulw|), so
  both runs prove the same claim on the same model with the same invariants.
- Default run: prove_uf at all widths (4..32), prove_nouf at widths <= 16
  (at most about 5 s) and the 2x rule at width 16. The slow prove_nouf points
  are marked @pytest.mark.validation:
  ./tc.sh pytest -m validation -n auto tests/speedup_prove
- Vacuity: the cover of the symbolic index is reached in both models. Control
  mutations M3/M4 make both prove tasks fail (FAIL).

Measured wall-clock time of the whole sby run (bitwuzla, depth 4, about
0.35 s of it ghdl/yosys preprocessing; all points in parallel, limit 30 min):

    WIDTH  prove_uf  prove_nouf   nouf/uf
      4    0.36 s      0.37 s        1
      8    0.38 s      0.37 s        1
     12    0.39 s      0.74 s        1.9
     14    0.36 s      1.14 s        3.2
     16    0.39 s      5.26 s       13
     18    0.36 s      24.3 s       68
     20    0.42 s       125 s      300
     22    0.37 s       756 s     2000
     24    0.41 s    > 1800 s    > 4400
     32    0.43 s    > 1800 s    > 4200

prove_uf is constant (about 0.4 s, mostly preprocessing) regardless of the
width. prove_nouf grows by about 5x per two bits from width 14 on; the time is
spent almost entirely in the induction step. In the UF run the solver needs
only congruence (x = y -> mulw(x) = mulw(y)): the pipelines of B and of the
helper instance c carry the same mulw(stim_f(j)) term. In the classical run
the same reasoning requires proving that the outputs of two bit-blasted
WIDTH-bit multipliers are equal when their inputs are symbolic and only
indirectly the same (the initial state of the induction is free, so s1 is not
syntactically the same term).
"""
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from conftest import (DONE_RE, SbyResult, _ignore_subdirs, failed_asserts, insert_before_arch_end,
                      mutated_copy, sby_model, smt2_module_sections, uf_decls)

HERE = Path(__file__).resolve().parent
SBY = 'uf_prove.sby'
INVARIANTS = ['inv_cnt_a', 'inv_cnt_b', 'inv_order', 'inv_bound']

# Measured widths (module docstring). prove_uf is fast at all of them (under 0.5 s).
WIDTHS = [4, 5, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24, 28, 32]
# prove_nouf in the default run at the widths where it finishes quickly
# (measured at most about 5 s); 18..22 are validation points (24 s, 125 s,
# 756 s). At widths 24, 28 and 32 prove_nouf did not finish in 30 minutes, so
# there is no PASS test for them.
NOUF_FAST = [w for w in WIDTHS if w <= 16]
NOUF_VALIDATION = [18, 20, 22]
# Time limit per validation point (the classical run is given 30 min).
NOUF_CAP_S = 1800

MUTATIONS = {
    # M3: s1 is captured on v1 instead of valid_in -> wrong beat in the pipeline.
    'M3_capture_on_v1': {'dsp.vhdl': [(
        "if valid_in = '1' then\n                    s1 <= resize(data_in * data_in, WIDTH);",
        "if v1 = '1' then\n                    s1 <= resize(data_in * data_in, WIDTH);")]},
    # M4: valid_out one cycle too early (latency).
    'M4_latency': {'dsp.vhdl': [('valid_out <= v1;', 'valid_out <= valid_in;')]},
}

# a_match must not be vacuous (as in vhdl_control_independence_setattr): B
# produces a symbolic beat j >= 2 that A has produced (and a_define bound) earlier.
COVER_J = ("    c_b_checked_j : cover {armed = '1' and rst_in = '0' and yvalid_b = '1' and "
           "ocnt_b = j and j >= 2 and j < ocnt_a};\n")


def run_task(src, task, tmp_path, width, depth=None, timeout=NOUF_CAP_S):
    """Copy src to tmp_path and run `sby -f uf_prove.sby <task>` with width `width`.

    Returns (SbyResult, wall-clock time in s). A timeout -> status TIMEOUT.
    """
    work = tmp_path / f'w{width}_{task}'
    shutil.copytree(src, work, dirs_exist_ok=True, ignore=_ignore_subdirs)
    env = dict(os.environ, PROVE_WIDTH=str(width))
    if depth is not None:
        env['PROVE_DEPTH'] = str(depth)
    t0 = time.monotonic()
    try:
        p = subprocess.run(['sby', '-f', SBY, task], cwd=work, env=env, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, text=True, timeout=timeout)
        log, rc = p.stdout, p.returncode
        done = DONE_RE.findall(log)
        status = done[-1][0] if done else 'ERROR'
    except subprocess.TimeoutExpired as e:
        log = e.stdout if isinstance(e.stdout, str) else (e.stdout or b'').decode(errors='replace')
        rc, status = -1, 'TIMEOUT'
    return SbyResult(status, rc, log, work), time.monotonic() - t0


def check_prove_model(r, task, width):
    """Final model: exactly a_match + the vunit invariants, j anyconst, and the
    UFs: prove_uf mulw + stim_f + out_f, prove_nouf only stim_f + out_f."""
    smt = sby_model(r, f'uf_prove_{task}')
    asserts = re.findall(r'^; yosys-smt2-assert \d+ (\S+)', smt, flags=re.M)
    assert sorted(asserts) == sorted(['a_match'] + [f'tb_dsp_formal_inv.{n}' for n in INVARIANTS]), \
        asserts
    assert 'yosys-smt2-anyconst' in smt
    dut = f'dsp_Brtl_{width}'
    sections = smt2_module_sections(smt)
    assert dut in sections, list(sections)
    if task.endswith('_uf'):
        assert {k: len(v) for k, v in uf_decls(smt).items()} == \
            {'mulw': 1, 'stim_f': 1, 'out_f': 1}, uf_decls(smt)
        assert re.search(rf'^\(declare-fun \|mulw\| \(\(_ BitVec {width}\) \(_ BitVec {width}\)\) '
                         rf'\(_ BitVec {width}\)\)', smt, flags=re.M), uf_decls(smt)
        assert 'bvmul' not in sections[dut]
    else:
        assert {k: len(v) for k, v in uf_decls(smt).items()} == \
            {'stim_f': 1, 'out_f': 1}, uf_decls(smt)
        assert 'mulw' not in smt
        assert sections[dut].count('bvmul') == 1
    return smt


def _prove_pass(tmp_path, task, width, timeout=NOUF_CAP_S):
    r, t = run_task(HERE, task, tmp_path, width, timeout=timeout)
    print(f'{task} WIDTH={width}: {r.status} {t:.2f} s')
    assert r.status == 'PASS', (t, r.log[-3000:])
    assert 'successful proof by k-induction' in r.log, r.log[-3000:]
    assert r.uf_warnings == [], r.uf_warnings
    check_prove_model(r, task, width)
    return t


# ---------------------------------------------------------------- prove

@pytest.mark.parametrize('width', WIDTHS)
def test_prove_uf(tmp_path, width):
    _prove_pass(tmp_path, 'prove_uf', width)


@pytest.mark.parametrize('width', NOUF_FAST + [pytest.param(w, marks=pytest.mark.validation)
                                               for w in NOUF_VALIDATION])
def test_prove_nouf(tmp_path, width):
    """Classical: the same assertion, the DUT multiplication interpreted. At the
    validation points the time limit is 30 min; a timeout fails the test."""
    _prove_pass(tmp_path, 'prove_nouf', width)


def test_uf_faster_at_16(tmp_path):
    """2x rule: at width 16 prove_nouf takes at least 2x the time of prove_uf
    (measured 5.3 s vs. 0.39 s wall clock)."""
    t_uf = _prove_pass(tmp_path / 'uf', 'prove_uf', 16)
    t_nouf = _prove_pass(tmp_path / 'nouf', 'prove_nouf', 16)
    assert t_nouf >= 2 * t_uf, (t_nouf, t_uf)


@pytest.mark.validation
def test_uf_faster_at_20(tmp_path):
    """At width 20 prove_nouf takes at least 10x the time of prove_uf
    (measured 125 s vs. 0.42 s)."""
    t_uf = _prove_pass(tmp_path / 'uf', 'prove_uf', 20)
    t_nouf = _prove_pass(tmp_path / 'nouf', 'prove_nouf', 20)
    assert t_nouf >= 10 * t_uf, (t_nouf, t_uf)


@pytest.mark.parametrize('task', ['prove_uf', 'prove_nouf'])
def test_min_depth(tmp_path, task):
    """k = 3 is enough for both (depth 3 PASS); at depth 2 the induction does
    not go through (UNKNOWN, inv_bound). uf_prove.sby uses depth 4 (margin)."""
    r3, _ = run_task(HERE, task, tmp_path / 'd3', 4, depth=3)
    assert r3.status == 'PASS', r3.log[-3000:]
    r2, _ = run_task(HERE, task, tmp_path / 'd2', 4, depth=2)
    assert r2.status == 'UNKNOWN', r2.log[-3000:]


# ---------------------------------------------------------------- same claim

def _strip_comments(smt):
    return [l.split(' ; ')[0] for l in smt.splitlines()]


@pytest.mark.parametrize('width', [8, 16])
def test_models_differ_only_in_mul(tmp_path, width):
    """The final models of prove_uf and prove_nouf (sby's design_smt2.smt2) are
    the same line by line except for the DUT multiplication: prove_uf has one
    extra line (declare-fun |mulw|) and one define-fun in which bvmul is
    replaced with |mulw| on the same arguments."""
    import difflib
    smts = {}
    for task in ('prove_uf', 'prove_nouf'):
        r, _ = run_task(HERE, task, tmp_path / task, width)
        assert r.status == 'PASS', r.log[-3000:]
        smts[task] = _strip_comments(sby_model(r, f'uf_prove_{task}'))
    uf, nouf = smts['prove_uf'], smts['prove_nouf']
    sm = difflib.SequenceMatcher(a=uf, b=nouf, autojunk=False)
    changes = [op for op in sm.get_opcodes() if op[0] != 'equal']
    removed = [l for tag, i1, i2, j1, j2 in changes for l in uf[i1:i2]]
    added = [l for tag, i1, i2, j1, j2 in changes for l in nouf[j1:j2]]
    assert len(removed) == 2 and len(added) == 1, (removed, added)
    decl = [l for l in removed if l.startswith('(declare-fun |mulw|')]
    assert len(decl) == 1, removed
    (uf_def,) = [l for l in removed if l not in decl]
    assert '(|mulw| ' in uf_def and 'bvmul' not in uf_def, uf_def
    assert added[0] == uf_def.replace('(|mulw| ', '(bvmul '), (added[0], uf_def)


# ---------------------------------------------------------------- vacuity and mutations

@pytest.mark.parametrize('task', ['prove_uf', 'prove_nouf'])
def test_vacuity_cover_j(tmp_path, task):
    """The check at the symbolic index is reached in the model of the task (vunit
    included): the same sby script in cover mode, COVER_J added to the testbench."""
    tb = HERE / 'tb_dsp_formal.vhdl'
    src = mutated_copy(HERE, tmp_path / 'cov' / HERE.name, {
        'tb_dsp_formal.vhdl': [(tb.read_text(), insert_before_arch_end(tb.read_text(), COVER_J))],
        SBY: [('prove: mode prove', 'prove: mode cover')]})
    r, _ = run_task(src, task, tmp_path, 4, depth=20, timeout=600)
    assert r.status == 'PASS', r.log[-3000:]
    assert 'Reached cover statement' in r.log, r.log[-3000:]
    assert 'Unreached cover' not in r.log, r.log[-3000:]
    assert r.uf_warnings == [], r.uf_warnings


def test_vacuity_cover_j_sensitivity(tmp_path):
    """Sensitivity: an assumption that closes channel B -> COVER_J is not reached."""
    tb = HERE / 'tb_dsp_formal.vhdl'
    extra = "    v_b_never_valid : assume always valid_b_in = '0';\n"
    src = mutated_copy(HERE, tmp_path / 'cov' / HERE.name, {
        'tb_dsp_formal.vhdl': [(tb.read_text(),
                                insert_before_arch_end(tb.read_text(), COVER_J + extra))],
        SBY: [('prove: mode prove', 'prove: mode cover')]})
    r, _ = run_task(src, 'prove_uf', tmp_path, 4, depth=20, timeout=600)
    assert r.status == 'FAIL', r.log[-3000:]
    assert 'Unreached cover statement' in r.log, r.log[-3000:]


@pytest.mark.parametrize('task', ['prove_uf', 'prove_nouf'])
@pytest.mark.parametrize('mut', sorted(MUTATIONS))
def test_prove_mutation_fails(tmp_path, mut, task):
    """A control mutation fails in the basecase of both prove tasks (FAIL):
    M3 in a_match, M4 in inv_cnt_a (the invariant encodes the latency)."""
    src = mutated_copy(HERE, tmp_path / 'mut' / HERE.name, MUTATIONS[mut])
    r, _ = run_task(src, task, tmp_path, 4, timeout=600)
    assert r.status == 'FAIL', r.log[-3000:]
    expected = {'a_match'} | {f'tb_dsp_formal_inv.{n}' for n in INVARIANTS}
    assert failed_asserts(r.log) and set(failed_asserts(r.log)) <= expected, r.log[-3000:]

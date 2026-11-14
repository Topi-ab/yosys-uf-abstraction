"""fifo_checkers: parameterized AXI Stream FIFO, UF checker vs. scoreboard.

Two checkers for the same DUT (axis_fifo.vhdl):
- uf: s_data = stim(icnt), assertion m_data = stim(ocnt); stim is a UF (declare-fun).
- sb: s_data_in free, tb_stream_scoreboard_formal: one symbolic sequence
  number master_ptr (anyconst), assertion k-th accepted input = k-th accepted
  output for beat k = master_ptr. No shadow queue, no delay.
Both share the same control assertions (tb_axis_ctrl_formal.vhdl).
prove: k-induction of the sb testbench with auxiliary invariants
(tb_axis_fifo_sb_formal_inv.psl).

The parameters (DEPTH, WIDTH) are in the pycode blocks of the sby file (the
line "D, W = 4, 8"; the generic overrides -gDEPTH=.. -gWIDTH=.. and the BMC
depth 2*DEPTH+6 are derived from it); the tests replace the line in a copy
and never touch the sources.
"""
import re
import shutil
from pathlib import Path

import pytest

from conftest import (_ignore_subdirs, cover_steps, failed_asserts, run_cover, run_sby,
                      sby_model, uf_decls)

HERE = Path(__file__).resolve().parent
SBY = 'axis_fifo.sby'

DEFAULT_PARAMS = 'D, W = 4, 8\n'
DEFAULT_PROVE_K = 'PROVE_K = 2\n'

CHECKERS = ['uf', 'sb']
TB = {'uf': 'tb_axis_fifo_uf_formal.vhdl', 'sb': 'tb_axis_fifo_sb_formal.vhdl'}
SB = 'tb_stream_scoreboard_formal.vhdl'
INV = 'tb_axis_fifo_sb_formal_inv.psl'
SOURCES = {
    'uf': ['axis_fifo.vhdl', 'tb_axis_stim_formal.vhdl', 'tb_axis_ctrl_formal.vhdl',
           TB['uf']],
    'sb': ['axis_fifo.vhdl', 'tb_axis_ctrl_formal.vhdl', SB, TB['sb']],
}
MATCH_ASSERT = {'uf': 'a_uf_match', 'sb': 'a_sb_match'}
# Auxiliary invariants (INV); in the model the vunit name is the prefix.
INVARIANTS = ['inv_range', 'inv_count', 'inv_wr', 'inv_ptr', 'inv_order', 'inv_inside',
              'inv_slot']

# Default run: a small grid (DEPTH 2 and 4, WIDTH 8 and 32) plus the
# non-power-of-two DEPTH 3 and 6 (WIDTH 8): there the pointer wrap is not the
# natural overflow of the bits, so wrap errors (wr_nowrap, rd_nowrap) show up.
# DEPTH=8 (BMC depth 22) takes about 8-21 s with bitwuzla -> slow.
# Validation: WIDTH 110.
# DEPTH=16 (depth 38) is left out: the BMC time grows by about 1.5-2x per
# step, so the run would not finish in reasonable time.
GRID = [(d, w) for d in (2, 4) for w in (8, 32)] + [(3, 8), (6, 8)]
GRID_SLOW = [(8, 8), (8, 32)]
GRID_VALIDATION = [(d, 110) for d in (2, 4, 8)]


def _params(grid, marks=()):
    return [pytest.param(d, w, id=f'D{d}-W{w}', marks=marks) for d, w in grid]


PARAMS = (_params(GRID) + _params(GRID_SLOW, marks=pytest.mark.slow)
          + _params(GRID_VALIDATION, marks=pytest.mark.validation))


def bmc_depth(depth):
    return 2 * depth + 6


def param_copy(dst, depth, width, edits=None, prove_k=None):
    """Copy the sources to dst and set the parameters in the sby pycode blocks.

    edits: {file: [(old, new), ...]}, each old exactly once.
    prove_k: induction depth of the prove task (default: PROVE_K of the sby file).
    """
    dst = Path(dst)
    shutil.copytree(HERE, dst, dirs_exist_ok=True, ignore=_ignore_subdirs)
    sby = dst / SBY
    text = sby.read_text()
    assert text.count(DEFAULT_PARAMS) == 2 and text.count(DEFAULT_PROVE_K) == 1
    text = text.replace(DEFAULT_PARAMS, f'D, W = {depth}, {width}\n')
    if prove_k is not None:
        text = text.replace(DEFAULT_PROVE_K, f'PROVE_K = {prove_k}\n')
    sby.write_text(text)
    for f, pairs in (edits or {}).items():
        p = dst / f
        t = p.read_text()
        for old, new in pairs:
            assert t.count(old) == 1, (f, old, t.count(old))
            t = t.replace(old, new)
        p.write_text(t)
    return dst


def sby_script_py(sby_file, tags):
    """[script] lines of the sby file for the given tags, pycode blocks executed.

    Like conftest.sby_script, but a '--pycode-begin--' .. '--pycode-end--'
    block is executed the way sby does it (tags, output) and its output is
    included.
    """
    out, sect, code = [], None, None
    for line in Path(sby_file).read_text().splitlines():
        if code is not None:
            if line.strip() == '--pycode-end--':
                if sect == 'script':
                    g = {'tags': set(tags), 'output': lambda s: out.extend(s.splitlines())}
                    exec('\n'.join(code), g)
                code = None
            else:
                code.append(line)
            continue
        if line.strip() == '--pycode-begin--':
            code = []
            continue
        if line.startswith('['):
            sect = line.strip()[1:-1]
            continue
        line = line.strip()
        if sect != 'script' or not line or line.startswith('#'):
            continue
        m = re.match(r'(\w+):\s+(.*)', line)
        if m:
            if m.group(1) not in tags:
                continue
            line = m.group(2)
        out.append(line)
    return out


def _bmc(tmp_path, checker, depth, width, edits=None):
    src = param_copy(tmp_path / 'param' / 'fifo_checkers', depth, width, edits)
    return run_sby(src, SBY, checker, tmp_path)


# ---------------------------------------------------------------- BMC

@pytest.mark.parametrize('checker', CHECKERS)
@pytest.mark.parametrize('depth,width', PARAMS)
def test_bmc(tmp_path, checker, depth, width):
    """Correct FIFO: checker PASS; in the UF model stim is a declare-fun, the sb model has no UF."""
    r = _bmc(tmp_path, checker, depth, width)
    assert r.status == 'PASS', r.log[-3000:]
    assert r.uf_warnings == [], r.uf_warnings
    smt = sby_model(r, f'axis_fifo_{checker}')
    decls = uf_decls(smt)
    if checker == 'uf':
        assert set(decls) == {'stim_f'}, decls
        assert [l.split(' ;', 1)[0] for l in decls['stim_f']] == [
            f'(declare-fun |stim_f| ((_ BitVec 32)) (_ BitVec {width}))'], decls
        # two instances (input and expected) -> at least two calls
        assert smt.count('(|stim_f|') >= 2
    else:
        assert decls == {}, decls


# ---------------------------------------------------------------- vacuity

def _cover_text(depth):
    # The FIFO has been full (was_full), has drained (icnt = ocnt) and at
    # least DEPTH+1 checked beats have come out.
    return ("    c_full_drained : cover {rst_in = '0' and was_full = '1' and "
            f"icnt = ocnt and ocnt >= {depth + 1}}};\n")


def _deep_cover_text(depth):
    # Deep cover: like the shallow one, but DEPTH+4 beats have come out. A full
    # FIFO needs DEPTH extra writes, so ocnt >= N needs at least step
    # N + DEPTH + 1: the earliest hit is 2*DEPTH+5 = the last step of the BMC
    # horizon. The shallow cover (2*DEPTH+2) does not rule out paths being cut
    # off in the last three steps of the horizon.
    return ("    c_full_drained_deep : cover {rst_in = '0' and was_full = '1' and "
            f"icnt = ocnt and ocnt >= {depth + 4}}};\n")


# Sensitivity: an assumption under which the cover must not be reached (the
# output is never ready).
NEVER_READY = "    v_never_ready : assume always m_ready_in = '0';\n"


def _cover(tmp_path, checker, depth, width, extra='', text=_cover_text):
    src = param_copy(tmp_path / 'param' / 'fifo_checkers', depth, width)
    script = sby_script_py(src / SBY, {checker, 'bmc'})
    return run_cover(src, SOURCES[checker], script, tmp_path, tb=TB[checker],
                     extra=extra, depth=bmc_depth(depth), cover=text(depth))


@pytest.mark.parametrize('checker', CHECKERS)
@pytest.mark.parametrize('depth,width', PARAMS)
def test_vacuity_cover(tmp_path, checker, depth, width):
    """Under the checker's assumptions the FIFO fills and drains within the BMC horizon."""
    r = _cover(tmp_path, checker, depth, width)
    assert r.status == 'PASS', r.log[-3000:]
    assert r.uf_warnings == [], r.uf_warnings
    steps = cover_steps(r.log)
    assert steps and 'Unreached cover' not in r.log, r.log[-3000:]
    # minimum: reset + DEPTH writes + DEPTH+1 reads
    assert steps[0] == 2 * depth + 2, steps
    assert steps[0] < bmc_depth(depth), steps


@pytest.mark.parametrize('checker', CHECKERS)
@pytest.mark.parametrize('depth,width', PARAMS)
def test_vacuity_cover_deep(tmp_path, checker, depth, width):
    """The deep cover is reached at the last step of the BMC horizon."""
    r = _cover(tmp_path, checker, depth, width, text=_deep_cover_text)
    assert r.status == 'PASS', r.log[-3000:]
    assert r.uf_warnings == [], r.uf_warnings
    steps = cover_steps(r.log)
    assert steps and 'Unreached cover' not in r.log, r.log[-3000:]
    assert steps[0] == 2 * depth + 5 == bmc_depth(depth) - 1, steps


@pytest.mark.parametrize('checker', CHECKERS)
@pytest.mark.parametrize('depth,width', PARAMS)
def test_vacuity_sensitivity(tmp_path, checker, depth, width):
    """Contradictory assumption (m_ready always low) -> cover unreachable (FAIL)."""
    r = _cover(tmp_path, checker, depth, width, extra=NEVER_READY)
    assert r.status == 'FAIL', r.log[-3000:]
    assert 'Unreached cover statement' in r.log, r.log[-3000:]
    assert cover_steps(r.log) == []


# ---------------------------------------------------------------- mutations
#
# Every mutation is applied to a tmp copy (param_copy, edits); the sources are
# never touched. Run with DEPTH=4, WIDTH=8 (BMC depth 14). Two modes:
# - full: all assertions; the mutation must fail on the expected assertion.
# - data: control assertions (tb_axis_ctrl_formal) disabled; measures whether
#   the data checker alone (a_uf_match / a_sb_match) sees the mutation.

_RD_INC = "                    else\n                        rd <= rd + 1;"
_WRITE = "            if push = '1' then\n                mem(wr) <= s_data_in;\n            end if;"

MUTATIONS = {
    # (a) Lost beat: on a simultaneous read and write wr advances, but the
    # data is not stored (the slot keeps its old content).
    'drop_store': {'axis_fifo.vhdl': [(
        "            if push = '1' then\n                mem(wr) <= s_data_in;",
        "            if push = '1' and pop = '0' then\n                mem(wr) <= s_data_in;")]},
    # (a) Lost beat: the read pointer skips one slot.
    'rd_skip': {'axis_fifo.vhdl': [(
        _RD_INC,
        "                    else\n                        rd <= (rd + 2) mod DEPTH;")]},
    # (b) Duplicated beat: the read pointer does not advance on a transfer.
    'dup_beat': {'axis_fifo.vhdl': [(
        _RD_INC,
        "                    else\n                        rd <= rd;")]},
    # (c) Reordering: write to the mirrored slot DEPTH-1-wr (a full FIFO reads
    # the beats in reverse order).
    'reorder_mirror': {'axis_fifo.vhdl': [(
        "                mem(wr) <= s_data_in;",
        "                mem(DEPTH - 1 - wr) <= s_data_in;")]},
    # (c) Wrong wrap: wr wraps at DEPTH-2 (rd wraps correctly).
    'wr_wrap_early': {'axis_fifo.vhdl': [(
        "                    if wr = DEPTH - 1 then",
        "                    if wr = DEPTH - 2 then")]},
    # (d) Control error: s_ready always high, a full FIFO overwrites an unread
    # beat.
    'overflow': {'axis_fifo.vhdl': [(
        "s_ready <= '1' when count < DEPTH else '0';",
        "s_ready <= '1';")]},
    # Extra: s_ready always low (the FIFO never accepts anything). Only the
    # control assertions can see this, since no transfers happen.
    'never_ready': {'axis_fifo.vhdl': [(
        "s_ready <= '1' when count < DEPTH else '0';",
        "s_ready <= '0';")]},
    # Extra: reset clears count but not the pointers rd, wr. If the FIFO holds
    # data at reset time, rd /= wr after reset and stale data is read.
    'no_ptr_reset': {'axis_fifo.vhdl': [(
        "                rd    <= 0;\n                wr    <= 0;\n", "")]},
    # Extra: input register error. On a transfer that follows a cycle without
    # a transfer, the previous cycle's s_data is stored. AXI only guarantees
    # stable data while valid = '1', so the error shows when valid = '0' on
    # the previous cycle.
    'stale_capture': {'axis_fifo.vhdl': [
        ("    signal pop     : std_logic;\n",
         "    signal pop     : std_logic;\n"
         "    signal push_q  : std_logic := '0';\n"
         "    signal s_data_q : std_logic_vector(WIDTH - 1 downto 0);\n"),
        (_WRITE,
         "            if push = '1' then\n"
         "                if push_q = '1' then\n"
         "                    mem(wr) <= s_data_in;\n"
         "                else\n"
         "                    mem(wr) <= s_data_q;\n"
         "                end if;\n"
         "            end if;\n"
         "            push_q   <= push;\n"
         "            s_data_q <= s_data_in;"),
    ]},
}

CTRL_ASSERTS = ('a_occ_max', 'a_no_underflow', 'a_no_overflow', 'a_ready_not_full',
                'a_valid_not_empty', 'a_m_valid_hold', 'a_m_data_stable')

# Acceptable failing assertions (full mode); 'match' = the checker's data
# assertion. smtbmc stops at the first failing step, so a mutation may first
# fail on a control assertion. wr_wrap_early: wr wraps onto the held head, so
# in the sb testbench (free s_data) a_m_data_stable can fail even before a
# transfer; the data mode shows that a_sb_match also sees the error.
EXPECT_FULL = {m: {'match'} for m in MUTATIONS}
EXPECT_FULL['overflow'] = {'a_no_overflow'}
EXPECT_FULL['never_ready'] = {'a_ready_not_full'}
EXPECT_FULL['wr_wrap_early'] = {'match', 'a_m_data_stable'}

# Data mode: never_ready is left out, because with no transfers the data
# assertion has nothing to check; a_ready_not_full catches it in full mode.
# The scoreboard catches overflow in data mode as well: it compares the k-th
# input with the k-th output without a capacity limit, so an overwritten beat
# shows up as a mismatch.
DATA_MUTATIONS = [m for m in MUTATIONS if m != 'never_ready']


def _disable_ctrl_asserts(dst):
    """Control assertion condition -> false (in the tmp copy)."""
    p = dst / 'tb_axis_ctrl_formal.vhdl'
    t, n = re.subn(r'(a_(?:occ_max|no_underflow|no_overflow|ready_not_full|valid_not_empty'
                   r'|m_valid_hold|m_data_stable)'
                   r' : assert always\n\s+\()', r'\1false and ', p.read_text())
    assert n == len(CTRL_ASSERTS), n
    p.write_text(t)


def _mut_bmc(tmp_path, checker, mut, data_only):
    src = param_copy(tmp_path / 'param' / 'fifo_checkers', 4, 8, MUTATIONS[mut])
    if data_only:
        _disable_ctrl_asserts(src)
    return run_sby(src, SBY, checker, tmp_path)


def _fail_names(r):
    return [re.sub(r'.*\.', '', n) for n in failed_asserts(r.log)]


@pytest.mark.parametrize('checker', CHECKERS)
@pytest.mark.parametrize('mut', list(MUTATIONS))
def test_mutation_fails(tmp_path, checker, mut):
    """A DUT mutation fails with both checkers on the expected assertion (D4-W8)."""
    expect = {MATCH_ASSERT[checker] if e == 'match' else e for e in EXPECT_FULL[mut]}
    r = _mut_bmc(tmp_path, checker, mut, data_only=False)
    assert r.status == 'FAIL', r.log[-3000:]
    assert expect & set(_fail_names(r)), (expect, _fail_names(r), r.log[-3000:])
    assert (r.workdir / f'axis_fifo_{checker}' / 'engine_0' / 'trace.vcd').exists()


@pytest.mark.parametrize('checker', CHECKERS)
@pytest.mark.parametrize('mut', DATA_MUTATIONS)
def test_mutation_data_only(tmp_path, checker, mut):
    """Control assertions disabled: the data checker alone fails."""
    r = _mut_bmc(tmp_path, checker, mut, data_only=True)
    assert r.status == 'FAIL', r.log[-3000:]
    assert _fail_names(r) == [MATCH_ASSERT[checker]], (_fail_names(r), r.log[-3000:])
    assert (r.workdir / f'axis_fifo_{checker}' / 'engine_0' / 'trace.vcd').exists()


def test_data_only_correct_passes(tmp_path):
    """Disabling the control assertions does not by itself fail a correct FIFO (data-mode control)."""
    for checker in CHECKERS:
        src = param_copy(tmp_path / checker / 'param' / 'fifo_checkers', 2, 8)
        _disable_ctrl_asserts(src)
        r = run_sby(src, SBY, checker, tmp_path / checker)
        assert r.status == 'PASS', (checker, r.log[-3000:])


# Reset only on the first cycle (the assumption in the tmp copy becomes an
# equivalence).
_RESET_FIRST_ONLY = {'tb_axis_ctrl_formal.vhdl': [(
    "        (first = '1') -> (rst_in = '1');",
    "        (first = '1') = (rst_in = '1');")]}


@pytest.mark.parametrize('checker', CHECKERS)
def test_stale_capture_without_midrun_reset(tmp_path, checker):
    """stale_capture is caught without a reset in the middle of the run.

    The free s_data_idle_in input makes this work for the UF checker: if
    stim(icnt) were driven also on non-valid cycles, the data would stay
    constant between transfers and the mutation would only be visible through
    a reset (the index jumping back to zero).
    """
    edits = {**MUTATIONS['stale_capture'], **_RESET_FIRST_ONLY}
    src = param_copy(tmp_path / 'param' / 'fifo_checkers', 4, 8, edits)
    r = run_sby(src, SBY, checker, tmp_path)
    assert r.status == 'FAIL', r.log[-3000:]
    assert MATCH_ASSERT[checker] in _fail_names(r), (_fail_names(r), r.log[-3000:])


# ---------------------------------------------------------------- wrap errors

# The pointer compares against DEPTH instead of DEPTH-1 when wrapping, i.e. it
# does not wrap by itself. When DEPTH is a power of two, the pointer width is
# log2(DEPTH) and wr + 1 overflows to zero: the mutation is equivalent (PASS
# with D4-W8 and D8-W32). For other DEPTH values the pointer leaves its range.
NOWRAP_MUTATIONS = {
    'wr_nowrap': {'axis_fifo.vhdl': [('if wr = DEPTH - 1 then', 'if wr = DEPTH then')]},
    'rd_nowrap': {'axis_fifo.vhdl': [('if rd = DEPTH - 1 then', 'if rd = DEPTH then')]},
}


@pytest.mark.parametrize('checker', CHECKERS)
@pytest.mark.parametrize('mut', sorted(NOWRAP_MUTATIONS))
@pytest.mark.parametrize('depth', [3, 6])
def test_nowrap_mutation_fails(tmp_path, depth, mut, checker):
    """A wrap error fails the data assertion when DEPTH is not a power of two."""
    src = param_copy(tmp_path / 'param' / 'fifo_checkers', depth, 8, NOWRAP_MUTATIONS[mut])
    r = run_sby(src, SBY, checker, tmp_path)
    assert r.status == 'FAIL', r.log[-3000:]
    assert MATCH_ASSERT[checker] in _fail_names(r), (_fail_names(r), r.log[-3000:])


# ---------------------------------------------------------------- scoreboard vacuity
#
# The cover is added to a copy of tb_stream_scoreboard_formal (the capture
# flags are its internal signals). Beat n is accepted at cycle n+1 at the
# earliest (reset at cycle 0) and comes out at cycle n+2 at the earliest, at
# which point the zero-delay scoreboard has captured it from both streams.

def _capture_cover_text(n):
    return ("    c_both_captured : cover {a_captured = '1' and b_captured = '1' and "
            f"master_ptr = {n}}};\n")


# Sensitivity: stream b never produces a beat -> b cannot capture.
SB_NEVER_B = "    v_never_b : assume always b_valid_in = '0';\n"


def _sb_cover(tmp_path, depth, width, n, extra=''):
    src = param_copy(tmp_path / 'param' / 'fifo_checkers', depth, width)
    script = sby_script_py(src / SBY, {'sb', 'bmc'})
    return run_cover(src, SOURCES['sb'], script, tmp_path, tb=SB, extra=extra,
                     depth=bmc_depth(depth), cover=_capture_cover_text(n))


@pytest.mark.parametrize('depth,width', PARAMS)
def test_sb_capture_cover(tmp_path, depth, width):
    """Beat DEPTH+1 (after the FIFO wraps) is captured from both streams at step DEPTH+3."""
    r = _sb_cover(tmp_path, depth, width, depth + 1)
    assert r.status == 'PASS', r.log[-3000:]
    assert cover_steps(r.log) == [depth + 3], r.log[-3000:]


@pytest.mark.parametrize('depth,width', PARAMS)
def test_sb_capture_cover_deep(tmp_path, depth, width):
    """The last beat that fits the horizon, 2*DEPTH+3, is captured at the last BMC step."""
    r = _sb_cover(tmp_path, depth, width, 2 * depth + 3)
    assert r.status == 'PASS', r.log[-3000:]
    assert 2 * depth + 5 == bmc_depth(depth) - 1
    assert cover_steps(r.log) == [2 * depth + 5], r.log[-3000:]


@pytest.mark.parametrize('depth,width', PARAMS)
def test_sb_capture_sensitivity(tmp_path, depth, width):
    """Stream b without beats -> capture cover unreachable (FAIL)."""
    r = _sb_cover(tmp_path, depth, width, 0, extra=SB_NEVER_B)
    assert r.status == 'FAIL', r.log[-3000:]
    assert 'Unreached cover statement' in r.log, r.log[-3000:]
    assert cover_steps(r.log) == []


# ---------------------------------------------------------------- k-induction
#
# prove task: sb testbench + auxiliary invariants (INV), induction depth
# PROVE_K = 2. Measured with bitwuzla: all of DEPTH 4..32, WIDTH 8..110 in
# under 5 s. WIDTH 110 is in the validation grid as for BMC.
PROVE_GRID = [(d, w) for d in (3, 4, 6, 8, 16, 24, 32) for w in (8, 32)]
PROVE_GRID_VALIDATION = [(d, 110) for d in (4, 8, 16, 24, 32)]
PROVE_PARAMS = (_params(PROVE_GRID)
                + _params(PROVE_GRID_VALIDATION, marks=pytest.mark.validation))


def _prove(tmp_path, depth, width, edits=None, prove_k=None):
    src = param_copy(tmp_path / 'param' / 'fifo_checkers', depth, width, edits, prove_k)
    return run_sby(src, SBY, 'prove', tmp_path)


@pytest.mark.parametrize('depth,width', PROVE_PARAMS)
def test_prove(tmp_path, depth, width):
    """k-induction (k = 2) with auxiliary invariants: PASS; the model has the data assertion and exactly the INV invariants."""
    r = _prove(tmp_path, depth, width)
    assert r.status == 'PASS', r.log[-3000:]
    assert 'successful proof by k-induction' in r.log, r.log[-3000:]
    smt = sby_model(r, 'axis_fifo_prove')
    names = set(re.findall(r'; yosys-smt2-assert \d+ (\S+)', smt))
    inv = {n for n in names if 'tb_axis_fifo_sb_formal_inv' in n}
    assert {re.sub(r'.*\.', '', n) for n in inv} == set(INVARIANTS), names
    assert any(n.endswith('a_sb_match') for n in names), names


# The probes of the prove task connect to the DUT signals count, rd, wr and
# mem[j]. Mutations that change the shape of these are covered by BMC
# (test_mutation_fails) instead: never_ready and dup_beat (count / rd fold to
# a constant), stale_capture (the memory is no longer recognized as one).
PROVE_MUTATIONS = [m for m in MUTATIONS if m not in ('never_ready', 'dup_beat', 'stale_capture')]


@pytest.mark.parametrize('mut', PROVE_MUTATIONS)
def test_prove_mutation_not_proven(tmp_path, mut):
    """A mutation is not proven: prove FAIL (basecase) or UNKNOWN (induction), never PASS (D4-W8)."""
    r = _prove(tmp_path, 4, 8, MUTATIONS[mut])
    assert r.status in ('FAIL', 'UNKNOWN'), r.log[-3000:]


def _weaken_invariant(name):
    """Make the invariant's condition contradictory (rst_in = '0' and rst_in = '1'):
    the assertion stays in the model (the probes stay in use, the select guards
    match), but it constrains nothing."""
    old = f"    {name} : assert always\n        (rst_in = '0'"
    return {INV: [(old, old + " and rst_in = '1'")]}


@pytest.mark.parametrize('inv', INVARIANTS)
def test_prove_invariant_needed(tmp_path, inv):
    """Every invariant is needed: without it induction does not go through (UNKNOWN), D3-W8.

    D3: inv_range is needed only when DEPTH is not a power of two
    (unused values of the pointer bits)."""
    r = _prove(tmp_path, 3, 8, _weaken_invariant(inv))
    assert r.status == 'UNKNOWN', r.log[-3000:]


def test_prove_k1_fails(tmp_path):
    """k = 1 is not enough (a_pre/b_pre and the scoreboard's prev registers are
    independent of each other in the induction start state): UNKNOWN. PROVE_K = 2
    is the minimum."""
    r = _prove(tmp_path, 4, 8, prove_k=1)
    assert r.status == 'UNKNOWN', r.log[-3000:]

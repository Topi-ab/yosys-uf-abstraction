"""write_smt2 uf_instance emission for hierarchical cells (Verilog sources).

A marked instance of a user module becomes one uninterpreted function over its
input ports (in port_id order); the return value is the concatenation of the
outputs, with the first output in the most significant bits. No box state, _h
member or hierarchy equations are generated.

The VHDL path (label attribute -> declare-fun) is covered by
tests/vhdl_control_independence and tests/vhdl_pipeline_latency.
"""
import json
import re
import subprocess
from pathlib import Path

import pytest

from conftest import mutated_copy, run_sby, run_yosys

HERE = Path(__file__).resolve().parent


# ---------------------------------------------------------------- helpers

def ys(tmp_path, src, defines=(), post='', wflags='-bv', prep='prep -top top; async2sync'):
    """Read src, run prep (+ post) and write_smt2. Returns (Run, smt2 text or '').
    An .il file is read with read_rtlil (defines are not used)."""
    if src.endswith('.il'):
        assert not defines
        read = f'read_rtlil {HERE / src}'
    else:
        defs = ' '.join(f'-D{d}' for d in defines)
        read = f'read_verilog -formal -sv {defs} {HERE / src}'
    script = (f'{read}; {prep}; '
              + (f'{post}; ' if post else '')
              + f'write_smt2 {wflags} x.smt2')
    r = run_yosys(script, tmp_path)
    smt = tmp_path / 'x.smt2'
    return r, (smt.read_text() if r.returncode == 0 and smt.exists() else '')


def ok(tmp_path, src, **kw):
    r, smt = ys(tmp_path, src, **kw)
    assert r.returncode == 0, r.log[-4000:]
    return r, smt


def err(tmp_path, src, **kw):
    r, _ = ys(tmp_path, src, **kw)
    assert r.returncode != 0, r.log[-4000:]
    return r.log


def declares(smt, sym):
    """All declare-fun lines of the symbol (including the zero-argument form)."""
    return [l for l in smt.splitlines() if l.startswith(f'(declare-fun |{sym}| ')]


def warnings(log):
    return [l for l in log.splitlines() if l.startswith('Warning:')]


def sby_model(r, task_dir, suffix=''):
    return (r.workdir / task_dir / 'model' / f'design_smt2{suffix}.smt2').read_text()


def no_hier_refs(smt, cells):
    """A UF cell must leave no yosys-smt2-cell or _h reference."""
    for c in cells:
        assert not re.search(rf'^; yosys-smt2-cell \S+ {c}$', smt, flags=re.M), c
        assert f'_h {c}|' not in smt, c


# ---------------------------------------------------------------- multiple outputs

def test_multi_output_layout(tmp_path):
    """o0[15:0] before o1[7:0]: 24-bit return, o0 = extract 23 8, o1 = extract 7 0."""
    r, smt = ok(tmp_path, 'multi.sv')
    assert r.uf_warnings == []
    d = declares(smt, 'g')
    assert len(d) == 1, d
    assert d[0].startswith('(declare-fun |g| ((_ BitVec 8) (_ BitVec 16)) (_ BitVec 24))'), d
    assert 'first use: top.u1 (module box): args a[8] b[16] -> o0[23:8] ++ o1[7:0]' in d[0]
    for u in ('u1', 'u2'):
        assert re.search(rf'\(\(_ extract 23 8\) \(\|g\| [^;]*; uf_instance g {u}\.o0$', smt, re.M), u
        assert re.search(rf'\(\(_ extract 7 0\) \(\|g\| [^;]*; uf_instance g {u}\.o1$', smt, re.M), u
    no_hier_refs(smt, ['u1', 'u2'])
    # the box implementation (bvadd, bvxor) is not in the top section
    top = smt.split('; yosys-smt2-module top', 1)[1]
    assert 'bvadd' not in top and 'bvxor' not in top


def test_declare_before_first_use(tmp_path):
    """Exactly one declare-fun, before the first call."""
    _, smt = ok(tmp_path, 'multi.sv')
    lines = smt.splitlines()
    decl = [i for i, l in enumerate(lines) if l.startswith('(declare-fun |g| ')]
    use = [i for i, l in enumerate(lines) if '(|g| ' in l and not l.startswith('(declare-fun')]
    assert len(decl) == 1 and use
    assert decl[0] < min(use)


@pytest.mark.parametrize('task,expected', [
    ('pass', 'PASS'), ('fail', 'FAIL'),
    ('pass_stbv', 'PASS'), ('fail_stbv', 'FAIL'),
    ('pass_stdt', 'PASS'), ('fail_stdt', 'FAIL'),
])
def test_multi_output_sby(sby, task, expected):
    """Congruence PASS, o0[7:0]==o1 FAIL (the slices are independent).
    Same result in the default mode (bitwuzla), with -stbv (yices) and with -stdt
    (z3 without unroll)."""
    r = sby(HERE, 'multi.sby', task)
    assert r.status == expected, r.log[-3000:]
    assert r.uf_warnings == []
    suffix = {'stbv': '_stbv', 'stdt': '_stdt'}.get(task.split('_')[-1], '')
    smt = sby_model(r, f'multi_{task}', suffix)
    assert len(declares(smt, 'g')) == 1
    no_hier_refs(smt, ['u1', 'u2'])


def test_nobv_error(tmp_path):
    """-nobv is an error. The target is a blackbox: otherwise the box's own (dead)
    module text would already fail under -nobv ($add unsupported) before this check."""
    log = err(tmp_path, 'bbox.sv', wflags='-nobv')
    assert 'uf_instance on hierarchical cell top.u1 (module box) requires -bv' in log, log


# ---------------------------------------------------------------- inputs and widths

def test_args_follow_port_order(tmp_path):
    """b_in[16] before a_in[8] in the module: arguments and outputs in port_id order,
    even though the instance connects them in a different order."""
    _, smt = ok(tmp_path, 'ports.sv')
    d = declares(smt, 'w')
    assert len(d) == 1, d
    assert d[0].startswith('(declare-fun |w| ((_ BitVec 16) (_ BitVec 8)) (_ BitVec 12))'), d
    assert 'args b_in[16] a_in[8] -> y1_out[11:4] ++ y0_out[3:0]' in d[0]
    assert re.search(r'\(\(_ extract 11 4\) \(\|w\| .*; uf_instance w u\.y1_out$', smt, re.M)
    assert re.search(r'\(\(_ extract 3 0\) \(\|w\| .*; uf_instance w u\.y0_out$', smt, re.M)


# ---------------------------------------------------------------- conflicts

@pytest.mark.parametrize('defines,builtin', [
    (['IN_SWAP'], False),
    (['OUT_SWAP'], False),
    (['BUILTIN', 'IN_SWAP'], True),
    (['MIDDLE', 'IN_SWAP'], False),
], ids=['inputs', 'outputs', 'builtin_first', 'other_names_between'])
def test_port_order_conflict(tmp_path, defines, builtin):
    """Same port names in a different order under the same symbol is an error, also when
    the first user is a built-in cell or a box with different port names comes in between."""
    post = 'setattr -set uf_instance "f" top/t:$sub' if builtin else ''
    log = err(tmp_path, 'conflict.sv', defines=defines, post=post)
    assert 'Conflicting port order for uf_instance symbol "f"' in log, log


def test_same_port_order_shares_symbol(tmp_path):
    """Control: same-named ports in the same order (m1, m3) share the symbol."""
    r, smt = ok(tmp_path, 'conflict.sv', defines=['SAME'])
    assert len(declares(smt, 'f')) == 1
    assert smt.count('; uf_instance f u') == 2


@pytest.mark.parametrize('define', ['WIDTH', 'SPLIT'])
def test_width_conflict(tmp_path, define):
    """Different argument width, or the same return width 16 split differently (8+8 vs 4+12): error."""
    log = err(tmp_path, 'conflict.sv', defines=[define])
    assert 'Conflicting signatures for uf_instance symbol "f"' in log, log
    if define == 'SPLIT':
        assert 'outputs 8+8' in log and 'outputs 4+12' in log, log


# ---------------------------------------------------------------- built-in + hierarchical

def test_builtin_and_hier_share_symbol(sby):
    """$neg 8->8 and box a[7:0]->y[7:0] under symbol f: one declare-fun, congruence PASS."""
    r = sby(HERE, 'mixed.sby')
    assert r.status == 'PASS', r.log[-3000:]
    assert r.uf_warnings == []
    smt = sby_model(r, 'mixed')
    d = declares(smt, 'f')
    assert len(d) == 1 and d[0].startswith('(declare-fun |f| ((_ BitVec 8)) (_ BitVec 8))'), d
    assert smt.count('(|f| ') >= 2
    assert 'bvneg' not in smt.split('; yosys-smt2-module top', 1)[1]


# ---------------------------------------------------------------- stateful box

@pytest.mark.parametrize('deep', [False, True], ids=['direct', 'deep'])
@pytest.mark.parametrize('kind,ctype', [
    ('DFF', '$dff'), ('MEM', '$mem_v2'), ('ANYSEQ', '$anyseq'),
    ('ANYCONST', '$anyconst'), ('ASSERT', '$assert'),
])
def test_stateful_box_error(tmp_path, kind, ctype, deep):
    """State or a formal cell in the box, or one level deeper, is an error."""
    defines = [f'K_{kind}'] + (['DEEP'] if deep else [])
    log = err(tmp_path, 'stateful.sv', defines=defines)
    m = re.search(r'ERROR: uf_instance cell top\.u \(module box\) must be stateless and '
                  r'combinational, but the module contains (\S+) \((\$\w+)\)', log)
    assert m, log
    assert m.group(2) == ctype
    assert m.group(1).startswith('box.i.' if deep else 'box.'), m.group(1)
    if not deep:
        assert not m.group(1).startswith('box.i.')


STATEFUL_RE = (r'ERROR: uf_instance cell top\.ua \(module box\) must be stateless and '
               r'combinational, but the module contains (\S+) \((\$\w+)\)')


@pytest.mark.parametrize('define,ctype', [
    ('LATCH', '$ff'),
    ('INIT', '$initstate'),
], ids=['latch_async2sync', 'initstate'])
def test_stateful_box_error_latch_initstate(tmp_path, define, ctype):
    """A latch (async2sync turns it into a $ff) and $initstate in the box are errors."""
    log = err(tmp_path, 'undriven.sv', defines=[define])
    m = re.search(STATEFUL_RE, log)
    assert m, log
    assert m.group(2) == ctype, log
    assert m.group(1).startswith('box.'), m.group(1)


def test_stateful_box_error_latch_clk2fflogic(tmp_path):
    """A latch under clk2fflogic (without async2sync) is also a $ff -> error."""
    log = err(tmp_path, 'undriven.sv', defines=['LATCH'], prep='prep -top top; clk2fflogic')
    m = re.search(STATEFUL_RE, log)
    assert m and m.group(2) == '$ff', log


@pytest.mark.parametrize('define,wire', [
    (None, 'box.n'), ('NESTED', 'box.s.n'), ('WB_SUB', 'box.s.n'),
], ids=['direct', 'nested', 'whitebox'])
def test_undriven_wire_error(tmp_path, define, wire):
    """An undriven wire in the box, in an ordinary submodule or in a whitebox submodule
    is an error. An undriven bit is free in every step, so write_smt2 run directly
    (without sby's setundef -anyseq) would otherwise give a false PASS for ya == yb."""
    log = err(tmp_path, 'undriven.sv', defines=[define] if define else [])
    assert ('ERROR: uf_instance cell top.ua (module box) must be a function of its inputs, '
            f'but the module reads the undriven wire {wire} (8 of 8 bits).') in log, log


@pytest.mark.parametrize('deep', [False, True], ids=['direct', 'deep'])
def test_assume_in_box_warns(tmp_path, deep):
    """$assume in the box: 'dropped' warning, export succeeds and the UF is created."""
    r, smt = ok(tmp_path, 'stateful.sv', defines=['K_ASSUME'] + (['DEEP'] if deep else []))
    w = [l for l in warnings(r.log) if '$assume' in l]
    assert len(w) == 1 and 'inside the box is dropped' in w[0], r.log
    assert ('box.i.' in w[0]) == deep
    assert len(declares(smt, 'st')) == 1
    # not counted as an "ignored" warning
    assert r.uf_warnings == []


# ---------------------------------------------------------------- zero inputs

def test_zero_inputs_declare(tmp_path):
    """(declare-fun |k| () (_ BitVec 8)), used as a bare |k|."""
    _, smt = ok(tmp_path, 'zero.sv')
    d = declares(smt, 'k')
    assert len(d) == 1 and d[0].startswith('(declare-fun |k| () (_ BitVec 8))'), d
    assert '(|k|)' not in smt
    assert len(re.findall(r'\(= \(\|top#\d+\| state\) \|k\|\) ; uf_instance k u[12]\.y$', smt, re.M)) == 2


@pytest.mark.parametrize('task,expected', [('plain', 'PASS'), ('unroll', 'PASS'), ('free', 'FAIL')])
def test_zero_inputs_sby(sby, task, expected):
    """The two instances are equal at every step (bitwuzla, also with --unroll).
    Control: the value 7 does not follow from anything (the UF is a free constant)."""
    r = sby(HERE, 'zero.sby', task)
    assert r.status == expected, r.log[-3000:]


# ---------------------------------------------------------------- zero-width ports

def test_zero_width_ports_mixed(tmp_path):
    """Zero-width ports between 8-bit ones are left out of the arguments and the return
    value: (declare-fun |f| ((_ BitVec 8)) (_ BitVec 8)), no BitVec 0. A zero-width input
    is not a "not connected" error, even though ua leaves it out (ub connects { })."""
    r, smt = ok(tmp_path, 'zero_width.il', prep='hierarchy -top top')
    assert 'BitVec 0' not in smt
    d = declares(smt, 'f')
    assert len(d) == 1, d
    assert d[0].startswith('(declare-fun |f| ((_ BitVec 8)) (_ BitVec 8))'), d
    assert d[0].endswith('args a[8] -> y[7:0]'), d
    for u in ('ua', 'ub'):
        assert re.search(rf'\(= \(\|top#\d+\| state\) \(\|f\| \(\|top#\d+\| state\)\)\) '
                         rf'; uf_instance f {u}\.y$', smt, re.M), u
        assert f'{u}.z_out' not in smt, u
    no_hier_refs(smt, ['ua', 'ub', 'uk'])


def test_zero_width_input_only(tmp_path):
    """The only input is zero-width: a zero-argument UF, used as a bare |k|."""
    _, smt = ok(tmp_path, 'zero_width.il', prep='hierarchy -top top')
    d = declares(smt, 'k')
    assert len(d) == 1 and d[0].startswith('(declare-fun |k| () (_ BitVec 8))'), d
    assert re.search(r'\(= \(\|top#\d+\| state\) \|k\|\) ; uf_instance k uk\.y$', smt, re.M)


def test_zero_width_outputs_only_warning(tmp_path):
    """The only output is zero-width: "no output ports" warning, no declare-fun."""
    r, smt = ok(tmp_path, 'zero_width.il', prep='hierarchy -top top')
    assert len(r.uf_warnings) == 1, r.log
    assert ('Ignoring uf_instance attribute "g" on cell top.un (module nobox): '
            'module has no output ports') in r.uf_warnings[0]
    assert declares(smt, 'g') == []
    assert 'uf_instance g' not in smt


# ---------------------------------------------------------------- symbol name collisions

COLLIDES_GEN = 'the symbol name collides with the name |{0}| that write_smt2 generates for module {1}'
RESERVED_CHAR = "the symbol name must not contain '#' or a space"
SMTBMC_NAMES = 'the symbol name collides with the step state and cover names'


@pytest.mark.parametrize('sym,msg', [
    ('top_s', COLLIDES_GEN.format('top_s', 'top')),
    ('box_h', COLLIDES_GEN.format('box_h', 'box')),
    ('box_is', COLLIDES_GEN.format('box_is', 'box')),
    ('top_ex_state_eq', COLLIDES_GEN.format('top_ex_state_eq', 'top')),
    ('top_mk', COLLIDES_GEN.format('top_mk', 'top')),
    ('a#1', RESERVED_CHAR),
    ('a b', RESERVED_CHAR),
    ('s3', SMTBMC_NAMES),
    ('covers_0', SMTBMC_NAMES),
])
def test_symbol_collision_error(tmp_path, sym, msg):
    """A symbol that collides with a name generated by write_smt2 or yosys-smtbmc is an error."""
    log = err(tmp_path, 'single.sv', post=f'setattr -set uf_instance "{sym}" top/u1 top/u2')
    assert f'ERROR: Attribute uf_instance on cell top.u1 has value "{sym}": {msg}' in log, log


@pytest.mark.parametrize('sym', ['ok_f', 's', 'top'])
def test_symbol_not_colliding_accepted(tmp_path, sym):
    """Control: similar but free names are accepted."""
    _, smt = ok(tmp_path, 'single.sv', post=f'setattr -set uf_instance "{sym}" top/u1 top/u2')
    assert len(declares(smt, sym)) == 1


# ---------------------------------------------------------------- --unroll and logic

@pytest.mark.parametrize('solver', ['yices', 'z3', 'bitwuzla'])
@pytest.mark.parametrize('mode', ['plain', 'unroll'])
@pytest.mark.parametrize('bad', [False, True], ids=['pass', 'fail'])
def test_unroll_sby(sby, solver, mode, bad):
    """A UF design with yices, z3 and bitwuzla, with and without --unroll: congruence
    PASS, o1 == x*3 FAIL. The model contains a '; yosys-smt2-uf' marker, from which
    smtio.py selects a logic with uninterpreted functions also in --unroll mode
    (otherwise z3 reports "logic does not support uninterpreted functions")."""
    task = f'{solver}_{mode}' + ('_bad' if bad else '')
    r = sby(HERE, 'unroll.sby', task)
    assert r.status == ('FAIL' if bad else 'PASS'), r.log[-3000:]
    assert 'uninterpreted functions' not in r.log
    smt = sby_model(r, f'unroll_{task}')
    assert re.search(r'^; yosys-smt2-uf$', smt, re.M)
    assert len(declares(smt, 'f')) == 1


@pytest.mark.parametrize('unroll', [False, True], ids=['plain', 'unroll'])
@pytest.mark.parametrize('marked', [True, False], ids=['uf', 'no_uf'])
def test_smtbmc_logic(tmp_path, marked, unroll):
    """z3 set-logic: QF_AUFBV for a UF design also in --unroll mode; without a UF there
    is no marker, and --unroll keeps QF_ABV."""
    post = '' if marked else 'setattr -unset uf_instance top/u1 top/u2'
    _, smt = ok(tmp_path, 'single.sv', post=post)
    assert bool(re.search(r'^; yosys-smt2-uf$', smt, re.M)) == marked
    out = smtbmc(['-s', 'z3'] + (['--unroll'] if unroll else []) +
                 ['-t', '2', '--dump-smt2', 'dump.smt2', 'x.smt2'], tmp_path)
    assert 'Status: PASSED' in out, out
    logic = re.findall(r'^\(set-logic (\S+)\)', (tmp_path / 'dump.smt2').read_text(), re.M)
    assert logic == ['QF_ABV' if unroll and not marked else 'QF_AUFBV'], logic


# ---------------------------------------------------------------- no outputs, unconnected ports

def test_no_outputs_warning(tmp_path):
    """Warning matched by UF_IGNORED_RE; no declare-fun."""
    r, smt = ok(tmp_path, 'noout.sv')
    assert len(r.uf_warnings) == 1, r.log
    assert 'Ignoring uf_instance attribute "no" on cell top.u1 (module box): module has no output ports' \
        in r.uf_warnings[0]
    assert declares(smt, 'no') == []


def test_unconnected_output(tmp_path):
    """u2.o1 open, u1 fully connected: width 24, one declare-fun, no equation for u2.o1."""
    r, smt = ok(tmp_path, 'multi.sv', defines=['OPEN'])
    assert r.uf_warnings == []
    d = declares(smt, 'g')
    assert len(d) == 1 and ' (_ BitVec 24))' in d[0], d
    assert '; uf_instance g u2.o0' in smt
    assert '; uf_instance g u2.o1' not in smt
    assert '; uf_instance g u1.o1' in smt


def test_unconnected_input_error(tmp_path):
    """Verilog .b() is an error."""
    log = err(tmp_path, 'unconn.sv')
    assert 'uf_instance cell top.u (module box): input port b is not connected' in log, log


# ---------------------------------------------------------------- clock

@pytest.mark.parametrize('ctl', [False, True], ids=['parent_clock', 'data_driven'])
def test_clock_argument_warning(tmp_path, ctl):
    """Parent $dff clock on a box input -> warning; driven by data -> none."""
    r, smt = ok(tmp_path, 'clock.sv', defines=['CTL'] if ctl else [])
    hits = [l for l in warnings(r.log) if 'input clk is a clock in the parent' in l]
    assert len(hits) == (0 if ctl else 1), r.log
    assert len(declares(smt, 'c')) == 1
    assert r.uf_warnings == []


# ---------------------------------------------------------------- blackbox target

def test_blackbox_target_smtcheck(tmp_path):
    """hierarchy -smtcheck accepts a marked blackbox instance; write_smt2 succeeds
    in the default mode and with -stbv/-stdt."""
    for flags in ('-bv', '-stbv', '-stdt'):
        r, smt = ok(tmp_path, 'bbox.sv', post='hierarchy -smtcheck', wflags=flags)
        assert len(declares(smt, 'b')) == 1, flags
        assert r.uf_warnings == []
        no_hier_refs(smt, ['u1', 'u2'])


def test_blackbox_unmarked_smtcheck_error(tmp_path):
    """An unmarked blackbox instance still fails under -smtcheck."""
    log = err(tmp_path, 'bbox.sv', defines=['UNMARKED'], post='hierarchy -smtcheck')
    assert "in cell `\\u2' is a blackbox/whitebox module" in log, log


def test_blackbox_simcheck_error(tmp_path):
    """-simcheck stays strict, also for a marked instance."""
    log = err(tmp_path, 'bbox.sv', post='hierarchy -simcheck')
    assert 'is a blackbox/whitebox module' in log, log


@pytest.mark.parametrize('task,expected', [
    ('pass', 'PASS'), ('fail', 'FAIL'), ('pass_stbv', 'PASS'), ('pass_stdt', 'PASS'),
])
def test_blackbox_target_sby(sby, task, expected):
    """sby (runs hierarchy -smtcheck itself): congruence PASS, o1 == x FAIL."""
    r = sby(HERE, 'bbox.sby', task)
    assert r.status == expected, r.log[-3000:]


def test_parametric_blackbox_error(tmp_path):
    """A parametric blackbox is an error."""
    log = err(tmp_path, 'bbox.sv', defines=['PARAM'], prep='hierarchy -top top',
              post='hierarchy -smtcheck')
    assert 'instantiates the parametric blackbox module box' in log, log


# ---------------------------------------------------------------- witness, nested

def smtbmc(args, cwd):
    p = subprocess.run(['yosys-smtbmc'] + args, cwd=cwd, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, text=True, timeout=600)
    return p.stdout


def witness_paths(smt):
    """Paths of witness signals of type blackbox."""
    out = []
    for l in smt.splitlines():
        if l.startswith('; yosys-smt2-witness '):
            w = json.loads(l.split(' ', 2)[2])
            if w['type'] == 'blackbox':
                out.append((tuple(w['path']), w['width']))
    return out


def vcd_scopes(vcd):
    """{scope path: {variable names}} from the VCD header."""
    out, stack = {}, []
    for l in vcd.splitlines():
        t = l.split()
        if t[:1] == ['$scope']:
            stack.append(t[2])
        elif t[:1] == ['$upscope']:
            stack.pop()
        elif t[:1] == ['$var']:
            out.setdefault('.'.join(stack), set()).add(t[4])
        elif t[:1] == ['$enddefinitions']:
            break
    return out


def drop_signal(yw, name):
    """yw without the given signal (its bits are removed from every step)."""
    d = json.loads(yw)
    offs, o = [], 0
    for s in d['signals']:
        offs.append(o)
        o += s['width']
    keep = [i for i, s in enumerate(d['signals']) if s['path'][-1] != name]
    assert len(keep) < len(d['signals'])
    for st in d['steps']:
        b = st['bits'][::-1]
        st['bits'] = ''.join(b[offs[i]:offs[i] + d['signals'][i]['width']] for i in keep)[::-1]
    d['signals'] = [d['signals'][i] for i in keep]
    return json.dumps(d)


@pytest.fixture(scope='module')
def witness_runs(tmp_path_factory):
    out = {}
    for task in ('onebit', 'nested'):
        r = run_sby(HERE, 'witness.sby', task, tmp_path_factory.mktemp(task))
        assert r.status == 'FAIL', r.log[-3000:]
        out[task] = r
    return out


def test_witness_onebit(witness_runs):
    """1-bit valid and 8-bit d are BV variables and blackbox witnesses;
    the VCD shows them as wires of the parent; --check-witness replays the failure."""
    r = witness_runs['onebit']
    task = r.workdir / 'witness_onebit'
    smt = sby_model(r, 'witness_onebit')
    assert re.search(r'^\(declare-fun \|top#\d+\| \(\|top_s\|\) \(_ BitVec 1\)\) ; \\valid$', smt, re.M)
    d = declares(smt, 'h')
    assert len(d) == 1 and d[0].startswith('(declare-fun |h| ((_ BitVec 8)) (_ BitVec 9))'), d
    assert '((_ extract 8 8) (|h| ' in smt
    assert set(witness_paths(smt)) == {(('\\valid',), 1), (('\\d',), 8)}

    yw = json.loads((task / 'engine_0' / 'trace.yw').read_text())
    paths = {tuple(s['path']) for s in yw['signals']}
    assert ('\\valid',) in paths and ('\\d',) in paths, paths

    scopes = vcd_scopes((task / 'engine_0' / 'trace.vcd').read_text())
    assert {'valid', 'd'} <= scopes.get('top', set()), scopes

    out = smtbmc(['-s', 'bitwuzla', '-t', '4', '--yw', 'engine_0/trace.yw', '--check-witness',
                  'model/design_smt2.smt2'], task)
    assert 'Status: PASSED' in out, out


def test_witness_nested(witness_runs, tmp_path):
    """UF cell inside mid. yw path ['\\um', '\\t'], VCD scope top.um contains t.
    Replay requires the blackbox signal: without it --check-witness does not reproduce the failure."""
    r = witness_runs['nested']
    task = r.workdir / 'witness_nested'
    smt = sby_model(r, 'witness_nested')
    assert witness_paths(smt) == [(('\\t',), 8)]  # path inside the mid module
    no_hier_refs(smt, ['ub'])
    assert re.search(r'^; yosys-smt2-cell mid um$', smt, re.M)  # the interpreted mid is kept

    yw_text = (task / 'engine_0' / 'trace.yw').read_text()
    paths = {tuple(s['path']) for s in json.loads(yw_text)['signals']}
    assert ('\\um', '\\t') in paths, paths

    scopes = vcd_scopes((task / 'engine_0' / 'trace.vcd').read_text())
    assert 't' in scopes.get('top.um', set()), scopes

    out = smtbmc(['-s', 'bitwuzla', '-t', '4', '--yw', 'engine_0/trace.yw', '--check-witness',
                  'model/design_smt2.smt2'], task)
    assert 'Status: PASSED' in out, out

    stripped = tmp_path / 'stripped.yw'
    stripped.write_text(drop_signal(yw_text, '\\t'))
    out = smtbmc(['-s', 'bitwuzla', '-t', '4', '--yw', str(stripped), '--check-witness',
                  'model/design_smt2.smt2'], task)
    assert 'Status: FAILED' in out, out


# ---------------------------------------------------------------- cover, feedback

def test_cover_reached(sby):
    """Cover mode reaches a cover that requires a free UF (interpreted: 3*3 = 9 != 5)."""
    r = sby(HERE, 'cover.sby')
    assert r.status == 'PASS', r.log[-3000:]
    assert 'Reached cover statement' in r.log
    no_hier_refs(sby_model(r, 'cover'), ['u1', 'u2'])


def test_feedback_through_box(sby):
    """box u(.a(x), .b(t), .y0(t), .y1(o)): no logic loop error, smtbmc runs."""
    r = sby(HERE, 'feedback.sby')
    assert r.status == 'PASS', r.log[-3000:]
    assert 'logic loop' not in r.log.lower()
    smt = sby_model(r, 'feedback')
    assert re.search(r'\(= \(\|top#\d+\| state\) \(\(_ extract 15 8\) \(\|fb\| ', smt)


# ---------------------------------------------------------------- unmarked instance

def test_unmarked_instance_keeps_h(tmp_path):
    """Unmarked instance u2 stays interpreted (_h is kept), u1 is a UF."""
    r, smt = ok(tmp_path, 'single.sv', defines=['UNMARKED'])
    assert re.search(r'^; yosys-smt2-cell box u2$', smt, re.M)
    assert '(declare-fun |top_h u2| (|top_s|) |box_s|)' in smt
    no_hier_refs(smt, ['u1'])
    assert len(declares(smt, 'f')) == 1


# ---------------------------------------------------------------- module attribute, flatten

def test_module_attribute_no_effect(tmp_path):
    """(* uf_instance *) on a module: 'has no effect' warning, no declare-fun."""
    r, smt = ok(tmp_path, 'modattr.sv')
    assert len(r.uf_warnings) == 1, r.log
    assert 'Attribute uf_instance on module box has no effect: mark the instances' in r.uf_warnings[0]
    assert declares(smt, 'ma') == []


def test_module_attribute_flattened(tmp_path):
    """Module attribute + flatten: warning from the module_uf_instance $scopeinfo."""
    r, smt = ok(tmp_path, 'modattr.sv', post='flatten')
    assert len(r.uf_warnings) == 1, r.log
    assert 'has no effect' in r.uf_warnings[0] and 'flattened instance top.u1' in r.uf_warnings[0]
    assert declares(smt, 'ma') == []


def test_flatten_without_keep_hierarchy_warns(tmp_path):
    """flatten dissolves the marked cell -> warning from $scopeinfo, no declare-fun."""
    r, smt = ok(tmp_path, 'single.sv', post='flatten')
    w = [l for l in r.uf_warnings if 'on flattened instance' in l]
    assert sorted(re.search(r'instance (\S+):', l).group(1) for l in w) == ['top.u1', 'top.u2'], r.log
    assert len(r.uf_warnings) == 2
    assert declares(smt, 'f') == []


def test_flatten_with_keep_hierarchy(tmp_path):
    """keep_hierarchy: the cell survives flatten and is abstracted."""
    r, smt = ok(tmp_path, 'single.sv',
                post='setattr -set keep_hierarchy 1 top/u1 top/u2; flatten')
    assert r.uf_warnings == []
    assert len(declares(smt, 'f')) == 1
    assert smt.count('; uf_instance f u') == 2


# ---------------------------------------------------------------- invalid value

def test_boolean_value_error(tmp_path):
    """A non-string value (Verilog (* uf_instance *) = 1) is an error."""
    log = err(tmp_path, 'single.sv', post='setattr -set uf_instance 1 top/u1')
    assert 'Attribute uf_instance on cell top.u1 must be a string' in log, log


# ---------------------------------------------------------------- submodules inside the box

FUNC_ERR = 'ERROR: uf_instance cell top.ua (module box) must be a function of its inputs, but '
UNCONN_ERR = (FUNC_ERR + 'instance {inst} leaves input port b unconnected ({n} of 8 bits). '
              'An unconnected input of a submodule is free in every step (like $anyseq), so a '
              'function of the current inputs does not over-approximate the box; connect the '
              'port (e.g. to a constant) or remove the marking.')
BB_ERR = (FUNC_ERR + 'it contains the instance box.s of the unmarked blackbox module bbx. '
          'The outputs of an unmarked blackbox are free in every step (like $anyseq), so a '
          'function of the current inputs does not over-approximate the box; mark the instance '
          'with uf_instance (a nested uninterpreted function) or remove the marking of the box.')
UNDRIVEN_ERR = (FUNC_ERR + 'the module reads the undriven wire box.n (8 of 8 bits).')
SUBFUNC_TASKS = ('unconn', 'deep', 'partial', 'undriven_in', 'bb', 'bb_uf',
                 'control', 'nomark', 'nomark_deep')
PARTIAL_CONNECT = 'cd box; connect -port s \\b a[3:0]; cd ..'


@pytest.mark.parametrize('defines,post,inst,n', [
    (['UNCONN'], '', 'box.s', 8),
    (['DEEP'], '', 'box.m.s', 8),
    ([], PARTIAL_CONNECT, 'box.s', 4),
], ids=['unconn', 'deep', 'partial'])
def test_submodule_input_unconnected_error(tmp_path, defines, post, inst, n):
    """An unconnected (or partially connected) input of a submodule inside the box is
    free in every step -> an error that names the instance path and the missing bits.
    Without the check UNCONN/DEEP would give a false PASS and PARTIAL a solver error
    'incompatible types'."""
    log = err(tmp_path, 'subfunc.sv', defines=defines, post=post)
    assert UNCONN_ERR.format(inst=inst, n=n) in log, log


def test_submodule_input_undriven_error(tmp_path):
    """A submodule input connected to an undriven wire -> the undriven-wire error."""
    log = err(tmp_path, 'subfunc.sv', defines=['UNDRIVEN_IN'])
    assert UNDRIVEN_ERR in log, log


def test_unmarked_blackbox_in_box_error(tmp_path):
    """An unmarked blackbox instance in the box -> error (without the check the solver
    would fail with 'undefined sort: bbx_s')."""
    log = err(tmp_path, 'subfunc.sv', defines=['BB'])
    assert BB_ERR in log, log


def test_marked_blackbox_in_box_accepted(tmp_path):
    """A blackbox marked with uf_instance inside the box (nested UF) is accepted."""
    r, smt = ok(tmp_path, 'subfunc.sv', defines=['BB_UF'])
    assert r.uf_warnings == []
    assert len(declares(smt, 'f')) == 1
    no_hier_refs(smt, ['ua', 'ub'])


def test_fully_connected_submodule_accepted(tmp_path):
    """Control: a fully connected submodule in the box."""
    r, smt = ok(tmp_path, 'subfunc.sv')
    assert r.uf_warnings == []
    assert len(declares(smt, 'f')) == 1


@pytest.mark.parametrize('task,expected,msg', [
    ('unconn', 'ERROR', UNCONN_ERR.format(inst='box.s', n=8)),
    ('deep', 'ERROR', UNCONN_ERR.format(inst='box.m.s', n=8)),
    # sby's hierarchy -smtcheck pads the short input with zeros back to 8 bits
    ('partial', 'PASS', 'Resizing cell port box.s.b from 4 bits to 8 bits'),
    ('undriven_in', 'ERROR', None),
    ('bb', 'ERROR', "Module `\\bbx' referenced in module `\\box' in cell `\\s' "
                    "is a blackbox/whitebox module."),
    ('bb_uf', 'PASS', None),
    ('control', 'PASS', None),
    # control: the unmarked design really fails (free bits differ between the instances)
    ('nomark', 'FAIL', None),
    ('nomark_deep', 'FAIL', None),
], ids=SUBFUNC_TASKS)
def test_submodule_function_sby(sby, task, expected, msg):
    """The same at sby level. unconn and deep would give a false PASS without the check
    (FAIL when unmarked); they are an ERROR with the yosys message."""
    r = sby(HERE, 'subfunc.sby', task)
    assert r.status == expected, r.log[-3000:]
    if msg:
        # the yosys messages (warnings too) are in the logs of the task directory
        logs = r.log + ''.join(f.read_text() for f in
                               sorted((r.workdir / f'subfunc_{task}').rglob('*.log')))
        assert msg in logs, r.log[-3000:]
    if task == 'undriven_in':
        # sby's setundef -anyseq turns the undriven wire into an $anyseq cell
        m = re.search(STATEFUL_RE, r.log)
        assert m and m.group(2) == '$anyseq', r.log[-3000:]


# ---------------------------------------------------------------- inout ports and reserved names

def test_inout_port_error(tmp_path):
    """An unconnected inout port -> a clear error (not an assertion failure)."""
    log = err(tmp_path, 'inout.sv', defines=['UNCONN'], prep='prep -top top')
    assert ('ERROR: uf_instance cell top.u (module boxio): port a is an inout port. An '
            'uninterpreted function has only inputs (arguments) and outputs (the result); '
            'remove the marking or split the port into an input and an output.') in log, log
    assert 'Assert' not in log


def test_inout_port_connected_error(tmp_path):
    """A connected inout hits the generic direction error of write_smt2."""
    log = err(tmp_path, 'inout.sv', prep='prep -top top')
    assert 'ERROR: Unsupported or unknown directionality on port a of cell top.u (boxio).' in log, log


RESERVED_SYMS = [
    # common SMT-LIB operators, constants and sorts
    'bvadd', 'true', 'false', 'and', 'or', 'not', 'ite', 'select', 'store', '=',
    'distinct', 'extract', 'concat', 'bvmul', 'let', 'assert', 'Bool', 'BitVec', '@x', '.x',
    # other classes: reserved words, commands, BV, arrays, Int/Real
    'forall', 'exists', 'par', 'as', '!', '_', 'declare-fun', 'check-sat', 'push',
    'set-logic', 'xor', '=>', 'repeat', 'zero_extend', 'sign_extend', 'rotate_left',
    'bvudiv', 'bvult', 'bvcomp', 'bv2nat', 'Array', 'Int', 'Real', '+', 'div', 'mod',
    '<=', 'to_real', 'divisible',
    # z3 built-ins for which z3 rejects a declare-fun ("builtin symbol ... has the
    # same argument sorts"), and the SMT-LIB 2.7 overflow predicates
    'bvsdiv_i', 'bvurem_i', 'bvredor', 'bvsdiv0', 'bvumul_noovfl', 'ext_rotate_left',
    'iff', 'equiv', 'to_fp', 'bvuaddo', 'bvnego', 'ubv_to_int', 'int_to_bv',
    # the rest of the backend's list (SMT-LIB 2.7 and z3)
    'bvsaddo', 'bvumulo', 'bvsmulo', 'bvusubo', 'bvssubo', 'bvsdivo', 'sbv_to_int',
    'bvredand', 'bvudiv_i', 'bvsrem_i', 'bvsmod_i', 'bvudiv0', 'bvsrem0', 'bvurem0',
    'bvsmod0', 'bvsmul_noovfl', 'bvsmul_noudfl', 'ext_rotate_right', 'equals', '&&',
    'case-def', 'char.is_digit', 'char.to_int', 'str.from_sbv', 'str.from_ubv',
]
assert len(set(RESERVED_SYMS)) == len(RESERVED_SYMS)
RESERVED_MSG = ('the symbol name is a reserved word or a predefined symbol of SMT-LIBv2 '
                "(or starts with '@' or '.', which are reserved for solvers). Use a different name.")


@pytest.mark.parametrize('sym', RESERVED_SYMS)
@pytest.mark.parametrize('hier', [True, False], ids=['hier', 'cell'])
def test_reserved_symbol_error(tmp_path, sym, hier):
    """A reserved or predefined SMT-LIB name as the symbol is an error, both on an
    instance and on a built-in $add cell."""
    target = 'top/u' if hier else 'top/t:$add'
    log = err(tmp_path, 'reserved.sv', defines=['HIER'] if hier else [],
              post=f'setattr -set uf_instance "{sym}" {target}')
    cell = r'top\.u' if hier else r'top\.\S*\$add\$\d+'
    m = re.search(rf'ERROR: Attribute uf_instance on cell {cell} has value "(.*?)": (.*)$',
                  log, re.M)
    assert m, log
    assert m.group(1) == sym, log
    assert m.group(2) == RESERVED_MSG, log


@pytest.mark.parametrize('sym', ['myadd', 'bvadd_', 'select1', 'x.', 'x@',
                                 # close to z3 names
                                 'bvsdiv_i_', 'bvredor1', 'iff_', 'my_to_fp', 'char_to_int'])
@pytest.mark.parametrize('hier', [True, False], ids=['hier', 'cell'])
def test_reserved_symbol_near_miss_accepted(tmp_path, sym, hier):
    """Control: names close to reserved names are accepted."""
    target = 'top/u' if hier else 'top/t:$add'
    _, smt = ok(tmp_path, 'reserved.sv', defines=['HIER'] if hier else [],
                post=f'setattr -set uf_instance "{sym}" {target}')
    assert len(declares(smt, sym)) == 1


def test_reserved_symbol_sby(sby):
    """At sby level: a reserved name is an ERROR with the yosys message, not a solver
    crash (BrokenPipeError)."""
    r = sby(HERE, 'reserved.sby')
    assert r.status == 'ERROR', r.log[-3000:]
    assert 'has value "bvadd": ' + RESERVED_MSG in r.log, r.log[-3000:]
    assert 'BrokenPipeError' not in r.log


# ---------------------------------------------------------------- loops and other instances

LOOP_ERR = (FUNC_ERR + 'its outputs depend on a combinational loop through {at}. Where a '
            'loop passes through a submodule instance, the fed-back bits are free variables in '
            'the SMT model (an unconstrained fixpoint), so the box has no unique value for its '
            'inputs and a function of the current inputs does not over-approximate it; break the '
            'loop or remove the marking.')
LOOP_RE = re.escape(LOOP_ERR).replace(re.escape('{at}'), r'(\S+)')
WB_ERR = (FUNC_ERR + 'it contains the instance {inst} of the unmarked whitebox module wbx. '
          'write_smt2 does not export whitebox modules (they are treated as blackboxes), so the '
          'instance has no semantics in the SMT model; mark the instance with uf_instance (a '
          'nested uninterpreted function), remove the whitebox attribute or remove the marking '
          'of the box.')
LOOP_TASKS = ('inst', 'pass2', 'deep', 'inner')


@pytest.mark.parametrize('define,path', [
    (None, 'box.t'), ('PASS2', 'box.t'), ('DEEP', 'box.m.t'), ('INNER', 'box.t'),
], ids=LOOP_TASKS)
def test_loop_in_box_error(tmp_path, define, path):
    """A combinational loop through an instance inside the box is an error. Without the
    check direct write_smt2 and sby would give a false PASS (the unmarked design FAILs)."""
    log = err(tmp_path, 'loop.sv', defines=[define] if define else [])
    m = re.search(LOOP_RE, log)
    assert m, log
    assert re.fullmatch(re.escape(path) + r'\[\d\]', m.group(1)), log


def test_loop_cells_error(tmp_path):
    """Control: a loop through built-in cells only is a logic loop error."""
    log = err(tmp_path, 'loop.sv', defines=['CELLS'])
    assert 'ERROR: Found logic loop in module box!' in log, log


def test_no_loop_accepted(tmp_path):
    """Control: the instance has x = a and y = a ^ b, the box connects x to b. A loop at
    cell level, but not at bit level (with the submodule's dependencies) -> accepted."""
    r, smt = ok(tmp_path, 'loop.sv', defines=['NOLOOP'])
    assert r.uf_warnings == []
    assert len(declares(smt, 'f')) == 1


@pytest.mark.parametrize('task,expected', [
    ('inst', 'ERROR'), ('pass2', 'ERROR'), ('deep', 'ERROR'), ('inner', 'ERROR'),
    ('cells', 'ERROR'), ('noloop', 'PASS'),
    # control: the unmarked design really fails (ua and ub have their own free t)
    ('nomark', 'FAIL'),
])
def test_loop_sby(sby, task, expected):
    """Loops at sby level. inst, pass2, deep and inner would give a false PASS without
    the check."""
    r = sby(HERE, 'loop.sby', task)
    assert r.status == expected, r.log[-3000:]
    if task in LOOP_TASKS:
        assert re.search(LOOP_RE, r.log), r.log[-3000:]


SMT_ERR = (FUNC_ERR + 'it contains the unmarked instance {inst} of the smtlib2_module module {mod}. '
           'yosys cannot verify that the user-written SMT-LIB of an smtlib2_module is a function '
           'of its inputs: an smtlib2_comb_expr may refer to the state (e.g. (|m_is| state)) and '
           'an output without one is a free function of the state, so a function of the current '
           'inputs need not over-approximate the box; mark the instance with uf_instance (a '
           'nested uninterpreted function) or remove the marking of the box.')


@pytest.mark.parametrize('define,inst,mod', [
    ('SMTLIB2', 'box.s', 'smtadd'),
    ('SMT_NOEXPR', 'box.s', 'smtnoexpr'),
    ('SMT_NOEXPR_DEEP', 'box.m.s', 'smtnoexpr'),
    ('SMT_HALF', 'box.s', 'smthalf'),
    ('SMT_HALF_OK', 'box.s', 'smthalf'),
    ('SMT_FULL', 'box.s', 'smtfull'),
    ('SMT_STATEREF', 'box.s', 'smtsr'),
    ('SMT_STATEREF2', 'box.s', 'smtsr2'),
    ('SMT_WB', 'box.s', 'smtwb'),
], ids=['comb_expr', 'noexpr', 'deep', 'half', 'half_ok', 'full', 'stateref', 'stateref2',
        'whitebox'])
def test_smtlib2_module_in_box_error(tmp_path, define, inst, mod):
    """An unmarked smtlib2_module instance in the output cone of the box is always an
    error, like an unmarked blackbox. yosys cannot verify that an smtlib2_comb_expr is a
    function of the inputs: stateref/stateref2 refer to the state ((|smtsr_n y| state)),
    which would otherwise give a false PASS; an output without an expression (noexpr,
    deep, half) is a free function of the state. whitebox: the error names the
    smtlib2_module instead of reporting an undriven wire box.s.y."""
    log = err(tmp_path, 'other.sv', defines=[define])
    assert SMT_ERR.format(inst=inst, mod=mod) in log, log[-3000:]
    assert 'undriven' not in log, log[-3000:]


@pytest.mark.parametrize('define', ['SMT_UF', 'SMT_WB_UF'], ids=['blackbox', 'whitebox'])
def test_marked_smtlib2_module_in_box_accepted(tmp_path, define):
    """Control: an smtlib2_module instance marked with uf_instance inside the box is a
    nested UF (a function by definition) -> accepted, also in whitebox form."""
    r, smt = ok(tmp_path, 'other.sv', defines=[define])
    assert r.uf_warnings == []
    assert len(declares(smt, 'f')) == 1
    assert len(declares(smt, 'inner')) == 1


def test_smtlib2_initstate_error(tmp_path):
    """The smtlib2_comb_expr (ite (|smtis_is| state) a (bvnot a)) depends on time.
    Without the check sby would give a false PASS (the unmarked control FAILs)."""
    log = err(tmp_path, 'initstate.sv')
    assert SMT_ERR.format(inst='box.s', mod='smtis') in log, log[-3000:]


@pytest.mark.parametrize('task,expected', [('mark', 'ERROR'), ('nomark', 'FAIL')])
def test_smtlib2_initstate_sby(sby, task, expected):
    """The same at sby level: mark is an ERROR, the unmarked control FAILs."""
    r = sby(HERE, 'initstate.sby', task)
    assert r.status == expected, r.log[-3000:]
    if expected == 'ERROR':
        assert SMT_ERR.format(inst='box.s', mod='smtis') in r.log, r.log[-3000:]


@pytest.mark.parametrize('task,expected', [
    ('smtlib2', 'ERROR'), ('smtlib2_nomark', 'PASS'),
    ('noexpr', 'ERROR'), ('noexpr_nomark', 'FAIL'),
    ('full', 'ERROR'), ('full_nomark', 'PASS'),
    ('stateref', 'ERROR'), ('stateref_nomark', 'FAIL'),
    ('smt_uf', 'PASS'), ('smt_wb_uf', 'PASS'),
])
def test_smtlib2_module_in_box_sby(sby, task, expected):
    """smtlib2_module instances at sby level (hierarchy -smtcheck accepts an
    smtlib2_module). noexpr and stateref would give a false PASS without the check
    (the unmarked controls FAIL). The unmarked controls smtlib2_nomark and full_nomark
    really PASS: one remedy is to remove the marking of the outer box.
    smt_uf/smt_wb_uf: a marked smtlib2_module instance (the other remedy) -> PASS."""
    r = sby(HERE, 'other.sby', task)
    assert r.status == expected, r.log[-3000:]
    if expected == 'ERROR':
        mod = {'smtlib2': 'smtadd', 'noexpr': 'smtnoexpr', 'full': 'smtfull',
               'stateref': 'smtsr'}[task]
        assert SMT_ERR.format(inst='box.s', mod=mod) in r.log, r.log[-3000:]


def test_whitebox_in_box_error(tmp_path):
    """An unmarked whitebox instance inside the box is an error. write_smt2 does not
    export whitebox modules, so a direct export would refer to the undefined sort wbx_s
    (z3/yices: solver error; --unroll mode would skip it and give a PASS)."""
    log = err(tmp_path, 'other.sv', defines=['WB'])
    assert WB_ERR.format(inst='box.s') in log, log


def test_marked_whitebox_in_box_accepted(tmp_path):
    """Control: a whitebox instance marked with uf_instance inside the box (nested UF)."""
    r, smt = ok(tmp_path, 'other.sv', defines=['WB_UF'])
    assert r.uf_warnings == []
    assert len(declares(smt, 'f')) == 1


@pytest.mark.parametrize('define,path', [
    ('XLEVEL', 'box.t'), ('DEEP2', 'box.m.n.t'), ('ROT', 'box.t'),
], ids=['xlevel', 'deep2', 'rot'])
def test_loop_in_box_error_more(tmp_path, define, path):
    """More loop cases: a loop across two hierarchy levels (the box connects the output
    of instance m to its input, and the dependency goes through m's own instance), a loop
    on the third level (box.m.n) and a bit-level rotation (b = t rotated)."""
    log = err(tmp_path, 'loop.sv', defines=[define])
    m = re.search(LOOP_RE, log)
    assert m, log
    assert re.fullmatch(re.escape(path) + r'\[\d\]', m.group(1)), log


def test_no_loop_inner_uf_accepted(tmp_path):
    """Control: NOLOOP with a nested uf_instance instance. The marked instance uses the
    bit-level dependencies of its module (x = a), so there is no loop."""
    r, smt = ok(tmp_path, 'loop.sv', defines=['INNER_NOLOOP'])
    assert r.uf_warnings == []
    assert len(declares(smt, 'f')) == 1


@pytest.mark.parametrize('task,expected', [
    ('xlevel', 'ERROR'), ('deep2', 'ERROR'), ('rot', 'ERROR'),
])
def test_loop_sby_more(sby, task, expected):
    """More loop cases at sby level."""
    r = sby(HERE, 'loop.sby', task)
    assert r.status == expected, r.log[-3000:]
    if expected == 'ERROR':
        assert re.search(LOOP_RE, r.log), r.log[-3000:]


def test_smtlib2_module_loop_error(tmp_path):
    """A marked smtlib2_module instance is conservatively "every output depends on every
    input", so a loop through it (t = a + t) is an error."""
    log = err(tmp_path, 'other.sv', defines=['SMTLIB2_LOOP'])
    m = re.search(LOOP_RE, log)
    assert m and re.fullmatch(r'box\.t\[\d\]', m.group(1)), log


def test_whitebox_in_box_deep_error(tmp_path):
    """An unmarked whitebox in a submodule of the box (box.m.s) is an error."""
    log = err(tmp_path, 'other.sv', defines=['WB_DEEP'])
    assert WB_ERR.format(inst='box.m.s') in log, log


@pytest.mark.parametrize('task,expected', [
    ('sub', 'PASS'), ('deep', 'PASS'), ('wrap', 'PASS'), ('sub_bad', 'FAIL'),
    ('sub_yices', 'PASS'), ('sub_z3', 'PASS'),
])
def test_feedback_through_box_with_submodules(sby, task, expected):
    """External feedback through a marked box is allowed even when the box contains
    instances (one or two levels) or the box is inside an unmarked module.
    sub_bad: the assertion o == x fails (the model is really run)."""
    r = sby(HERE, 'feedback2.sby', task)
    assert r.status == expected, r.log[-3000:]
    assert 'logic loop' not in r.log.lower()
    assert not re.search(LOOP_RE, r.log)
    assert '|fb|' in sby_model(r, f'feedback2_{task}')


@pytest.mark.parametrize('sym,expected', [
    ('bvsdiv_i', 'ERROR'), ('bvredor', 'ERROR'), ('iff', 'ERROR'), ('bvuaddo', 'ERROR'),
    # control: a close name is fine for z3
    ('bvsdiv_i_', 'PASS'),
])
def test_reserved_z3_symbol_sby(sby, tmp_path, sym, expected):
    """At sby level with z3: a z3 built-in name is a yosys error, not a solver error
    ("builtin symbol ... has the same argument sorts")."""
    src = mutated_copy(HERE, tmp_path / 'mut' / 'rz3', {'reserved.sby': [
        ('smtbmc bitwuzla', 'smtbmc z3'),
        ('uf_instance "bvadd"', f'uf_instance "{sym}"'),
    ]})
    r = sby(src, 'reserved.sby')
    assert r.status == expected, r.log[-3000:]
    assert 'Solver Error' not in r.log, r.log[-3000:]
    if expected == 'ERROR':
        assert f'has value "{sym}": ' + RESERVED_MSG in r.log, r.log[-3000:]


# ---------------------------------------------------------------- uf_disable

NOT_BOOL = 'which is not a boolean'


def other_warnings(log):
    """Warnings without the -bv deprecation notice."""
    return [w for w in warnings(log) if 'are now the default' not in w]


def stripped(tmp_path, src, prep, wflags='-bv', post='', defines=()):
    """The same design without the uf_instance and uf_disable attributes: an unmarked
    reference with the same src attributes (source lines do not change)."""
    sub = tmp_path / 'stripped'
    sub.mkdir(exist_ok=True)
    unset = 'setattr -unset uf_instance -unset uf_disable */*'
    r, smt = ys(sub, src, defines=defines, prep=prep, wflags=wflags,
                post=f'{post}; {unset}' if post else unset)
    assert r.returncode == 0, r.log[-4000:]
    assert 'uf_instance' not in smt
    return smt


PREP_UF = 'prep -top top; async2sync'
PREP_NOUF = 'hierarchy -top top -chparam UF_MODE 0; prep -top top; async2sync'


def test_disable_param_default_uf(tmp_path):
    """UF_MODE = 1 (default) -> uf_disable = 0, the boxes are the UF f."""
    r, smt = ok(tmp_path, 'disable.sv', prep=PREP_UF)
    assert r.uf_warnings == [] and other_warnings(r.log) == [], r.log
    assert len(declares(smt, 'f')) == 1
    no_hier_refs(smt, ['u1', 'u2'])


@pytest.mark.parametrize('wflags', ['-bv', '-stbv', '-stdt', ''])
def test_disable_param_off_identical(tmp_path, wflags):
    """UF_MODE = 0 -> uf_disable = 1: the model is the same as without the marks
    (the same lines; the order of two hierarchy lines may differ, because even a
    no-op setattr in the reference changes it), also without -bv, where a marked
    hierarchical cell would be an error."""
    r, smt = ok(tmp_path, 'disable.sv', prep=PREP_NOUF, wflags=wflags)
    assert r.uf_warnings == [] and other_warnings(r.log) == [], r.log
    assert declares(smt, 'f') == []
    assert re.search(r'^; yosys-smt2-cell box u1$', smt, re.M)
    assert sorted(smt.splitlines()) == sorted(stripped(tmp_path, 'disable.sv', PREP_NOUF, wflags=wflags).splitlines())


def test_disable_param_on_differs(tmp_path):
    """Control for the identity test: the UF model differs from the unmarked one."""
    _, smt = ok(tmp_path, 'disable.sv', prep=PREP_UF)
    assert smt != stripped(tmp_path, 'disable.sv', PREP_UF)


@pytest.mark.parametrize('mode,expected_on', [
    ('1', {'e_zero', 'p_not', 'e_str', 'e_bit'}),
    ('0', {'e_zero', 'e_str', 'e_bit'}),
])
def test_disable_verilog_value_forms(tmp_path, mode, expected_on):
    """read_verilog value forms: (* uf_disable *) and = 1 (32-bit 1), = 0,
    = !UF_MODE and = 1'b1/1'b0 (1-bit), = "true"/"false" (strings)."""
    prep = f'hierarchy -top top -chparam UF_MODE {mode}; prep -top top'
    r, smt = ok(tmp_path, 'disval.sv', prep=prep)
    assert r.uf_warnings == [] and other_warnings(r.log) == [], r.log
    assert set(uf_decls_hier(smt)) == expected_on
    for c in ('u0', 'u1', 'u4', 'u6'):
        assert re.search(rf'^; yosys-smt2-cell box {c}$', smt, re.M), c


def uf_decls_hier(smt):
    """Symbols of the UF declarations (declare-fun line comment '; uf_instance, first use')."""
    return {m.group(1) for m in re.finditer(r'^\(declare-fun \|([^|]+)\| .*; uf_instance, first use', smt, re.M)}


@pytest.mark.parametrize('value,disabled', [
    ('1', True), ('0', False), ("1'b1", True), ("1'b0", False), ("32'd1", True),
    ('2', True), ('"true"', True), ('"TRUE"', True), ('"True"', True), ('"1"', True),
    ('"false"', False), ('"FALSE"', False), ('"0"', False),
])
def test_disable_setattr_values(tmp_path, value, disabled):
    """setattr values (integer, bit constant, strings in any case). Off -> the same
    model as without the mark."""
    post = f'setattr -set uf_disable {value} top/u1 top/u2'
    r, smt = ok(tmp_path, 'single.sv', post=post)
    assert r.uf_warnings == [], r.log
    if disabled:
        assert declares(smt, 'f') == []
        assert smt == stripped(tmp_path, 'single.sv', 'prep -top top; async2sync')
    else:
        assert len(declares(smt, 'f')) == 1


@pytest.mark.parametrize('value,shown', [
    ('"yes"', '"yes"'), ('""', '""'), ('"on"', '"on"'), ("1'bx", "1'x"), ("2'b1x", "2'1x"),
])
@pytest.mark.parametrize('marked', [True, False], ids=['marked', 'unmarked'])
def test_disable_invalid_value_error(tmp_path, value, shown, marked):
    """A value other than a boolean is an error that names the cell and the value
    (also without uf_instance: a typo must not silently change the model)."""
    log = err(tmp_path, 'single.sv', defines=[] if marked else ['UNMARKED'],
              post=f'setattr -set uf_disable {value} top/u2')
    assert f'ERROR: Attribute uf_disable on cell top.u2 has value {shown}, {NOT_BOOL}' in log, log


@pytest.mark.parametrize('mod', ['blackbox', 'whitebox'])
def test_disable_blackbox_error(tmp_path, mod):
    """uf_disable = 1 on an instance of a blackbox/whitebox module is an error: there
    is no implementation of its own (the outputs would be free)."""
    post = 'setattr -set uf_disable 1 top/u1'
    if mod == 'whitebox':
        post = 'setattr -mod -unset blackbox -set whitebox 1 =box; ' + post
    log = err(tmp_path, 'bbox.sv', post=post)
    assert (f'ERROR: Cell top.u1 instantiates the {mod} module box and has uf_disable set: '
            'a concrete export of the instance does not exist') in log, log
    assert 'Remove uf_disable (or set it false)' in log


def test_disable_false_blackbox_accepted(tmp_path):
    """Control: uf_disable = 0 on a blackbox instance is an ordinary UF."""
    r, smt = ok(tmp_path, 'bbox.sv', post='setattr -set uf_disable 0 top/u1 top/u2; hierarchy -smtcheck')
    assert r.uf_warnings == []
    assert len(declares(smt, 'b')) == 1


def test_disable_blackbox_smtcheck_error(tmp_path):
    """hierarchy -smtcheck does not exempt a blackbox instance whose mark is switched off."""
    log = err(tmp_path, 'bbox.sv', post='setattr -set uf_disable 1 top/u2; hierarchy -smtcheck')
    assert ("in cell `\\u2' is a blackbox/whitebox module (the uf_instance marking of the cell "
            'is switched off with uf_disable)') in log, log


def test_disable_smtlib2_module_interpreted(tmp_path):
    """An smtlib2_module instance has an implementation of its own (smtlib2_comb_expr),
    so uf_disable = 1 is accepted; inside a box it is then unmarked -> error."""
    log = err(tmp_path, 'other.sv', defines=['SMT_UF'], post='setattr -set uf_disable 1 box/s')
    assert SMT_ERR.format(inst='box.s', mod='smtadd') in log, log[-3000:]
    # the same without the mark of the box: an interpreted smtlib2_module instance is accepted
    r, smt = ok(tmp_path, 'other.sv', defines=['SMT_UF'],
                post='setattr -set uf_disable 1 box/s; setattr -unset uf_instance top/*')
    assert declares(smt, 'inner') == [] and declares(smt, 'f') == []


def test_disable_without_mark_warning(tmp_path):
    """uf_disable without uf_instance on the same cell -> warning, model unchanged."""
    r, smt = ok(tmp_path, 'single.sv', defines=['UNMARKED'], post='setattr -set uf_disable 1 top/u2')
    assert len(r.uf_warnings) == 1, r.log
    assert ('Attribute uf_disable on cell top.u2 has no effect: the cell has no uf_instance '
            'attribute.') in r.uf_warnings[0]
    assert len(declares(smt, 'f')) == 1


def test_disable_module_attribute_warning(tmp_path):
    """A module-level uf_disable has no effect (the instances stay UFs), warning."""
    r, smt = ok(tmp_path, 'single.sv', post='setattr -mod -set uf_disable 1 box')
    assert len(r.uf_warnings) == 1, r.log
    assert 'Attribute uf_disable on module box has no effect' in r.uf_warnings[0]
    assert len(declares(smt, 'f')) == 1


def test_disable_module_attribute_flattened(tmp_path):
    """After flatten, module_uf_disable in $scopeinfo -> warning."""
    r, _ = ok(tmp_path, 'single.sv', post='setattr -mod -set uf_disable 1 box; flatten')
    w = [l for l in r.uf_warnings if 'uf_disable on module box' in l]
    assert len(w) == 2 and all('flattened instance' in l for l in w), r.log


@pytest.mark.parametrize('sym,msg', [
    ('a b', "must not contain '#' or a space"),
    ('bvadd', 'reserved word or a predefined symbol'),
    ('top_s', 'collides with the name |top_s|'),
])
@pytest.mark.parametrize('hier', [True, False], ids=['hier', 'cell'])
def test_disable_symbol_still_checked(tmp_path, sym, msg, hier):
    """The symbol name is validated also while the mark is switched off, so that a
    typo is found in both modes."""
    target = 'top/u' if hier else 'top/t:$add'
    log = err(tmp_path, 'reserved.sv', defines=['HIER'] if hier else [],
              post=f'setattr -set uf_instance "{sym}" -set uf_disable 1 {target}')
    assert re.search(rf'ERROR: Attribute uf_instance on cell \S+ has value "{re.escape(sym)}": .*'
                     + re.escape(msg), log), log


def test_disable_flatten_no_warning(tmp_path):
    """A switched-off mark does not warn when flattened (interpretation was requested);
    a mark that is on still warns."""
    r, smt = ok(tmp_path, 'single.sv', post='setattr -set uf_disable 1 top/u1; flatten')
    w = [l for l in r.uf_warnings if 'on flattened instance' in l]
    assert len(w) == 1 and 'top.u2' in w[0], r.log
    r, smt = ok(tmp_path, 'single.sv', post='setattr -set uf_disable 1 top/u1 top/u2; flatten')
    assert r.uf_warnings == [], r.log
    assert declares(smt, 'f') == []


def test_disable_flatten_invalid_value_error(tmp_path):
    """An invalid value also in $scopeinfo (cell_uf_disable) is an error."""
    log = err(tmp_path, 'single.sv', post='setattr -set uf_disable "maybe" top/u1; flatten')
    assert 'Attribute uf_disable on flattened instance top.u1 has value "maybe"' in log, log


def test_disable_mixed_instances(tmp_path):
    """Same symbol, one instance switched off -> one declare-fun, u2 interpreted."""
    r, smt = ok(tmp_path, 'single.sv', post='setattr -set uf_disable 1 top/u2')
    assert r.uf_warnings == []
    assert len(declares(smt, 'f')) == 1
    assert re.search(r'^; yosys-smt2-cell box u2$', smt, re.M)
    no_hier_refs(smt, ['u1'])


@pytest.mark.parametrize('task,expected', [
    ('sv_uf', 'PASS'), ('sv_uf_bad', 'FAIL'), ('sv_nouf_bad', 'PASS'),
    ('vhdl_uf', 'PASS'), ('vhdl_uf_bad', 'FAIL'), ('vhdl_nouf_bad', 'PASS'),
])
def test_disable_sby(sby, task, expected):
    """uf_disable with sby: in UF mode the assertion o1 == 3 * x fails (the UF is free),
    in the non-UF model (UF_MODE = 0 / false) it holds; congruence holds in UF mode."""
    r = sby(HERE, 'disable.sby', task)
    assert r.status == expected, r.log[-3000:]
    # VHDL: u3 with only uf_disable warns (tb_uf_disable_formal.vhdl)
    assert all('cell tb_uf_disable_formal.u3 has no effect' in w for w in r.uf_warnings), r.uf_warnings
    model = sby_model(r, f'disable_{task}')
    assert ('(declare-fun |f| ' in model) == ('_uf' in task), task


# VHDL: generic -> label attribute (GHDL gives a VHDL boolean as 1'1 / 1'0).

VHDL_TB = 'uf_dis_box.vhdl tb_uf_disable_formal.vhdl -e tb_uf_disable_formal'


def vhdl(tmp_path, generics='', files=VHDL_TB, top='tb_uf_disable_formal', post='', unset=False):
    files = ' '.join(f'{HERE / f}' if f.endswith('.vhdl') else f for f in files.split())
    script = (f'ghdl --std=08 {generics} {files}; prep -top {top}; '
              + (f'{post}; ' if post else '')
              + ('setattr -unset uf_instance -unset uf_disable */*; ' if unset else '')
              + 'write_smt2 -bv x.smt2')
    r = run_yosys(script, tmp_path, ghdl=True)
    smt = tmp_path / 'x.smt2'
    return r, (smt.read_text() if r.returncode == 0 and smt.exists() else '')


def test_vhdl_disable_generic_default_uf(tmp_path):
    """VHDL: UF_MODE = true (default) -> u1, u2 are the UF f; u3 with only uf_disable
    warns."""
    r, smt = vhdl(tmp_path)
    assert r.returncode == 0, r.log[-4000:]
    assert len(declares(smt, 'f')) == 1
    no_hier_refs(smt, ['u1', 'u2'])
    assert len(r.uf_warnings) == 1, r.log
    assert 'Attribute uf_disable on cell tb_uf_disable_formal.u3 has no effect' in r.uf_warnings[0]


def test_vhdl_disable_generic_off_identical(tmp_path):
    """VHDL: -gUF_MODE=false -> the model is the same as without the marks."""
    r, smt = vhdl(tmp_path, '-gUF_MODE=false')
    assert r.returncode == 0, r.log[-4000:]
    assert declares(smt, 'f') == []
    sub = tmp_path / 'stripped'
    sub.mkdir()
    r2, smt2 = vhdl(sub, '-gUF_MODE=false', unset=True)
    assert r2.returncode == 0, r2.log[-4000:]
    assert smt == smt2
    # control: the UF model differs
    sub = tmp_path / 'uf'
    sub.mkdir()
    _, smt3 = vhdl(sub)
    assert smt3 != smt


def test_vhdl_disable_blackbox_error(tmp_path):
    """VHDL: an unbound component (blackbox) and -gUF_MODE=false -> error;
    by default the UF b."""
    r, smt = vhdl(tmp_path, '', files='uf_dis_bbox.vhdl -e uf_dis_bbox', top='uf_dis_bbox')
    assert r.returncode == 0, r.log[-4000:]
    assert len(declares(smt, 'b')) == 1
    r, _ = vhdl(tmp_path, '-gUF_MODE=false', files='uf_dis_bbox.vhdl -e uf_dis_bbox', top='uf_dis_bbox')
    assert r.returncode != 0
    assert 'instantiates the blackbox module bb and has uf_disable set' in r.log, r.log[-4000:]

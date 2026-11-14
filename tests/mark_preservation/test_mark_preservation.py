"""mark_preservation: keep / keep_hierarchy keep a uf_instance mark alive in a normal flow.

Every protection has a pair: the unprotected variant SHOWS the loss (otherwise the
protected variant would prove nothing) and the protected variant shows that the
mark survives. Observations, in order of preference:
  1. the proof result (sby status), when the loss changes the semantics,
  2. write_smt2: a declare-fun (the marked cell still exists) or an
     "Ignoring uf_instance" warning (e.g. for the $scopeinfo cell left by flatten),
  3. RTLIL: select -list of the marked cells.

For a hierarchy cell write_smt2 emits a declare-fun; survival is detected from that.
"""
import re
import shutil
from pathlib import Path

import pytest

from conftest import run_yosys

HERE = Path(__file__).resolve().parent

UF_VHDL = ['uf_f.vhdl', 'uf_f_keep.vhdl', 'uf_f_kh.vhdl']


# ---------------------------------------------------------------- helpers

class Y:
    """Result of a yosys run: log, select lists and (optional) SMT2 text."""

    def __init__(self, run, sels, smt):
        self.run = run
        self.sels = sels
        self.smt = smt

    def warned(self, sym):
        return [w for w in self.run.uf_warnings if f'"{sym}"' in w]

    def flat_warned(self, sym):
        return [w for w in self.warned(sym) if 'on flattened instance' in w]

    def declares(self, sym):
        return [l for l in self.smt.splitlines() if l.startswith(f'(declare-fun |{sym}| ')]


def yosys_run(tmp_path, files, script, sels=(), ghdl=False, smt2=True):
    """Run yosys on a tmp copy. sels: select expressions whose -list is returned.

    The returned names are in select -list form 'module/object'.
    """
    work = tmp_path / 'y'
    work.mkdir(parents=True, exist_ok=True)
    for f in files:
        shutil.copy2(HERE / f, work / f)
    lines = [script]
    for i, sel in enumerate(sels):
        lines.append(f'tee -q -o sel{i}.txt select -list {sel}')
    if smt2:
        lines.append('write_smt2 -wires out.smt2')
    r = run_yosys(';\n'.join(lines), work, ghdl=ghdl)
    assert r.returncode == 0, r.log[-4000:]
    out = []
    for i in range(len(sels)):
        txt = (work / f'sel{i}.txt').read_text()
        out.append(sorted(l.strip() for l in txt.splitlines() if l.strip()))
    smt = (work / 'out.smt2').read_text() if smt2 else ''
    return Y(r, out, smt)


def objs(sel_list):
    """'module/object' -> {object}."""
    return {l.split('/', 1)[1] for l in sel_list}


def sby_decls(r, sby_name, task):
    """declare-fun lines of the uf symbols in the SMT2 model of an sby run, {symbol: line}."""
    smt = (r.workdir / f'{sby_name}_{task}' / 'model' / 'design_smt2.smt2').read_text()
    out = {}
    for l in smt.splitlines():
        m = re.match(r'\(declare-fun \|([^|#]+)\| \(\(_ BitVec', l)
        if m:
            out[m.group(1)] = l
    return out


def check_status(r, *allowed):
    """A status other than the allowed ones (e.g. ERROR) is a real failure."""
    if r.status not in allowed:
        raise RuntimeError(f'unexpected status {r.status}:\n{r.log[-3000:]}')


# ---------------------------------------------------------------- 0. GHDL: where keep* ends up

GHDL_FLAT = 'ghdl --std=08 ' + ' '.join(UF_VHDL) + ' h_flat.vhdl -e h_flat'
GHDL_CLEAN = 'ghdl --std=08 ' + ' '.join(UF_VHDL) + ' h_clean.vhdl -e h_clean'
GHDL_MERGE = 'ghdl --std=08 ' + ' '.join(UF_VHDL) + ' h_merge.vhdl -e h_merge'


def test_ghdl_keep_placement(tmp_path):
    """Boolean keep / keep_hierarchy: entity -> module attribute, label -> cell attribute."""
    y = yosys_run(tmp_path, UF_VHDL + ['h_flat.vhdl'], GHDL_FLAT,
                  sels=['A:keep', 'A:keep_hierarchy', 'h_flat/a:keep', 'h_flat/a:keep_hierarchy',
                        'h_flat/a:uf_instance'],
                  ghdl=True, smt2=False)
    # A:<attr> lists the module as well as its contents; modules are the lines without '/'
    mod_keep, mod_kh = ([l for l in sel if '/' not in l] for sel in y.sels[:2])
    cell_keep, cell_kh, marked = y.sels[2:]
    assert mod_keep == ['uf_f_keep_Brtl'], mod_keep
    assert mod_kh == ['uf_f_kh_Brtl'], mod_kh
    assert objs(cell_keep) == {'u_lkeep'}, cell_keep
    assert objs(cell_kh) == {'u_lkh'}, cell_kh
    assert objs(marked) == {'u_none', 'u_lkeep', 'u_ekeep', 'u_lkh', 'u_ekh'}, marked


def test_ghdl_keeps_unused_instances(tmp_path):
    """GHDL does not drop an unused instance (not even one with an open output) before yosys."""
    y = yosys_run(tmp_path, UF_VHDL + ['h_clean.vhdl'], GHDL_CLEAN,
                  sels=['h_clean/c:u_*'], ghdl=True, smt2=False)
    assert objs(y.sels[0]) == {'u_none', 'u_open', 'u_ent', 'u_lbl'}, y.sels[0]


# ---------------------------------------------------------------- 1. opt_clean

@pytest.fixture
def h_clean(tmp_path):
    return yosys_run(tmp_path, UF_VHDL + ['h_clean.vhdl'],
                     GHDL_CLEAN + ';\nprep -top h_clean',
                     sels=['h_clean/c:u_*'], ghdl=True)


def test_clean_hier_unprotected_lost(h_clean):
    """An unprotected unused UF instance is removed silently: no cell, no warning."""
    cells = objs(h_clean.sels[0])
    assert 'u_none' not in cells and 'u_open' not in cells, cells
    assert not h_clean.warned('f_none') and not h_clean.warned('f_open'), h_clean.run.uf_warnings
    assert not h_clean.declares('f_none') and not h_clean.declares('f_open')


def test_clean_hier_keep_entity_survives(h_clean):
    """keep on the entity (module attribute) protects: the cell survives and a declare-fun is emitted."""
    assert 'u_ent' in objs(h_clean.sels[0])
    assert len(h_clean.declares('f_ent')) == 1, h_clean.smt[:2000]
    assert not h_clean.warned('f_ent'), h_clean.run.uf_warnings


def test_clean_hier_keep_label_survives(h_clean):
    """keep on the instance label protects in the same way."""
    assert 'u_lbl' in objs(h_clean.sels[0])
    assert len(h_clean.declares('f_lbl')) == 1, h_clean.smt[:2000]
    assert not h_clean.warned('f_lbl'), h_clean.run.uf_warnings


B_CLEAN_READ = 'read_verilog -sv b_clean.sv'
B_CLEAN_VARIANTS = {
    'none': '',
    'wire_keep': 'setattr -set keep 1 w:p',
}


def _b_clean(tmp_path, variant):
    script = [B_CLEAN_READ]
    if B_CLEAN_VARIANTS[variant]:
        script.append(B_CLEAN_VARIANTS[variant])
    script.append('prep -top b_clean')
    return yosys_run(tmp_path, ['b_clean.sv'], ';\n'.join(script), sels=['a:uf_instance'])


def test_clean_builtin_unprotected_lost(tmp_path):
    """An unused marked $mul is removed (opt_clean): no declare-fun, no warning."""
    y = _b_clean(tmp_path, 'none')
    assert y.sels[0] == []
    assert not y.declares('f') and not y.warned('f')


def test_clean_builtin_wire_keep_survives(tmp_path):
    """keep on the output wire protects against both opt_clean and wreduce: a declare-fun is emitted."""
    y = _b_clean(tmp_path, 'wire_keep')
    assert len(y.sels[0]) == 1, y.sels
    assert len(y.declares('f')) == 1, y.smt[:2000]


# ---------------------------------------------------------------- 2a. opt_merge, f != g

def test_merge2_unprotected_silent_pass(sby):
    """opt_merge does not hash attributes: the f and g cells are merged, pf == pg becomes
    pf == pf and folds to a constant, so the $mul result is left unused and the cell
    is removed (wreduce). Neither symbol reaches the model: the PASS comes from the interpreted logic."""
    r = sby(HERE, 'b_merge2.sby', 'none')
    check_status(r, 'PASS', 'FAIL')
    assert r.status == 'PASS'
    assert sby_decls(r, 'b_merge2', 'none') == {}


def test_merge2_keep_both_fails(sby):
    """keep on both: no merge, f and g are different UFs -> FAIL."""
    r = sby(HERE, 'b_merge2.sby', 'keep')
    check_status(r, 'PASS', 'FAIL')
    assert r.status == 'FAIL'
    assert set(sby_decls(r, 'b_merge2', 'keep')) == {'f', 'g'}


# ---------------------------------------------------------------- 2b. opt_merge, marked + unmarked

def test_merge_one_unprotected_marking_lost(sby):
    """Without keep the marked cell is merged with the unmarked one: PASS, but f is lost."""
    r = sby(HERE, 'b_merge_one.sby', 'none')
    check_status(r, 'PASS', 'FAIL')
    assert r.status == 'PASS'
    assert 'f' not in sby_decls(r, 'b_merge_one', 'none')


def test_merge_one_keep_both(sby):
    """keep on both: the interpreted use stays interpreted and f survives."""
    r = sby(HERE, 'b_merge_one.sby', 'keep_both')
    check_status(r, 'PASS', 'FAIL')
    assert r.status == 'PASS'
    assert 'f' in sby_decls(r, 'b_merge_one', 'keep_both')


# ---------------------------------------------------------------- 2c. opt_merge, hierarchy cells

def test_merge_hier_prep_does_not_merge(tmp_path):
    """The opt_merge in prep does not merge hierarchy cells (no -share_all): all survive."""
    y = yosys_run(tmp_path, UF_VHDL + ['h_merge.vhdl'], GHDL_MERGE + ';\nprep -top h_merge',
                  sels=['h_merge/c:u_*'], ghdl=True)
    assert objs(y.sels[0]) == {'u_n1', 'u_n2', 'u_e1', 'u_e2', 'u_l1', 'u_l2'}


@pytest.fixture
def h_merge_share_all(tmp_path):
    return yosys_run(tmp_path, UF_VHDL + ['h_merge.vhdl'],
                     GHDL_MERGE + ';\nprep -top h_merge;\nopt_merge -share_all',
                     sels=['h_merge/c:u_*'], ghdl=True)


def test_merge_hier_share_all_unprotected_lost(h_merge_share_all):
    """opt_merge -share_all: of the unprotected u_n1/u_n2 one remains, the other symbol is lost silently."""
    y = h_merge_share_all
    cells = objs(y.sels[0])
    assert len(cells & {'u_n1', 'u_n2'}) == 1, cells
    assert len(y.declares('f_n1')) + len(y.declares('f_n2')) == 1, y.smt[:2000]
    assert not y.warned('f_n1') and not y.warned('f_n2'), y.run.uf_warnings


@pytest.mark.parametrize('pair', [('u_e1', 'u_e2'), ('u_l1', 'u_l2')], ids=['entity', 'label'])
def test_merge_hier_share_all_keep_survives(h_merge_share_all, pair):
    """keep on the entity or on both labels: both instances and declarations survive."""
    y = h_merge_share_all
    assert set(pair) <= objs(y.sels[0]), y.sels[0]
    for c in pair:
        assert len(y.declares('f_' + c[2:])) == 1, y.smt[:2000]
        assert not y.warned('f_' + c[2:]), y.run.uf_warnings


# ---------------------------------------------------------------- 3. flatten

FLAT_FLOWS = {
    'prep_flatten': 'prep -flatten -top h_flat',
    'prep_then_flatten': 'prep -top h_flat;\nflatten',
}


def _h_flat(tmp_path, flow):
    return yosys_run(tmp_path, UF_VHDL + ['h_flat.vhdl'], GHDL_FLAT + ';\n' + flow,
                     sels=['h_flat/c:u_* h_flat/t:$scopeinfo %d',
                           'h_flat/t:$scopeinfo a:cell_uf_instance %i'],
                     ghdl=True)


def _hier_cells(y):
    # inner cells of a flattened instance look like u_x.:13; a hierarchy cell name has no dot
    return {c for c in objs(y.sels[0]) if '.' not in c}


FLAT_SYMS = ['f_none', 'f_lkeep', 'f_ekeep', 'f_lkh', 'f_ekh']
UF_F_DECL = '((_ BitVec 8) (_ BitVec 8)) (_ BitVec 8))'


def test_flat_baseline_no_flatten(tmp_path):
    """Without flatten all five hierarchy cells survive and each one yields a declare-fun."""
    y = _h_flat(tmp_path, 'prep -top h_flat')
    assert _hier_cells(y) == {'u_none', 'u_lkeep', 'u_ekeep', 'u_lkh', 'u_ekh'}
    assert y.run.uf_warnings == [], y.run.uf_warnings
    for sym in FLAT_SYMS:
        d = y.declares(sym)
        assert len(d) == 1 and d[0].startswith(f'(declare-fun |{sym}| {UF_F_DECL}'), (sym, d)


@pytest.mark.parametrize('flow', FLAT_FLOWS)
def test_flat_unprotected_lost(tmp_path, flow):
    """flatten dissolves an unprotected cell: the attribute is left only on the $scopeinfo
    cell, as cell_uf_instance. write_smt2 warns about it, and no declare-fun is emitted."""
    y = _h_flat(tmp_path, FLAT_FLOWS[flow])
    inst, sym = 'u_none', 'f_none'
    assert inst not in _hier_cells(y), y.sels[0]
    assert inst in objs(y.sels[1]), y.sels[1]
    assert len(y.flat_warned(sym)) == 1, y.run.uf_warnings
    assert len(y.warned(sym)) == 1, y.run.uf_warnings
    assert not y.declares(sym)


@pytest.mark.parametrize('flow', FLAT_FLOWS)
@pytest.mark.parametrize('inst', ['u_lkh', 'u_ekh'])
def test_flat_keep_hierarchy_survives(tmp_path, flow, inst):
    """keep_hierarchy (label or entity) keeps the cell: a declare-fun is emitted, no warning."""
    y = _h_flat(tmp_path, FLAT_FLOWS[flow])
    sym = 'f_' + inst[2:]
    assert inst in _hier_cells(y), y.sels[0]
    assert len(y.declares(sym)) == 1, y.smt[:2000]
    assert not y.warned(sym), y.run.uf_warnings


# ---------------------------------------------------------------- 4. wreduce: UF signature width

def test_wreduce_control_full_fails(sby):
    """Control: the whole 16-bit result is used -> f is 16 bits wide and the assertion FAILs."""
    r = sby(HERE, 'b_wreduce.sby', 'full')
    check_status(r, 'PASS', 'FAIL')
    assert r.status == 'FAIL'
    assert '(_ BitVec 16) (_ BitVec 16)) (_ BitVec 16))' in sby_decls(r, 'b_wreduce', 'full')['f']


def test_wreduce_unprotected_narrowed(sby):
    """Only the low byte is used: wreduce narrows Y to 8 bits, f is declared 8 bits wide
    (inputs truncated) and the assertion passes."""
    r = sby(HERE, 'b_wreduce.sby', 'low')
    check_status(r, 'PASS', 'FAIL')
    assert r.status == 'PASS'
    assert '(_ BitVec 8) (_ BitVec 8)) (_ BitVec 8))' in sby_decls(r, 'b_wreduce', 'low')['f']


def test_wreduce_wire_keep_protects(sby):
    """keep on the output wires p, q: wreduce does not narrow (keep_bits), f stays 16 bits wide -> FAIL."""
    r = sby(HERE, 'b_wreduce.sby', 'low_wkeep')
    check_status(r, 'PASS', 'FAIL')
    assert r.status == 'FAIL'
    assert '(_ BitVec 16) (_ BitVec 16)) (_ BitVec 16))' in sby_decls(r, 'b_wreduce', 'low_wkeep')['f']

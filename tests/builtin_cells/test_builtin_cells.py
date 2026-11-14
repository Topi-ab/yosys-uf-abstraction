"""write_smt2 uf_instance emission for built-in cells (Verilog sources).

- comm.sby: nouf PASS, uf FAIL -> the UF is truly uninterpreted
  (m8(a, 1) == a does not follow from anything).
- conflict.sv: same symbol for different widths -> error.
- warn.sv: unsupported cell types -> one warning each; the marked
  hierarchical cell u_sub is a real UF (hierarchical cell cases: tests/hierarchical_cells).
- invalid symbol value -> error.
- disable.sv, comm.sby task uf_off: uf_disable switches a uf_instance mark off.
"""
import re
import subprocess
from pathlib import Path

import pytest

from conftest import run_yosys

HERE = Path(__file__).resolve().parent


@pytest.mark.parametrize('task,expected', [('nouf', 'PASS'), ('uf', 'FAIL')])
def test_comm(sby, task, expected):
    r = sby(HERE, 'comm.sby', task)
    assert r.status == expected, r.log[-3000:]


def test_conflicting_signature(tmp_path):
    r = run_yosys(f'read_verilog {HERE}/conflict.sv; setattr -set uf_instance "sq" t:$mul; '
                  'prep -top conflict; write_smt2 -bv x.smt2', tmp_path)
    assert r.returncode != 0
    assert 'Conflicting signatures' in r.log, r.log
    assert '"sq"' in r.log


def test_distinct_symbols_no_conflict(tmp_path):
    """Control case: distinct symbols for different widths are accepted."""
    r = run_yosys(f'read_verilog {HERE}/conflict.sv; prep -top conflict; '
                  'setattr -set uf_instance "sq8" w:y %ci1 t:$mul %i; '
                  'setattr -set uf_instance "sq16" w:z %ci1 t:$mul %i; '
                  'write_smt2 -bv x.smt2', tmp_path)
    assert r.returncode == 0, r.log
    smt = (tmp_path / 'x.smt2').read_text()
    assert smt.count('declare-fun |sq8| ((_ BitVec 8) (_ BitVec 8)) (_ BitVec 8)') == 1
    assert smt.count('declare-fun |sq16| ((_ BitVec 16) (_ BitVec 16)) (_ BitVec 16)') == 1


@pytest.fixture(scope='module')
def warn_run(tmp_path_factory):
    work = tmp_path_factory.mktemp('warn')
    r = run_yosys(f'read_verilog {HERE}/warn.sv; prep -top warn; '
                  'setattr -set uf_instance "f" t:$lt t:$mux t:$reduce_or t:$shl warn/u_sub; '
                  'write_smt2 -bv x.smt2', work)
    assert r.returncode == 0, r.log
    return r, (work / 'x.smt2').read_text()


@pytest.mark.parametrize('ctype', ['$lt', '$mux', '$shl', '$reduce_or'])
def test_warning_unsupported_type(warn_run, ctype):
    r, _ = warn_run
    hits = [w for w in r.uf_warnings if f'cell type {ctype} ' in w]
    assert len(hits) == 1, r.uf_warnings


def test_warning_total_and_hier_declare(warn_run):
    """The four unsupported cells warn; hierarchical cell u_sub (a[7:0] -> y[7:0])
    is the only user of f, so f is declared once with its signature."""
    r, smt = warn_run
    assert len(r.uf_warnings) == 4, r.uf_warnings
    decls = [l for l in smt.splitlines() if l.startswith('(declare-fun |f| ')]
    assert len(decls) == 1, decls
    assert decls[0].startswith('(declare-fun |f| ((_ BitVec 8)) (_ BitVec 8))'), decls


@pytest.mark.parametrize('value', ['"a|b"', '"a;b"', '5'])
def test_invalid_symbol(tmp_path, value):
    r = run_yosys(f'read_verilog {HERE}/conflict.sv; setattr -set uf_instance {value} t:$mul; '
                  'prep -top conflict; write_smt2 -bv x.smt2', tmp_path)
    assert r.returncode != 0
    assert re.search(r'ERROR: Attribute uf_instance on cell .* (has value|must be a string)', r.log), r.log


def test_help_documents_uf_instance():
    p = subprocess.run(['yosys', '-h', 'write_smt2'], stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, text=True, timeout=60)
    assert p.returncode == 0
    assert 'uf_instance' in p.stdout
    assert '(declare-fun |<name>|' in p.stdout
    for t in ('$add', '$sub', '$mul', '$neg', '$div', '$mod', '$divfloor', '$modfloor'):
        assert t in p.stdout
    # Hierarchical cell paragraph: return value, signature and box requirements.
    text = ' '.join(p.stdout.split())
    for kw in ('concatenation', 'port order', 'stateless'):
        assert kw in text, kw


# ---------------------------------------------------------------- uf_disable

def dis(tmp_path, mode=None, post=''):
    chp = f' -chparam UF_MODE {mode}' if mode is not None else ''
    r = run_yosys(f'read_verilog -sv {HERE}/disable.sv; hierarchy -top dis_top{chp}; '
                  f'prep -top dis_top; {post}{"; " if post else ""}write_smt2 -bv x.smt2', tmp_path)
    assert r.returncode == 0, r.log
    return r, (tmp_path / 'x.smt2').read_text()


def test_disable_builtin_param(tmp_path):
    """(* uf_instance = "g", uf_disable = !UF_MODE *) on an operator: by default
    g and h are UFs, UF_MODE = 0 -> only h; the model equals the one without g's mark."""
    r, smt = dis(tmp_path)
    assert r.uf_warnings == [], r.log
    assert smt.count('(declare-fun |g| ') == 1 and smt.count('(declare-fun |h| ') == 1
    sub = tmp_path / 'off'
    sub.mkdir()
    r, off = dis(sub, 0)
    assert r.uf_warnings == [], r.log
    assert '(declare-fun |g| ' not in off and off.count('(declare-fun |h| ') == 1
    assert 'bvadd' in off
    sub = tmp_path / 'strip'
    sub.mkdir()
    _, strip = dis(sub, 0, post='setattr -unset uf_instance -unset uf_disable t:$add')
    assert off == strip


def test_comm_uf_off(sby):
    """The uf_off task of comm.sby (uf_instance + uf_disable = 1) is interpreted:
    PASS, and the model has no m8."""
    r = sby(HERE, 'comm.sby', 'uf_off')
    assert r.status == 'PASS', r.log[-3000:]
    assert '|m8|' not in (r.workdir / 'comm_uf_off' / 'model' / 'design_smt2.smt2').read_text()


def test_disable_unsupported_type_no_warning(tmp_path):
    """A switched-off mark on an unsupported cell type does not warn ("Ignoring")."""
    r = run_yosys(f'read_verilog {HERE}/warn.sv; prep -top warn; '
                  'setattr -set uf_instance "f" -set uf_disable 1 t:$lt t:$mux; '
                  'write_smt2 -bv x.smt2', tmp_path)
    assert r.returncode == 0, r.log
    assert r.uf_warnings == [], r.uf_warnings


@pytest.mark.parametrize('sym,ok', [('a#b', False), ('ok_sym', True)])
def test_disable_unexported_cell_symbol_checked(tmp_path, sym, ok):
    """An unused (no exported output) switched-off cell: the symbol is still
    validated, but no "Ignoring" warning is given."""
    r = run_yosys(f'read_verilog {HERE}/warn.sv; hierarchy -top warn; proc; '
                  f'setattr -set uf_instance "{sym}" -set uf_disable 1 t:$sub; '
                  'select -assert-count 1 t:$sub; write_smt2 -bv x.smt2', tmp_path)
    if ok:
        assert r.returncode == 0, r.log
        assert r.uf_warnings == [], r.uf_warnings
    else:
        assert r.returncode != 0
        assert f'Attribute uf_instance on cell warn.' in r.log and f'has value "{sym}"' in r.log, r.log


@pytest.mark.parametrize('value', ['"no"', "1'bx"])
def test_disable_builtin_invalid_value(tmp_path, value):
    r = run_yosys(f'read_verilog {HERE}/conflict.sv; prep -top conflict; '
                  f'setattr -set uf_instance "sq" -set uf_disable {value} t:$mul; write_smt2 -bv x.smt2',
                  tmp_path)
    assert r.returncode != 0
    assert re.search(r'ERROR: Attribute uf_disable on cell conflict\.\S+ has value .*which is not a boolean',
                     r.log), r.log


def test_help_documents_uf_disable():
    p = subprocess.run(['yosys', '-h', 'write_smt2'], stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, text=True, timeout=60)
    assert p.returncode == 0
    text = ' '.join(p.stdout.split())
    for kw in ("'uf_disable'", 'attribute uf_disable of u_sum : label is not UF_MODE',
               'uf_disable = !UF_MODE', 'has no concrete export', 'has no effect'):
        assert kw in text, kw

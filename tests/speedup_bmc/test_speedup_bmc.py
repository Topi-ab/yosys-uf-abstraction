"""speedup_bmc: speed gain of abstracting the DUT multiplication as a UF (speedup.sby).

Same two-channel structure as vhdl_control_independence_setattr, but the data
width is the generic WIDTH and the BMC depth is chosen per run (environment
variables SPEEDUP_WIDTH and SPEEDUP_DEPTH, read in the pycode blocks of
speedup.sby).

- uf:   the testbench stim_f/out_f and the DUT $mul (mulw) are UFs.
- nouf: the testbench stim_f/out_f are UFs, the DUT multiplication is interpreted
        (the "traditional" model with symbolic data).

The points (WIDTH, DEPTH) were picked from a measurement grid (grid.sh) so
that with bitwuzla nouf/uf is about 7-12x and the uf run takes >= ~2 s.
Measured solver times (s, three repetitions, nouf/uf):

    WIDTH DEPTH   uf               nouf                ratio
    11    20      1.72 1.89 1.69   17.49 17.60 18.50    9.3-10.9x
    11    24      4.48 3.35 3.51   38.48 36.01 38.64    8.6-11.0x
    11    28      7.91 7.29 8.14   66.54 67.00 63.75    7.8-9.2x
    12    28      9.43 7.72 10.25  96.45 98.04 100.24   9.8-12.7x

Over the whole grid: at WIDTH <= 7 the UF does not help (ratio ~1x; the
Ackermann constraints of the UF cost as much as a small multiplier), at
WIDTH 8-10 it gives 2-5x, at 11-12 7-20x and at >= 13 more than 18-20x; a
16-bit multiplication is over 20x slower already at depth 10.

The exact ratio is not required (it depends on the machine and its load); the
times are recorded as junit properties and printed. The nouf runs are @slow
(minutes in total):
  ./tc.sh pytest tests/speedup_bmc                  # uf + vacuity + structure
  ./tc.sh pytest -m slow tests/speedup_bmc          # nouf + loose ratio check (>= 3x)
"""
import os
import subprocess
import time
from pathlib import Path

import pytest

from conftest import COVER_BOTH, cover_steps, run_sby, sby_model, smt2_module_sections, uf_decls

HERE = Path(__file__).resolve().parent

# (WIDTH, DEPTH): measured with bitwuzla, see the module docstring.
POINTS = [(11, 20), (11, 24), (11, 28), (12, 28)]
POINT_IDS = [f'w{w}_d{d}' for w, d in POINTS]

# Loose lower bound for the nouf/uf ratio (measured 6.5-12x wall clock).
MIN_RATIO = 3.0


def _run(tmp_path, monkeypatch, task, width, depth):
    """Run the speedup.sby task with the given width and depth; returns
    (SbyResult, wall-clock time in s)."""
    monkeypatch.setenv('SPEEDUP_WIDTH', str(width))
    monkeypatch.setenv('SPEEDUP_DEPTH', str(depth))
    t0 = time.monotonic()
    r = run_sby(HERE, 'speedup.sby', task, tmp_path / task, timeout=1800)
    return r, time.monotonic() - t0


def _record(record_property, task, width, depth, secs):
    record_property(f'{task}_w{width}_d{depth}_s', f'{secs:.2f}')
    print(f'{task} WIDTH={width} DEPTH={depth}: {secs:.2f} s')


def _check_uf_model(r, width):
    smt = sby_model(r, 'speedup_uf')
    decls = uf_decls(smt)
    assert {k: len(v) for k, v in decls.items()} == {'mulw': 1, 'stim_f': 1, 'out_f': 1}, decls
    assert f'(declare-fun |mulw| ((_ BitVec {width}) (_ BitVec {width})) (_ BitVec {width}))' \
        in decls['mulw'][0], decls['mulw']
    dsp = [s for m, s in smt2_module_sections(smt).items() if m.startswith('dsp')]
    assert len(dsp) == 1, list(smt2_module_sections(smt))
    assert 'bvmul' not in dsp[0] and '|mulw|' in dsp[0]


def _check_nouf_model(r):
    smt = sby_model(r, 'speedup_nouf')
    decls = uf_decls(smt)
    assert {k: len(v) for k, v in decls.items()} == {'stim_f': 1, 'out_f': 1}, decls
    dsp = [s for m, s in smt2_module_sections(smt).items() if m.startswith('dsp')]
    assert len(dsp) == 1 and 'bvmul' in dsp[0]


# ---------------------------------------------------------------- structure

def _dumpcfg(task, width, depth):
    env = {'SPEEDUP_WIDTH': str(width), 'SPEEDUP_DEPTH': str(depth)}
    p = subprocess.run(['sby', '--dumpcfg', 'speedup.sby', task], cwd=HERE, text=True,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60,
                       env={**os.environ, **env})
    assert p.returncode == 0, p.stdout
    return p.stdout.splitlines()


@pytest.mark.parametrize('task', ['uf', 'nouf', 'cover_uf', 'cover_nouf'])
def test_sby_parameters(task):
    """Width and depth are taken from the environment variables; only the uf
    tasks mark the DUT multiplication."""
    cfg = _dumpcfg(task, 11, 24)
    assert 'depth 24' in cfg
    assert any(l.startswith('ghdl ') and ' -gWIDTH=11 ' in l for l in cfg), cfg
    setattr_line = 'setattr -set uf_instance "mulw" dsp*/t:$mul'
    assert (setattr_line in cfg) == (task in ('uf', 'cover_uf')), cfg
    assert ('mode cover' in cfg) == task.startswith('cover')


def test_cover_matches_conftest():
    """The vacuity cover of the testbench is the same condition as conftest.COVER_BOTH."""
    cond = COVER_BOTH.split('cover ', 1)[1].strip().rstrip(';')
    assert cond in (HERE / 'tb_dsp_formal.vhdl').read_text()


# ---------------------------------------------------------------- uf / nouf

@pytest.mark.parametrize('width,depth', POINTS, ids=POINT_IDS)
def test_uf(tmp_path, monkeypatch, record_property, width, depth):
    """uf: PASS, the DUT multiplication is uninterpreted (declare-fun |mulw|)."""
    r, secs = _run(tmp_path, monkeypatch, 'uf', width, depth)
    _record(record_property, 'uf', width, depth, secs)
    assert r.status == 'PASS', r.log[-3000:]
    assert r.uf_warnings == [], r.uf_warnings
    _check_uf_model(r, width)


@pytest.mark.slow
@pytest.mark.parametrize('width,depth', POINTS, ids=POINT_IDS)
def test_nouf(tmp_path, monkeypatch, record_property, width, depth):
    """nouf: PASS with an interpreted multiplication (bvmul, no mulw UF)."""
    r, secs = _run(tmp_path, monkeypatch, 'nouf', width, depth)
    _record(record_property, 'nouf', width, depth, secs)
    assert r.status == 'PASS', r.log[-3000:]
    _check_nouf_model(r)


@pytest.mark.parametrize('task', ['cover_uf', 'cover_nouf'])
@pytest.mark.parametrize('width,depth', POINTS, ids=POINT_IDS)
def test_vacuity_cover(tmp_path, monkeypatch, task, width, depth):
    """Both channels produce checked beats with the model and depth of the task
    (the cover is reached quickly, so the cover of the nouf model is also part
    of the default run)."""
    r, _ = _run(tmp_path, monkeypatch, task, width, depth)
    assert r.status == 'PASS', r.log[-3000:]
    assert 'Reached cover statement' in r.log, r.log[-3000:]
    assert 'Unreached cover' not in r.log, r.log[-3000:]
    assert cover_steps(r.log)[0] + 2 <= depth, cover_steps(r.log)
    smt = sby_model(r, f'speedup_{task}')
    expect = {'stim_f', 'out_f'} | ({'mulw'} if task == 'cover_uf' else set())
    assert set(uf_decls(smt)) == expect, uf_decls(smt)


@pytest.mark.slow
@pytest.mark.parametrize('width,depth', POINTS, ids=POINT_IDS)
def test_speedup_ratio(tmp_path, monkeypatch, record_property, width, depth):
    """Loose sanity check: nouf / uf >= MIN_RATIO at the same point.
    The measured ratios are in the module docstring; they depend on the machine
    and its load."""
    ru, tu = _run(tmp_path, monkeypatch, 'uf', width, depth)
    assert ru.status == 'PASS', ru.log[-3000:]
    rc, tc = _run(tmp_path, monkeypatch, 'nouf', width, depth)
    assert rc.status == 'PASS', rc.log[-3000:]
    ratio = tc / tu
    _record(record_property, 'uf', width, depth, tu)
    _record(record_property, 'nouf', width, depth, tc)
    record_property(f'ratio_w{width}_d{depth}', f'{ratio:.2f}')
    print(f'nouf/uf WIDTH={width} DEPTH={depth}: {ratio:.2f}x')
    assert ratio >= MIN_RATIO, (tu, tc, ratio)

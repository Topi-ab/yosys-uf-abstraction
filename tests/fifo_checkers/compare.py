#!/usr/bin/env python3
"""UF checker vs. scoreboard: BMC time comparison over a (DEPTH, WIDTH) grid.

Run (from the repository root, in Docker):
    ./tc.sh python3 tests/fifo_checkers/compare.py
    ./tc.sh python3 tests/fifo_checkers/compare.py --depths 2 4 8 --widths 8 32 110

At each point the uf and sb tasks run in parallel (same BMC depth
2*DEPTH+6, same sby script, only the generics change). 2x rule: when the
faster one finishes in time T, the slower one is waited for at most until 2T
and then killed -> '>2T s (killed)'; a 2x difference is enough to decide the
comparison. In addition, each has a cap of --cap seconds (both are killed if
neither finishes).

Budget: --budget seconds for the whole run; when the budget would be
exceeded, the remaining points are skipped (reported as 'skipped' in the
table).
"""
import argparse
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SBY = 'axis_fifo.sby'
DEFAULT_PARAMS = 'D, W = 4, 8\n'
DONE_RE = re.compile(r'DONE \((PASS|FAIL|ERROR|UNKNOWN|TIMEOUT)')
CHECKERS = ('uf', 'sb')


def bmc_depth(depth):
    return 2 * depth + 6


def make_copy(dst, depth, width):
    """Copy the source files (no subdirectories) and set the parameters (pycode
    line; the generics and the BMC depth 2*DEPTH+6 are derived from it in the
    sby file)."""
    dst.mkdir(parents=True)
    for p in HERE.iterdir():
        if p.is_file() and p.suffix in ('.vhdl', '.sby', '.psl'):
            shutil.copy(p, dst / p.name)
    sby = dst / SBY
    t = sby.read_text()
    assert t.count(DEFAULT_PARAMS) == 2
    t = t.replace(DEFAULT_PARAMS, f'D, W = {depth}, {width}\n')
    sby.write_text(t)


def kill(p):
    try:
        os.killpg(p.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    p.wait()


def run_point(work, depth, width, cap):
    """Run uf and sb in parallel; return {checker: (time, status)}."""
    # A separate copy for each: two parallel sby processes in the same
    # directory would race for the shared output directory (ERROR).
    for c in CHECKERS:
        make_copy(work / c, depth, width)
    procs, logs, t0 = {}, {}, time.monotonic()
    for c in CHECKERS:
        logs[c] = open(work / f'{c}.log', 'w')
        procs[c] = subprocess.Popen(['sby', '-f', SBY, c], cwd=work / c, stdout=logs[c],
                                    stderr=subprocess.STDOUT, start_new_session=True)
    res = {}
    deadline = t0 + cap
    while len(res) < len(CHECKERS):
        now = time.monotonic()
        for c, p in procs.items():
            if c not in res and p.poll() is not None:
                logs[c].close()
                done = DONE_RE.findall((work / f'{c}.log').read_text())
                res[c] = (now - t0, done[-1] if done else 'ERROR')
                # 2x rule: the other one is waited for at most twice this
                # time (only if the faster one really finished with PASS)
                if res[c][1] == 'PASS':
                    deadline = min(deadline, t0 + 2 * (now - t0))
        if len(res) < len(CHECKERS) and now >= deadline:
            for c, p in procs.items():
                if c not in res:
                    kill(p)
                    logs[c].close()
                    res[c] = (now - t0, 'KILLED')
        time.sleep(0.05)
    return res


def fmt(t, status):
    if status == 'KILLED':
        return f'>{t:.1f} s (killed)'
    if status != 'PASS':
        return f'{t:.1f} s ({status})'
    return f'{t:.2f} s'


def ratio(r):
    (tu, su), (ts, ss) = r['uf'], r['sb']
    if su == 'PASS' and ss == 'PASS':
        return f'{tu / ts:.2f}'
    if su == 'KILLED' and ss == 'PASS':
        return f'>{tu / ts:.2f}'
    if ss == 'KILLED' and su == 'PASS':
        return f'<{tu / ts:.2f}'
    return '-'


def verdict(r):
    (tu, su), (ts, ss) = r['uf'], r['sb']
    if su != 'PASS' and ss != 'PASS':
        return 'neither finished'
    # A killed run counts as >= 2x only if it ran for 2x the other's time
    # (otherwise it was killed by the --cap limit and the ratio stays open).
    if ss == 'KILLED':
        return 'UF >= 2x faster' if ts >= 2 * tu - 0.1 else 'UF faster, 2x not decided (cap)'
    if su == 'KILLED':
        return 'SB >= 2x faster' if tu >= 2 * ts - 0.1 else 'SB faster, 2x not decided (cap)'
    if su != 'PASS' or ss != 'PASS':
        return '-'
    if ts >= 2 * tu:
        return 'UF >= 2x faster'
    if tu >= 2 * ts:
        return 'SB >= 2x faster'
    return 'difference < 2x'


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--depths', type=int, nargs='+', default=[2, 4, 8, 16])
    ap.add_argument('--widths', type=int, nargs='+', default=[8, 32, 110])
    ap.add_argument('--cap', type=float, default=600.0,
                    help='maximum time of one checker at a point (s)')
    ap.add_argument('--budget', type=float, default=1200.0,
                    help='time budget of the whole run (s)')
    ap.add_argument('--keep', action='store_true', help='keep the work directory')
    a = ap.parse_args()

    root = Path(tempfile.mkdtemp(prefix='axis_fifo_compare_'))
    start = time.monotonic()
    rows = []
    hdr = '| DEPTH | WIDTH | BMC depth | UF | SB | UF/SB | 2x rule |'
    print(hdr)
    print('|---|---|---|---|---|---|---|')
    sys.stdout.flush()
    for d in sorted(a.depths):
        for w in sorted(a.widths):
            left = a.budget - (time.monotonic() - start)
            if left <= 5:
                line = f'| {d} | {w} | {bmc_depth(d)} | skipped | skipped | - | budget exhausted |'
            else:
                r = run_point(root / f'D{d}-W{w}', d, w, min(a.cap, left))
                line = (f'| {d} | {w} | {bmc_depth(d)} | {fmt(*r["uf"])} | '
                        f'{fmt(*r["sb"])} | {ratio(r)} | {verdict(r)} |')
            rows.append(line)
            print(line)
            sys.stdout.flush()
    print(f'\nTotal time {time.monotonic() - start:.1f} s')
    if a.keep:
        print(f'Work directory: {root}')
    else:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == '__main__':
    main()

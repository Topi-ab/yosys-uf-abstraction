#!/usr/bin/env python3
"""Wolper vs. UF vs. scoreboard: BMC time comparison over a (DEPTH, WIDTH) grid.

Run (from the repository root, in Docker):
    ./tc.sh python3 tests/fifo_wolper/compare.py --out wolper_grid
    ./tc.sh python3 tests/fifo_wolper/compare.py --depths 2 4 --widths 8 --points 2

At each point the wolper, uf and sb tasks run in parallel (same BMC depth
2*DEPTH+6, same sby script axis_fifo_wolper.sby, only the parameters
change). 2x rule for three: when the fastest finishes with PASS in time T,
the others are waited for at most until 2T and then killed ->
'>2T s (killed)'; a 2x difference is enough to decide the comparison. In
addition, a cap of --cap seconds.

--prove: also prove_wolper (k-induction) at every point as a separate run
(not part of the 2x race; cap --cap). --prove-only: only prove_wolper.

--points points run in parallel (3 solvers each), so the times are
parallel-run times. Results: <out>/results.jsonl (one line per checker per
point) and <out>/table.md; <out>/ALLDONE when finished.
"""
import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
SBY = 'axis_fifo_wolper.sby'
PARAM_LINE = 'D, W = 4, 8'
DONE_RE = re.compile(r'DONE \((PASS|FAIL|ERROR|UNKNOWN|TIMEOUT)')
CHECKERS = ('wolper', 'uf', 'sb')
LOCK = threading.Lock()


def bmc_depth(depth):
    return 2 * depth + 6


def make_copy(dst, depth, width):
    """Copy the source files (no subdirectories) and set the parameters."""
    dst.mkdir(parents=True)
    for p in HERE.iterdir():
        if p.is_file() and p.suffix in ('.vhdl', '.sby', '.psl'):
            shutil.copy(p, dst / p.name)
    sby = dst / SBY
    t = sby.read_text()
    assert t.count(PARAM_LINE) == 2, t.count(PARAM_LINE)
    sby.write_text(t.replace(PARAM_LINE, f'D, W = {depth}, {width}'))


def kill(p):
    try:
        os.killpg(p.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    p.wait()


def run_tasks(work, tasks, cap, race):
    """Run the tasks in parallel; return {task: (time, status)}.

    race: 2x rule (fastest PASS in time T -> the others are killed at 2T).
    """
    procs, logs, t0 = {}, {}, time.monotonic()
    for c in tasks:
        logs[c] = open(work / c / f'{c}.log', 'w')
        procs[c] = subprocess.Popen(['sby', '-f', SBY, c], cwd=work / c, stdout=logs[c],
                                    stderr=subprocess.STDOUT, start_new_session=True)
    res = {}
    deadline = t0 + cap
    while len(res) < len(tasks):
        now = time.monotonic()
        for c, p in procs.items():
            if c not in res and p.poll() is not None:
                logs[c].close()
                done = DONE_RE.findall((work / c / f'{c}.log').read_text())
                res[c] = (now - t0, done[-1] if done else 'ERROR')
                if race and res[c][1] == 'PASS':
                    deadline = min(deadline, t0 + 2 * (now - t0))
        if len(res) < len(tasks) and now >= deadline:
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


def verdict(r):
    """The fastest one and its lead in terms of the 2x rule."""
    ok = {c: t for c, (t, s) in r.items() if s == 'PASS'}
    if not ok:
        return 'none finished'
    best = min(ok, key=ok.get)
    tb = ok[best]
    beaten = [c for c, (t, s) in r.items() if c != best and
              ((s == 'PASS' and t >= 2 * tb) or (s == 'KILLED' and t >= 2 * tb - 0.1))]
    close = [c for c in r if c != best and c not in beaten]
    if close:
        return f'{best} fastest; < 2x: ' + ', '.join(close)
    return f'{best} >= 2x faster than the others'


def point(out, d, w, cap, prove, results, prove_only=False):
    work = out / f'D{d}-W{w}'
    if work.exists():
        shutil.rmtree(work)
    for c in (() if prove_only else CHECKERS) + (('prove_wolper',) if prove else ()):
        make_copy(work / c, d, w)
    r = {} if prove_only else run_tasks(work, CHECKERS, cap, race=True)
    if prove:
        r.update(run_tasks(work, ('prove_wolper',), cap, race=False))
    with LOCK:
        with open(out / 'results.jsonl', 'a') as f:
            for c, (t, s) in r.items():
                f.write(json.dumps(dict(depth=d, width=w, task=c, time=round(t, 2),
                                        status=s)) + '\n')
        if prove_only:
            line = f'| {d} | {w} | {fmt(*r["prove_wolper"])} |'
        else:
            line = (f'| {d} | {w} | {bmc_depth(d)} | '
                    + ' | '.join(fmt(*r[c]) for c in CHECKERS)
                    + f' | {verdict({c: r[c] for c in CHECKERS})} |'
                    + (f' {fmt(*r["prove_wolper"])} |' if prove else ''))
        results[(d, w)] = line
        print(line, flush=True)
    shutil.rmtree(work, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--depths', type=int, nargs='+', default=[2, 3, 4, 6, 8, 12, 16])
    ap.add_argument('--widths', type=int, nargs='+', default=[8, 32, 110])
    ap.add_argument('--cap', type=float, default=1800.0,
                    help='maximum time of one task at a point (s)')
    ap.add_argument('--points', type=int, default=6, help='points run in parallel')
    ap.add_argument('--prove', action='store_true', help='also run prove_wolper')
    ap.add_argument('--prove-only', action='store_true', help='run only prove_wolper')
    ap.add_argument('--out', type=Path, default=Path('wolper_grid'))
    a = ap.parse_args()
    a.prove = a.prove or a.prove_only
    out = a.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out / 'ALLDONE').unlink(missing_ok=True)
    start = time.monotonic()
    pts = [(d, w) for d in sorted(a.depths) for w in sorted(a.widths)]
    # Deepest first, so that the long runs start right away.
    pts.sort(key=lambda p: (-p[0], -p[1]))
    results = {}
    with ThreadPoolExecutor(a.points) as ex:
        list(ex.map(lambda p: point(out, p[0], p[1], a.cap, a.prove, results,
                                    a.prove_only), pts))
    if a.prove_only:
        hdr, sep = '| DEPTH | WIDTH | prove (Wolper) |', '|---|---|---|'
    else:
        hdr = ('| DEPTH | WIDTH | BMC depth | Wolper | UF | SB | 2x rule |'
               + (' prove (Wolper) |' if a.prove else ''))
        sep = '|---|---|---|---|---|---|---|' + ('---|' if a.prove else '')
    table = '\n'.join([hdr, sep] + [results[p] for p in sorted(results)])
    (out / 'table.md').write_text(table + f'\n\nTotal time {time.monotonic() - start:.1f} s\n')
    print(table)
    (out / 'ALLDONE').write_text('ok\n')


if __name__ == '__main__':
    sys.exit(main())

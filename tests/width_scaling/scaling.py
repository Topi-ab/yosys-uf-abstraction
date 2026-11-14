"""Driver of the UF width experiment: generates an sby file for one point and runs it.

Point = (mode, WI, WO, depth, solver, bad). Mode 'uf' keeps the box instances
as uninterpreted functions (UF_MODE=1), 'nouf' switches their marks off
(UF_MODE=0, width.sv: uf_disable = !UF_MODE; interpreted multiplication).

Usage (inside ./tc.sh), grid in parallel:
    python3 scaling.py grid <grid> <result.csv> [--jobs J] [--timeout S]
Grids: see grid(). Result: CSV (name, mode, wi, wo, depth, solver, bad,
status, seconds).

Measured (bitwuzla, wall clock of the whole sby run, s; 61 points in
parallel on a loaded machine with a 300 s limit, so absolute times are
pessimistic; where that run hit the limit, a rerun with 15 points in parallel
and a 900 s limit is shown):

    argument width WI (WO = 10)        return width WO (WI = 10)
    WI    d10   d20     d40            WO    d10   d20     d40
    4     0.7   7.9     160            4     0.6   4.6     115
    10    0.7   8.1     173            10    0.7   8.1     173
    32    0.8   10.5    257            32    1.0   20.2    346
    64    1.0   24.7    >300           64    1.6   43.3    >300
    110   1.1   41.0    >300           110   2.3   89.7    >300
    256   2.0   120.7   >300           256   5.3   285     >300

    interpreted multiplication (WI = WO = W)
    W     d10    d20    d40
    4     0.5    1.3    24.4
    10    1.7    23.8   257
    32    >900   >300   >300

The width is not free, but the cost grows gently (roughly linearly) over a
wide range; the return width costs more than the argument width (the return
value is carried in state and compared at full width in the claim, the
argument only appears in congruence conditions). Depth dominates: 2x depth is
about 20x time already at 10 bits. At 32 bits the interpreted multiplication
does not finish even at depth 10 (> 900 s vs. 0.8 s with the UF).
"""
import csv
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
DONE_RE = re.compile(r'DONE \((\w+), rc=(\d+)\)')

ENGINES = {
    'bitwuzla': 'smtbmc bitwuzla',
    'yices': 'smtbmc yices',
}


def sby_text(mode, wi, wo, depth, solver='bitwuzla', bad=False):
    defs = '-DBAD ' if bad else ''
    # stim is always a UF; in nouf mode only the box (mul) is interpreted. The
    # mode is selected with the parameter UF_MODE (sby only gives the value);
    # the marks are present in both modes and uf_disable (1-bit !UF_MODE)
    # tells which one is active.
    uf_mode = 1 if mode == 'uf' else 0
    # Channels a and b share the chan module (BAD: different OFS -> two derived modules).
    nmod = 2 if bad else 1
    guard = (f'select -assert-count {4 * nmod} a:uf_instance=mul\n'
             f"select -assert-count {4 * nmod} a:uf_instance=mul a:uf_disable=1'{1 - uf_mode} %i\n"
             f"select -assert-none a:uf_disable=1'{uf_mode}\n")
    stimguard = f'select -assert-count {nmod} a:uf_instance=stim\n'
    return f"""[options]
mode bmc
depth {depth}

[engines]
{ENGINES[solver]}

[script]
read_verilog -formal -sv {defs}width.sv
chparam -set WI {wi} -set WO {wo} -set UF_MODE {uf_mode} top
hierarchy -top top
{guard}{stimguard}prep -top top

[files]
width.sv
"""


def point_name(mode, wi, wo, depth, solver='bitwuzla', bad=False):
    return f"{mode}_i{wi}_o{wo}_d{depth}_{solver}{'_bad' if bad else ''}"


def run_point(workroot, mode, wi, wo, depth, solver='bitwuzla', bad=False, timeout=600):
    """Run one point in the directory workroot/<name>. Returns (status, seconds, log).
    Timeout: status 'TIMEOUT', seconds = timeout (lower bound)."""
    name = point_name(mode, wi, wo, depth, solver, bad)
    work = Path(workroot) / name
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    shutil.copy(HERE / 'width.sv', work / 'width.sv')
    (work / 'w.sby').write_text(sby_text(mode, wi, wo, depth, solver, bad))
    t0 = time.monotonic()
    # Own process group: on timeout the children of sby (the solver) are killed too.
    p = subprocess.Popen(['sby', '-f', 'w.sby'], cwd=work, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, start_new_session=True)
    try:
        log, _ = p.communicate(timeout=timeout)
        done = DONE_RE.findall(log)
        status = done[-1][0] if done else 'ERROR'
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGKILL)
        log, _ = p.communicate()
        status = 'TIMEOUT'
    dt = time.monotonic() - t0
    return status, dt, log


WIDTHS = [4, 10, 32, 64, 110, 256]
DEPTHS = [10, 20, 40]
FIXED = 10


def grid(name):
    """Returns a list of points (mode, wi, wo, depth, solver, bad)."""
    pts = []
    if name in ('arg', 'all'):
        pts += [('uf', w, FIXED, d, 'bitwuzla', False) for w in WIDTHS for d in DEPTHS]
    if name in ('ret', 'all'):
        pts += [('uf', FIXED, w, d, 'bitwuzla', False) for w in WIDTHS for d in DEPTHS
                if w != FIXED]
    if name in ('yices', 'all'):
        pts += [('uf', w, FIXED, 20, 'yices', False) for w in WIDTHS]
    if name in ('nouf', 'all'):
        pts += [('nouf', w, w, d, 'bitwuzla', False) for w in (4, 10, 32) for d in DEPTHS]
    if name in ('bad', 'all'):
        pts += [('uf', w, FIXED, 20, 'bitwuzla', True) for w in WIDTHS]
        pts += [('uf', FIXED, w, 20, 'bitwuzla', True) for w in WIDTHS if w != FIXED]
        pts += [('nouf', w, w, 10, 'bitwuzla', True) for w in (4, 10)]
    return pts


def main(argv):
    if len(argv) < 4 or argv[1] != 'grid':
        print(__doc__)
        return 2
    gname, out = argv[2], Path(argv[3])
    jobs, timeout = 32, 600
    if '--jobs' in argv:
        jobs = int(argv[argv.index('--jobs') + 1])
    if '--timeout' in argv:
        timeout = int(argv[argv.index('--timeout') + 1])
    workroot = out.parent / (out.stem + '_work')
    pts = grid(gname)

    def one(pt):
        st, dt, _ = run_point(workroot, *pt, timeout=timeout)
        print(f'{point_name(*pt)} {st} {dt:.1f}', flush=True)
        return (point_name(*pt),) + pt + (st, round(dt, 2))

    with ThreadPoolExecutor(jobs) as ex:
        rows = list(ex.map(one, pts))
    with open(out, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['name', 'mode', 'wi', 'wo', 'depth', 'solver', 'bad', 'status', 'seconds'])
        w.writerows(rows)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))

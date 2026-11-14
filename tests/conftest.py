"""Shared helpers for the tests.

Everything runs in the runtime container (./tc.sh pytest): yosys, the ghdl
plugin and sby are on PATH. sby runs happen in tmp_path, so no output
directories are created in the source directories and parallel runs
(-n auto) do not collide.
"""
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# yosys warning about a uf_instance attribute that was not handled (also a
# uf_disable attribute that has no effect)
UF_IGNORED_RE = re.compile(r'Warning: (Ignoring uf_instance attribute|Attribute uf_(instance|disable) .* has no effect)')


@dataclass
class Run:
    returncode: int
    log: str

    @property
    def uf_warnings(self):
        return [l for l in self.log.splitlines() if UF_IGNORED_RE.search(l)]


def run_yosys(script, cwd, ghdl=False, timeout=600):
    """Run a yosys script (separated by semicolons or newlines). Returns a Run."""
    cmd = ['yosys', '-q']
    if ghdl:
        cmd += ['-m', 'ghdl']
    cmd += ['-p', script]
    p = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       text=True, timeout=timeout)
    return Run(p.returncode, p.stdout)


@dataclass
class SbyResult:
    status: str          # PASS / FAIL / UNKNOWN / ERROR / TIMEOUT
    returncode: int
    log: str
    workdir: Path

    @property
    def uf_warnings(self):
        return [l for l in self.log.splitlines() if UF_IGNORED_RE.search(l)]


DONE_RE = re.compile(r'DONE \((\w+), rc=(\d+)\)')


def _ignore_subdirs(path, names):
    """copytree ignore: copy only files, no subdirectories.

    Test directories have no source subdirectories; subdirectories are sby
    output directories (dsp2_bmc/, counter/, ...) or __pycache__. A name
    pattern such as 'dsp*_*' would also match the source file dsp_core.vhdl.
    """
    return [n for n in names if (Path(path) / n).is_dir() or n.endswith('.pyc')]


def run_sby(src_dir, sby_file, task, tmp_path, timeout=1800):
    """Copy src_dir into tmp_path and run `sby -f <sby_file> <task>`.

    Returns the final task status taken from sby's DONE line.
    """
    src_dir = Path(src_dir)
    work = tmp_path / src_dir.name
    shutil.copytree(src_dir, work, dirs_exist_ok=True, ignore=_ignore_subdirs)
    cmd = ['sby', '-f', sby_file] + ([task] if task else [])
    p = subprocess.run(cmd, cwd=work, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       text=True, timeout=timeout)
    done = DONE_RE.findall(p.stdout)
    status = done[-1][0] if done else 'ERROR'
    return SbyResult(status, p.returncode, p.stdout, work)


def mutated_copy(src_dir, dst, edits=None):
    """Copy the files of src_dir (no subdirectories) to dst and apply edits.

    edits: {file: [(old, new), ...]}. Each old text must occur in the file
    exactly once, so that a mutation is never silently skipped.
    Returns dst.
    """
    dst = Path(dst)
    shutil.copytree(Path(src_dir), dst, dirs_exist_ok=True, ignore=_ignore_subdirs)
    for f, pairs in (edits or {}).items():
        p = dst / f
        text = p.read_text()
        for old, new in pairs:
            assert text.count(old) == 1, (f, old, text.count(old))
            text = text.replace(old, new)
        p.write_text(text)
    return dst


FAILED_ASSERT_RE = re.compile(r'Assert failed in \S+: (\S+)')


def failed_asserts(log):
    """Names of the assertions smtbmc reported as failed, in log order."""
    return FAILED_ASSERT_RE.findall(log)


REACHED_COVER_RE = re.compile(r'Reached cover statement in step (\d+)')


def cover_steps(log):
    """Steps at which smtbmc reached a cover statement."""
    return [int(x) for x in REACHED_COVER_RE.findall(log)]


@pytest.fixture
def sby(tmp_path):
    def _run(src_dir, sby_file, task=None, **kw):
        return run_sby(src_dir, sby_file, task, tmp_path, **kw)
    return _run


# ---------------------------------------------------------------- sby model inspection

# UF declaration: the name contains no '#' (state variables look like |module#n|)
# and the arguments are bit vectors (state functions take a |module_s| argument).
# A zero-argument UF (a hierarchy cell without inputs) looks like
# (declare-fun |k| () (_ BitVec R)).
UF_DECL_RE = re.compile(r'^\(declare-fun \|([^|#]+)\| \((\(_ BitVec|\))')


def sby_model(r, task_dir):
    """The model produced by sby's own model build (design_prep.ys + write_smt2).

    This is what the solver actually sees: select guards in the [script]
    section do not see sby's later prep step (opt_clean, opt -fast without
    -keepdc).
    """
    return (r.workdir / task_dir / 'model' / 'design_smt2.smt2').read_text()


def uf_decls(smt):
    """UF declarations of an SMT2 text as {symbol: [lines]}."""
    out = {}
    for l in smt.splitlines():
        m = UF_DECL_RE.match(l)
        if m:
            out.setdefault(m.group(1), []).append(l)
    return out


def smt2_module_sections(text):
    """{module name: text}, split at '; yosys-smt2-module <name>' lines."""
    parts = re.split(r'^; yosys-smt2-module (\S+)\s*$', text, flags=re.M)
    return dict(zip(parts[1::2], parts[2::2]))


SMT2_TOPMOD_RE = re.compile(r'^; yosys-smt2-topmod (\S+)', flags=re.M)
SMT2_CELL_RE = re.compile(r'^; yosys-smt2-cell (\S+) (\S+)', flags=re.M)


def reachable_modules(text, top=None):
    """Modules reachable from top through '; yosys-smt2-cell' lines.

    A UF-marked hierarchy cell produces no yosys-smt2-cell line, so its type
    module (dead text) is not reachable. top defaults to the value of the
    '; yosys-smt2-topmod' line.
    """
    sections = smt2_module_sections(text)
    if top is None:
        m = SMT2_TOPMOD_RE.search(text)
        assert m, 'yosys-smt2-topmod missing'
        top = m.group(1)
    seen, todo = set(), [top]
    while todo:
        mod = todo.pop()
        if mod in seen:
            continue
        seen.add(mod)
        todo += [t for t, _ in SMT2_CELL_RE.findall(sections[mod])]
    return seen


# ---------------------------------------------------------------- vacuity

def sby_script(sby_file, tags):
    """[script] lines of an sby file for the given task tags (as sby would run them).

    Comments and blank lines are dropped; a 'tag: line' is kept only if tag
    is in `tags`. Lines are returned as is (including 'plugin -i ghdl').
    """
    out, in_script = [], False
    for line in Path(sby_file).read_text().splitlines():
        if line.startswith('['):
            in_script = line.strip() == '[script]'
            continue
        if not in_script:
            continue
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        m = re.match(r'(\w+):\s+(.*)', line)
        if m:
            if m.group(1) not in tags:
                continue
            line = m.group(2)
        out.append(line)
    return out


# Vacuity check: both channels have produced beats since the same reset and the
# assertions are armed. The counters clear on reset and armed is '0' only on
# the first cycle after reset, so ocnt >= 3 means at least two checked (B) /
# constraining (A) beats.
COVER_BOTH = ("    -- Vacuity check: both channels produce checked beats.\n"
              "    c_both_checked : cover {armed = '1' and rst_in = '0' and "
              "ocnt_a >= 3 and ocnt_b >= 3};\n")

# Deep vacuity check: A runs at full rate, so ocnt_a >= 16 is reached at step 19
# at the earliest (initial reset at step 0, latency 2), i.e. on the last step
# of a depth-20 BMC. The shallow COVER_BOTH (step 6) does not rule out a fault
# that cuts the paths only later (e.g. a_define pruning beat 8 of A in a
# non-UF run); this one shows that checked beats of both channels continue
# up to the end of the horizon.
COVER_DEEP = ("    -- Vacuity check (deep): A produces beats up to the end of the horizon.\n"
              "    c_both_deep : cover {armed = '1' and rst_in = '0' and "
              "ocnt_a >= 16 and ocnt_b >= 3};\n")

# Sensitivity checks: assumptions under which COVER_BOTH must not be reachable.
# - a_define_contradiction: the vacuity failure mode. The assumption is the
#   negation of a_define (A's result does NOT match the output function), so
#   together they forbid every checked beat of A -> the state space empties,
#   just as a datapath change would with a non-abstracted out_f.
# - b_never_valid: an assumption that closes the channel (B never accepts a beat).
# (No rst_in = '1' style assumption: COVER_BOTH itself contains the condition
# rst_in = '0', so it would be unreachable with any design.)
VACUITY_INJECT = {
    'a_define_contradiction': (
        "    v_a_define_contradiction : assume always\n"
        "        (armed = '1' and rst_in = '0' and yvalid_a = '1') -> (a_res /= ufout_a);\n"),
    'b_never_valid': "    v_b_never_valid : assume always valid_b_in = '0';\n",
}


def insert_before_arch_end(vhdl, text):
    """Insert text before the final 'end' line of the architecture."""
    lines = vhdl.splitlines(keepends=True)
    ends = [i for i, l in enumerate(lines) if re.match(r'end\b[^;]*;', l)]
    assert len(ends) >= 2, 'entity and architecture end not found'
    arch_end = ends[-1]
    head = ''.join(lines[:arch_end])
    assert re.search(r'^architecture\b', head, flags=re.M | re.I)
    assert not re.search(r'^end\b', ''.join(lines[arch_end + 1:]), flags=re.M)
    return head + text + ''.join(lines[arch_end:])


def run_cover(src_dir, sources, script, tmp_path, tb='tb_dsp_formal.vhdl',
              extra='', depth=20, cover=COVER_BOTH):
    """Run sby in cover mode on a copy whose testbench has `cover` (default
    COVER_BOTH) and an optional `extra`, e.g. a VACUITY_INJECT assumption, added.
    The source files are not touched.
    """
    src = tmp_path / 'src' / 'cov'
    src.mkdir(parents=True)
    for f in sources:
        shutil.copy2(Path(src_dir) / f, src / f)
    p = src / tb
    p.write_text(insert_before_arch_end(p.read_text(), cover + extra))
    (src / 'cov.sby').write_text(
        f'[options]\nmode cover\ndepth {depth}\n\n[engines]\nsmtbmc bitwuzla\n\n[script]\n'
        + ''.join(l + '\n' for l in script)
        + '\n[files]\n' + ''.join(f + '\n' for f in sources))
    return run_sby(src, 'cov.sby', None, tmp_path)

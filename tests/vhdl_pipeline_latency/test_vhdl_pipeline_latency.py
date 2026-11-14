"""vhdl_pipeline_latency: output = function of the inputs from one cycle earlier.

u_core (inside the DUT) and u_ref (the testbench reference) are instances of
the same uninterpreted function dsp_f (VHDL label attribute), so the proof
does not depend on what dsp_core computes.

- test_dsp: bmc and prove PASS, plus structural checks on sby's final model.
- test_vacuity_cover*: a_value is armed (cover), and the cover is sensitive.
- test_vacuity_cover_deep: a_value is armed on ten consecutive cycles, i.e.
  also on the last step of the BMC horizon.
- test_two_register_delay_fails: two-register delay -> FAIL a_value (a wrong
  latency must be caught even with the datapath abstracted).
- test_reset_mutation_fails: ghost beat after reset -> FAIL a_rst_valid.
"""
import re
from pathlib import Path

import pytest

from conftest import (cover_steps, failed_asserts, mutated_copy, reachable_modules,
                      run_cover, run_sby, sby_model, sby_script, smt2_module_sections,
                      uf_decls)

HERE = Path(__file__).resolve().parent

SOURCES = ['dsp_core.vhdl', 'dsp_dut.vhdl', 'tb_dsp_dut_formal.vhdl']
TB = 'tb_dsp_dut_formal.vhdl'
DEPTH = 12

DSP_F_DECL = '(declare-fun |dsp_f| ((_ BitVec 16) (_ BitVec 16)) (_ BitVec 32))'


def _decls(smt):
    """uf_decls without the trailing line comment (first-use layout)."""
    return {k: [l.split(' ;', 1)[0] for l in v] for k, v in uf_decls(smt).items()}


@pytest.mark.parametrize('task', ['bmc', 'prove'])
def test_dsp(sby, task):
    r = sby(HERE, 'dsp.sby', task)
    assert r.status == 'PASS', r.log[-3000:]
    assert r.uf_warnings == [], r.uf_warnings
    smt = sby_model(r, f'dsp_{task}')
    assert _decls(smt) == {'dsp_f': [DSP_F_DECL]}, uf_decls(smt)
    sections = smt2_module_sections(smt)
    assert DSP_F_DECL in sections['dsp_dut_Brtl']
    assert '(|dsp_f|' in sections['dsp_dut_Brtl']
    assert '(|dsp_f|' in sections['tb_dsp_dut_formal']
    assert '_h u_core|' not in smt
    assert '_h u_ref|' not in smt
    assert not re.search(r'^; yosys-smt2-cell dsp_core_Brtl ', smt, flags=re.M)
    assert reachable_modules(smt) == {'tb_dsp_dut_formal', 'dsp_dut_Brtl'}


# ---------------------------------------------------------------- vacuity

# a_value is armed: valid_in = '1' on the previous clock, outside reset.
COVER_VALUE = ("    -- Vacuity check: the data value is checked (a_value armed).\n"
               "    c_value_checked : cover {armed = '1' and rst_in = '0' and "
               "prev(valid_in) = '1'};\n")


# Deep cover: a_value armed on DEEP_RUN consecutive cycles without reset.
# Step 0 is the initial state (armed = '0'), so the earliest hit is at step
# DEEP_RUN = DEPTH - 2: the first of the last two BMC steps (DEPTH - 2,
# DEPTH - 1). A shallow cover (step 1) does not rule out an assumption or a
# DUT bug that cuts paths later; this one shows a checked cycle at the end of
# the horizon.
DEEP_RUN = DEPTH - 2
COVER_DEEP = ("    -- Vacuity check (deep): a_value armed consecutively up to the end of the horizon.\n"
              "    c_value_deep : cover {(armed = '1' and rst_in = '0' and "
              f"prev(valid_in) = '1')[*{DEEP_RUN}]}};\n")


def _cover(tmp_path, extra='', cover=COVER_VALUE):
    return run_cover(HERE, SOURCES, sby_script(HERE / 'dsp.sby', {'bmc'}), tmp_path,
                     tb=TB, extra=extra, depth=DEPTH, cover=cover)


def test_vacuity_cover(tmp_path):
    """The cover is reached, and the cover run's own model contains the same dsp_f UF as test_dsp."""
    r = _cover(tmp_path)
    assert r.status == 'PASS', r.log[-3000:]
    assert 'Reached cover statement' in r.log, r.log[-3000:]
    assert 'Unreached cover' not in r.log, r.log[-3000:]
    assert cover_steps(r.log)[0] + 2 <= DEPTH, cover_steps(r.log)
    assert r.uf_warnings == [], r.uf_warnings
    smt = sby_model(r, 'cov')
    assert _decls(smt) == {'dsp_f': [DSP_F_DECL]}, uf_decls(smt)
    assert '_h u_core|' not in smt and '_h u_ref|' not in smt
    assert reachable_modules(smt) == {'tb_dsp_dut_formal', 'dsp_dut_Brtl'}


def test_vacuity_cover_deep(tmp_path):
    """The deep cover is reached within the BMC horizon (step < DEPTH)."""
    r = _cover(tmp_path, cover=COVER_DEEP)
    assert r.status == 'PASS', r.log[-3000:]
    assert 'Unreached cover' not in r.log, r.log[-3000:]
    steps = cover_steps(r.log)
    assert steps and DEEP_RUN <= steps[0] < DEPTH, steps
    assert r.uf_warnings == [], r.uf_warnings


def test_vacuity_cover_sensitivity(tmp_path):
    """Sensitivity: valid_in always '0' -> a_value is never armed, cover stays unreached."""
    r = _cover(tmp_path, "    v_never_valid : assume always valid_in = '0';\n")
    assert r.status == 'FAIL', r.log[-3000:]
    assert 'Unreached cover statement' in r.log, r.log[-3000:]


# ---------------------------------------------------------------- mutation

# data_out gets dsp_core's value through two registers (core_q in between).
TWO_REG_DELAY = {'dsp_dut.vhdl': [
    ('    signal core_y : signed(31 downto 0);\n',
     '    signal core_y : signed(31 downto 0);\n    signal core_q : signed(31 downto 0);\n'),
    ("                if valid_in = '1' then\n                    data_out <= core_y;",
     "                core_q <= core_y;\n"
     "                if valid_in = '1' then\n                    data_out <= core_q;"),
]}


@pytest.mark.parametrize('task', ['bmc', 'prove'])
def test_two_register_delay_fails(tmp_path, task):
    """With abstraction (dsp_f UF) the wrong latency fails assertion a_value, status FAIL (not ERROR)."""
    src = mutated_copy(HERE, tmp_path / 'mut' / HERE.name, TWO_REG_DELAY)
    r = run_sby(src, 'dsp.sby', task, tmp_path)
    assert r.status == 'FAIL', r.log[-3000:]
    assert 'a_value' in failed_asserts(r.log), r.log[-3000:]
    assert _decls(sby_model(r, f'dsp_{task}')) == {'dsp_f': [DSP_F_DECL]}


# ---------------------------------------------------------------- reset mutations

# Ghost beat after reset: valid_out is not cleared by reset. armed excludes the
# cycle after reset from a_valid, a_value and a_hold, so only a_rst_valid sees
# these mutations (without it they all PASS).
_IFR = "            if rst_in = '1' then\n"
_RSTV = "                valid_out <= '0';\n"
RESET_MUTATIONS = {
    # reset removed entirely: valid_out = prev(valid_in) also during reset
    'rst_never': {'dsp_dut.vhdl': [(_IFR, "            if false then\n")]},
    # valid_out reset value '1'
    'rst_vout1': {'dsp_dut.vhdl': [(_RSTV, "                valid_out <= '1';\n")]},
    # valid_out reset assignment removed: the old value stays
    'rst_vout_drop': {'dsp_dut.vhdl': [(_RSTV, '')]},
}


@pytest.mark.parametrize('task', ['bmc', 'prove'])
@pytest.mark.parametrize('mut', sorted(RESET_MUTATIONS))
def test_reset_mutation_fails(tmp_path, mut, task):
    """A ghost beat after reset fails assertion a_rst_valid (FAIL, not ERROR)."""
    src = mutated_copy(HERE, tmp_path / 'mut' / HERE.name, RESET_MUTATIONS[mut])
    r = run_sby(src, 'dsp.sby', task, tmp_path)
    assert r.status == 'FAIL', r.log[-3000:]
    # prove: basecase and induction may both report the same assertion
    assert set(failed_asserts(r.log)) == {'a_rst_valid'}, r.log[-3000:]

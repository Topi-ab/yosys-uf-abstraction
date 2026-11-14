-- Testbench output function as an uninterpreted function: the expected
-- complex output as a function of the output beat index
-- (out_f: idx -> re & im). In UF runs channel A DEFINES this function (assume
-- a_define) and channel B is CHECKED against it (assert a_match).
-- Instantiated only in UF runs (UF_MODE = true), so the architecture is never
-- interpreted; the non-UF comparison run computes the FIR reference in the
-- testbench (tb_fir_pipe_data_formal.vhdl, g_nouf_fun).
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

use work.fir_complex_pipe_pkg.all;

entity tb_fir_pipe_out_formal is
    generic (
        TAPS  : positive := 5;
        WIDTH : positive := 8
    );
    port (
        idx_in : in  unsigned(15 downto 0);
        re_out : out signed(out_width(TAPS, WIDTH) - 1 downto 0);
        im_out : out signed(out_width(TAPS, WIDTH) - 1 downto 0)
    );
    -- A UF box must keep its cell and hierarchy structure all the way to
    -- write_smt2 (see tests/mark_preservation): keep protects it from
    -- opt_clean, keep_hierarchy from flatten (flattening would lose the
    -- instance's uf_instance).
    attribute keep : boolean;
    attribute keep of tb_fir_pipe_out_formal : entity is true;
    attribute keep_hierarchy : boolean;
    attribute keep_hierarchy of tb_fir_pipe_out_formal : entity is true;
end;

architecture rtl of tb_fir_pipe_out_formal is
begin
    re_out <= resize(signed(idx_in), out_width(TAPS, WIDTH));
    im_out <= resize(-signed(idx_in), out_width(TAPS, WIDTH));
end;

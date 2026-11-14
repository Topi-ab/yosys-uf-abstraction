-- Testbench stimulus as an uninterpreted function: the complex input sample
-- as a function of the input beat index (stim_f: idx -> re & im). No
-- constraints. Instantiated only in UF runs (UF_MODE = true), so the
-- architecture is never interpreted; the non-UF comparison run uses the
-- free table of the testbench (tb_fir_pipe_data_formal.vhdl, g_nouf_fun).
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity tb_fir_pipe_stim_formal is
    generic (
        WIDTH : positive := 8
    );
    port (
        idx_in : in  unsigned(15 downto 0);
        re_out : out signed(WIDTH - 1 downto 0);
        im_out : out signed(WIDTH - 1 downto 0)
    );
    -- A UF box must keep its cell and hierarchy structure all the way to
    -- write_smt2 (see tests/mark_preservation): keep protects it from
    -- opt_clean, keep_hierarchy from flatten (flattening would lose the
    -- instance's uf_instance).
    attribute keep : boolean;
    attribute keep of tb_fir_pipe_stim_formal : entity is true;
    attribute keep_hierarchy : boolean;
    attribute keep_hierarchy of tb_fir_pipe_stim_formal : entity is true;
end;

architecture rtl of tb_fir_pipe_stim_formal is
begin
    re_out <= resize(signed(idx_in) * 3 - 7, WIDTH);
    im_out <= resize(5 - signed(idx_in) * 2, WIDTH);
end;

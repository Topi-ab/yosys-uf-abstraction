-- Testbench stimulus as an uninterpreted function: the input sequence as a
-- function of the beat index. No generator, no constraints.
-- The index is always 16 bits, the data WIDTH bits.
-- The architecture exists only for a non-UF run (in this directory both
-- tasks run this as a UF).
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity tb_stim_formal is
    generic (
        WIDTH : positive := 8
    );
    port (
        idx_in   : in  signed(15 downto 0);
        data_out : out signed(WIDTH - 1 downto 0)
    );
    -- keep + keep_hierarchy: the UF box survives up to write_smt2, see
    -- tests/vhdl_control_independence_setattr and tests/mark_preservation.
    attribute keep : boolean;
    attribute keep of tb_stim_formal : entity is true;
    attribute keep_hierarchy : boolean;
    attribute keep_hierarchy of tb_stim_formal : entity is true;
end;

architecture rtl of tb_stim_formal is
begin
    data_out <= resize(idx_in * 3 - 7, WIDTH);
end;

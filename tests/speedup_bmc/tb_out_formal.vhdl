-- Output function of the testbench as an uninterpreted function: the expected
-- output as a function of the output beat index. Channel A BINDS this function
-- with an assumption, channel B is CHECKED against it with an assertion.
-- The index is always 16 bits, the data WIDTH bits.
-- The architecture exists only for a non-UF run (in this directory both
-- tasks run this as a UF).
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity tb_out_formal is
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
    attribute keep of tb_out_formal : entity is true;
    attribute keep_hierarchy : boolean;
    attribute keep_hierarchy of tb_out_formal : entity is true;
end;

architecture rtl of tb_out_formal is
begin
    data_out <= resize(resize(idx_in * 3 - 7, WIDTH) * resize(idx_in * 3 - 7, WIDTH), WIDTH);
end;

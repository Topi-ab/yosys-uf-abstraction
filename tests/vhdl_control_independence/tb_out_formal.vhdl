-- The testbench output function as an uninterpreted function: the expected
-- output as a function of the output beat index. Channel A DEFINES this
-- function with an assume, channel B is CHECKED against it with an assert.
-- The architecture exists only for the non-UF comparison run.
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity tb_out_formal is
    port (
        idx_in   : in  signed(15 downto 0);
        data_out : out signed(15 downto 0)
    );
    -- The UF box must keep its cell and hierarchy structure all the way to write_smt2:
    -- keep: opt_clean does not remove cells whose type module has keep
    -- (Cell::has_keep_attr also looks at the module). opt_merge merges
    -- hierarchical cells only with -share_all (not in prep); even then two
    -- keep cells stay apart, and here all instances are of the same keep
    -- module.
    -- keep_hierarchy: flatten ignores keep; flattening would move the
    -- instance's uf_instance onto a $scopeinfo cell and the mark would be lost.
    -- See tests/mark_preservation.
    attribute keep : boolean;
    attribute keep of tb_out_formal : entity is true;
    attribute keep_hierarchy : boolean;
    attribute keep_hierarchy of tb_out_formal : entity is true;
end;

architecture rtl of tb_out_formal is
begin
    data_out <= resize((idx_in * 3 - 7) * (idx_in * 3 - 7), 16);
end;

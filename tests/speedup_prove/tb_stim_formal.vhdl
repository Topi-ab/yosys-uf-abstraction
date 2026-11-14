-- Testbench stimulus as an uninterpreted function: the input sequence as a
-- function of the beat index. No generator, no constraints.
-- The index is always 16 bits, the data WIDTH bits (generic).
-- The architecture exists only for a non-UF comparison run; in this
-- directory both prove tasks run this as a UF.
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
    -- The UF box has to keep its cell and hierarchy structure up to write_smt2:
    -- keep: opt_clean does not remove cells whose type module is keep
    -- (Cell::has_keep_attr also looks at the module). opt_merge merges
    -- hierarchy cells only with -share_all (not in prep); even then only two
    -- keep cells stay separate, and here all instances are of the same keep
    -- module.
    -- keep_hierarchy: flatten ignores keep; when flattening, the uf_instance
    -- of the instance would move to a $scopeinfo cell and the mark would be
    -- lost. See tests/mark_preservation.
    attribute keep : boolean;
    attribute keep of tb_stim_formal : entity is true;
    attribute keep_hierarchy : boolean;
    attribute keep_hierarchy of tb_stim_formal : entity is true;
end;

architecture rtl of tb_stim_formal is
begin
    data_out <= resize(idx_in * 3 - 7, WIDTH);
end;

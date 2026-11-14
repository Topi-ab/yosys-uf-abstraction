-- Testbench stimulus as an uninterpreted function: the data of a beat as a
-- function of the beat index. No generator, no constraints. The architecture
-- exists only for a non-UF run; in a UF run it is dead text.
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity tb_axis_stim_formal is
    generic (
        WIDTH : positive := 8
    );
    port (
        idx_in   : in  unsigned(31 downto 0);
        data_out : out std_logic_vector(WIDTH - 1 downto 0)
    );
    -- keep: opt_clean does not remove the cells of the UF box; keep_hierarchy:
    -- flatten does not flatten the instance (uf_instance would be lost).
    attribute keep : boolean;
    attribute keep of tb_axis_stim_formal : entity is true;
    attribute keep_hierarchy : boolean;
    attribute keep_hierarchy of tb_axis_stim_formal : entity is true;
end;

architecture rtl of tb_axis_stim_formal is
begin
    data_out <= std_logic_vector(resize(idx_in * 7 + 3, WIDTH));
end;

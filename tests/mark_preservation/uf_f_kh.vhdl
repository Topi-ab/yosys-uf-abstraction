-- UF box with boolean keep_hierarchy on the entity (-> module attribute).
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity uf_f_kh is
    port (
        a_in  : in  unsigned(7 downto 0);
        b_in  : in  unsigned(7 downto 0);
        y_out : out unsigned(7 downto 0)
    );
    attribute keep_hierarchy : boolean;
    attribute keep_hierarchy of uf_f_kh : entity is true;
end;

architecture rtl of uf_f_kh is
begin
    y_out <= resize(a_in * b_in, 8);
end;

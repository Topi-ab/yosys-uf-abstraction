-- UF box without keep attributes (unprotected).
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity uf_f is
    port (
        a_in  : in  unsigned(7 downto 0);
        b_in  : in  unsigned(7 downto 0);
        y_out : out unsigned(7 downto 0)
    );
end;

architecture rtl of uf_f is
begin
    y_out <= resize(a_in * b_in, 8);
end;

-- VHDL box for the uf_disable tests (y = 3 * a).
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity uf_dis_box is
    port (
        a_in  : in  std_logic_vector(7 downto 0);
        y_out : out std_logic_vector(7 downto 0)
    );
end entity;

architecture rtl of uf_dis_box is
begin
    y_out <= std_logic_vector(resize(unsigned(a_in) * 3, 8));
end architecture;

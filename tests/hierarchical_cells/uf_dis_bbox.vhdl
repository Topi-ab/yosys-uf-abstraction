-- The unbound component bb is a blackbox module. UF_MODE = false would switch
-- the mark off, but a blackbox has no implementation of its own -> error.
library ieee;
use ieee.std_logic_1164.all;

entity uf_dis_bbox is
    generic (
        UF_MODE : boolean := true
    );
    port (
        x_in  : in  std_logic_vector(7 downto 0);
        y_out : out std_logic_vector(7 downto 0)
    );
end entity;

architecture rtl of uf_dis_bbox is
    component bb is
        port (
            a_in  : in  std_logic_vector(7 downto 0);
            y_out : out std_logic_vector(7 downto 0)
        );
    end component;

    attribute uf_instance : string;
    attribute uf_disable : boolean;
    attribute uf_instance of u_bb : label is "b";
    attribute uf_disable of u_bb : label is not UF_MODE;
begin
    u_bb : component bb
        port map (
            a_in  => x_in,
            y_out => y_out
        );
end architecture;

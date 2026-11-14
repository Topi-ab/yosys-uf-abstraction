-- The generic UF_MODE selects whether u1 and u2 are uninterpreted functions
-- (true, default) or interpreted (false): uf_disable = not UF_MODE. u3 has only
-- uf_disable without uf_instance -> warning "has no effect".
-- BAD: an assertion that holds only in the non-UF model.
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity tb_uf_disable_formal is
    generic (
        UF_MODE : boolean := true;
        BAD     : boolean := false
    );
    port (
        clk_in : in  std_logic;
        x_in   : in  std_logic_vector(7 downto 0);
        o1_out : out std_logic_vector(7 downto 0);
        o2_out : out std_logic_vector(7 downto 0);
        o3_out : out std_logic_vector(7 downto 0)
    );
end entity;

architecture rtl of tb_uf_disable_formal is
    signal o1 : std_logic_vector(7 downto 0);
    signal o2 : std_logic_vector(7 downto 0);

    attribute uf_instance : string;
    attribute uf_disable : boolean;
    attribute uf_instance of u1 : label is "f";
    attribute uf_disable of u1 : label is not UF_MODE;
    attribute uf_instance of u2 : label is "f";
    attribute uf_disable of u2 : label is not UF_MODE;
    attribute uf_disable of u3 : label is not UF_MODE;
begin
    u1 : entity work.uf_dis_box
        port map (
            a_in  => x_in,
            y_out => o1
        );

    u2 : entity work.uf_dis_box
        port map (
            a_in  => x_in,
            y_out => o2
        );

    u3 : entity work.uf_dis_box
        port map (
            a_in  => x_in,
            y_out => o3_out
        );

    o1_out <= o1;
    o2_out <= o2;

    default clock is rising_edge(clk_in);

    a_cong : assert always o1 = o2;

    g_bad : if BAD generate
        a_nouf : assert always o1 = std_logic_vector(resize(unsigned(x_in) * 3, 8));
    end generate;
end architecture;

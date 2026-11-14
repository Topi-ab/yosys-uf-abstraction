-- opt_merge path for hierarchy cells. The pairs are kept apart from each other
-- either by cell type or by connectivity:
--   u_n1/u_n2 and u_e1/u_e2 get the same inputs (a_in, b_in) but differ in
--   type (uf_f vs. uf_f_keep), so they do not merge with each other.
--   u_l1/u_l2 (b_in, a_in) are of type uf_f and differ from u_n* by
--   connectivity.
--   u_n1/u_n2 : uf_f,      no keep attribute,     symbols f_n1/f_n2
--   u_e1/u_e2 : uf_f_keep, keep on the entity,    symbols f_e1/f_e2
--   u_l1/u_l2 : uf_f,      keep on both labels,   symbols f_l1/f_l2
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity h_merge is
    port (
        a_in    : in  unsigned(7 downto 0);
        b_in    : in  unsigned(7 downto 0);
        y_n1_out : out unsigned(7 downto 0);
        y_n2_out : out unsigned(7 downto 0);
        y_e1_out : out unsigned(7 downto 0);
        y_e2_out : out unsigned(7 downto 0);
        y_l1_out : out unsigned(7 downto 0);
        y_l2_out : out unsigned(7 downto 0)
    );
end;

architecture rtl of h_merge is
    attribute uf_instance : string;
    attribute uf_instance of u_n1 : label is "f_n1";
    attribute uf_instance of u_n2 : label is "f_n2";
    attribute uf_instance of u_e1 : label is "f_e1";
    attribute uf_instance of u_e2 : label is "f_e2";
    attribute uf_instance of u_l1 : label is "f_l1";
    attribute uf_instance of u_l2 : label is "f_l2";

    attribute keep : boolean;
    attribute keep of u_l1 : label is true;
    attribute keep of u_l2 : label is true;
begin
    u_n1 : entity work.uf_f
        port map (
            a_in  => a_in,
            b_in  => b_in,
            y_out => y_n1_out
        );

    u_n2 : entity work.uf_f
        port map (
            a_in  => a_in,
            b_in  => b_in,
            y_out => y_n2_out
        );

    u_e1 : entity work.uf_f_keep
        port map (
            a_in  => a_in,
            b_in  => b_in,
            y_out => y_e1_out
        );

    u_e2 : entity work.uf_f_keep
        port map (
            a_in  => a_in,
            b_in  => b_in,
            y_out => y_e2_out
        );

    u_l1 : entity work.uf_f
        port map (
            a_in  => b_in,
            b_in  => a_in,
            y_out => y_l1_out
        );

    u_l2 : entity work.uf_f
        port map (
            a_in  => b_in,
            b_in  => a_in,
            y_out => y_l2_out
        );
end;

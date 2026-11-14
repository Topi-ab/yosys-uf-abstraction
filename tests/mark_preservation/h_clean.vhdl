-- opt_clean path: the outputs of the UF instances are never read.
--   u_none : uf_f,      no keep attribute               -> expected: removed
--   u_open : uf_f,      like u_none, output left open   -> expected: removed
--   u_ent  : uf_f_keep, keep on the entity (module)     -> expected: kept
--   u_lbl  : uf_f,      keep on the instance label      -> expected: kept
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity h_clean is
    port (
        a_in  : in  unsigned(7 downto 0);
        b_in  : in  unsigned(7 downto 0);
        y_out : out unsigned(7 downto 0)
    );
end;

architecture rtl of h_clean is
    signal y_none : unsigned(7 downto 0);
    signal y_ent  : unsigned(7 downto 0);
    signal y_lbl  : unsigned(7 downto 0);

    attribute uf_instance : string;
    attribute uf_instance of u_none : label is "f_none";
    attribute uf_instance of u_open : label is "f_open";
    attribute uf_instance of u_ent  : label is "f_ent";
    attribute uf_instance of u_lbl  : label is "f_lbl";

    attribute keep : boolean;
    attribute keep of u_lbl : label is true;
begin
    u_none : entity work.uf_f
        port map (
            a_in  => a_in,
            b_in  => b_in,
            y_out => y_none
        );

    u_open : entity work.uf_f
        port map (
            a_in  => a_in,
            b_in  => b_in,
            y_out => open
        );

    u_ent : entity work.uf_f_keep
        port map (
            a_in  => a_in,
            b_in  => b_in,
            y_out => y_ent
        );

    u_lbl : entity work.uf_f
        port map (
            a_in  => a_in,
            b_in  => b_in,
            y_out => y_lbl
        );

    y_out <= a_in xor b_in;
end;

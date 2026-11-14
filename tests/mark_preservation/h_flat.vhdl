-- flatten path: the outputs of all UF instances are used.
--   u_none  : uf_f      no keep attribute
--   u_lkeep : uf_f      keep on the label
--   u_ekeep : uf_f_keep keep on the entity
--   u_lkh   : uf_f      keep_hierarchy on the label
--   u_ekh   : uf_f_kh   keep_hierarchy on the entity
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity h_flat is
    port (
        a_in  : in  unsigned(7 downto 0);
        b_in  : in  unsigned(7 downto 0);
        y_none_out  : out unsigned(7 downto 0);
        y_lkeep_out : out unsigned(7 downto 0);
        y_ekeep_out : out unsigned(7 downto 0);
        y_lkh_out   : out unsigned(7 downto 0);
        y_ekh_out   : out unsigned(7 downto 0)
    );
end;

architecture rtl of h_flat is
    attribute uf_instance : string;
    attribute uf_instance of u_none  : label is "f_none";
    attribute uf_instance of u_lkeep : label is "f_lkeep";
    attribute uf_instance of u_ekeep : label is "f_ekeep";
    attribute uf_instance of u_lkh   : label is "f_lkh";
    attribute uf_instance of u_ekh   : label is "f_ekh";

    attribute keep : boolean;
    attribute keep of u_lkeep : label is true;
    attribute keep_hierarchy : boolean;
    attribute keep_hierarchy of u_lkh : label is true;
begin
    u_none : entity work.uf_f
        port map (
            a_in  => a_in,
            b_in  => b_in,
            y_out => y_none_out
        );

    u_lkeep : entity work.uf_f
        port map (
            a_in  => a_in,
            b_in  => b_in,
            y_out => y_lkeep_out
        );

    u_ekeep : entity work.uf_f_keep
        port map (
            a_in  => a_in,
            b_in  => b_in,
            y_out => y_ekeep_out
        );

    u_lkh : entity work.uf_f
        port map (
            a_in  => a_in,
            b_in  => b_in,
            y_out => y_lkh_out
        );

    u_ekh : entity work.uf_f_kh
        port map (
            a_in  => a_in,
            b_in  => b_in,
            y_out => y_ekh_out
        );
end;

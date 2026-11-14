-- Complex multiplier y = a * b (signed components).
-- fir_complex_pipe and fir_pipe_ref instantiate this once per tap and mark the
-- instances with the uf_instance label attribute "cmul": in the formal model
-- the multiplier is an uninterpreted function (args a_re, a_im, b_re, b_im ->
-- y_re & y_im). The architecture is for non-UF runs and synthesis.
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

use work.fir_complex_pipe_pkg.all;

entity cmul is
    generic (
        WIDTH : positive := 8
    );
    port (
        a_re_in  : in  signed(WIDTH - 1 downto 0);
        a_im_in  : in  signed(WIDTH - 1 downto 0);
        b_re_in  : in  signed(WIDTH - 1 downto 0);
        b_im_in  : in  signed(WIDTH - 1 downto 0);
        y_re_out : out signed(prod_width(WIDTH) - 1 downto 0);
        y_im_out : out signed(prod_width(WIDTH) - 1 downto 0)
    );
    -- A UF box must keep its cell and hierarchy structure all the way to
    -- write_smt2 (see tests/mark_preservation): keep protects it from
    -- opt_clean, keep_hierarchy from flatten (flattening would lose the
    -- instance's uf_instance).
    attribute keep : boolean;
    attribute keep of cmul : entity is true;
    attribute keep_hierarchy : boolean;
    attribute keep_hierarchy of cmul : entity is true;
end;

architecture rtl of cmul is
    constant PW : positive := prod_width(WIDTH);
begin
    y_re_out <= resize(a_re_in * b_re_in, PW) - resize(a_im_in * b_im_in, PW);
    y_im_out <= resize(a_re_in * b_im_in, PW) + resize(a_im_in * b_re_in, PW);
end;

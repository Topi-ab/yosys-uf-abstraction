-- Adder of two complex numbers y = a + b (signed components, W bits).
-- fir_complex_pipe (the adder tree stages) and fir_pipe_ref (the reference
-- computation) instantiate this and mark the instances with the uf_instance
-- label attribute "cadd": in the formal model the adder is an uninterpreted
-- function (args a_re, a_im, b_re, b_im -> y_re & y_im). The width W =
-- out_width(TAPS, WIDTH) on every tree level: the incoming products are sign
-- extended, so the sum cannot overflow. The architecture is for non-UF runs
-- and synthesis. The box is stateless (the UF check rejects a marked box that
-- has state).
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity cadd is
    generic (
        W : positive := 20
    );
    port (
        a_re_in  : in  signed(W - 1 downto 0);
        a_im_in  : in  signed(W - 1 downto 0);
        b_re_in  : in  signed(W - 1 downto 0);
        b_im_in  : in  signed(W - 1 downto 0);
        y_re_out : out signed(W - 1 downto 0);
        y_im_out : out signed(W - 1 downto 0)
    );
    -- A UF box must keep its cell and hierarchy structure all the way to
    -- write_smt2 (see tests/mark_preservation): keep protects it from
    -- opt_clean, keep_hierarchy from flatten (flattening would lose the
    -- instance's uf_instance).
    attribute keep : boolean;
    attribute keep of cadd : entity is true;
    attribute keep_hierarchy : boolean;
    attribute keep_hierarchy of cadd : entity is true;
end;

architecture rtl of cadd is
begin
    y_re_out <= a_re_in + b_re_in;
    y_im_out <= a_im_in + b_im_in;
end;

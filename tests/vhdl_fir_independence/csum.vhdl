-- Product adder: s = sum_k p(k) (complex, signed).
-- fir_complex instantiates it once (u_sum) and marks the instance with the
-- uf_instance label attribute "csum": in the formal model the adder is an
-- uninterpreted function (args p_re, p_im -> s_re & s_im). The products arrive
-- as a flat vector, tap k in bits (k+1)*PW-1 downto k*PW.
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

use work.fir_complex_pkg.all;

entity csum is
    generic (
        TAPS  : positive := 5;
        WIDTH : positive := 8
    );
    port (
        p_re_in  : in  signed(TAPS * prod_width(WIDTH) - 1 downto 0);
        p_im_in  : in  signed(TAPS * prod_width(WIDTH) - 1 downto 0);
        s_re_out : out signed(out_width(TAPS, WIDTH) - 1 downto 0);
        s_im_out : out signed(out_width(TAPS, WIDTH) - 1 downto 0)
    );
    -- The UF box must keep its cell and hierarchy structure all the way to
    -- write_smt2: keep protects it from opt_clean, keep_hierarchy from flatten
    -- (flattening would drop the uf_instance attribute of the instance).
    attribute keep : boolean;
    attribute keep of csum : entity is true;
    attribute keep_hierarchy : boolean;
    attribute keep_hierarchy of csum : entity is true;
end;

architecture rtl of csum is
    constant PW : positive := prod_width(WIDTH);
    constant OW : positive := out_width(TAPS, WIDTH);
begin
    process (all) is
        variable acc_re : signed(OW - 1 downto 0);
        variable acc_im : signed(OW - 1 downto 0);
    begin
        acc_re := (others => '0');
        acc_im := (others => '0');
        for k in 0 to TAPS - 1 loop
            acc_re := acc_re + resize(p_re_in((k + 1) * PW - 1 downto k * PW), OW);
            acc_im := acc_im + resize(p_im_in((k + 1) * PW - 1 downto k * PW), OW);
        end loop;
        s_re_out <= acc_re;
        s_im_out <= acc_im;
    end process;
end;

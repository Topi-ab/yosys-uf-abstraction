-- Reference computation for the invariants: the values of all pipeline
-- stages for one beat, computed combinationally from its window.
--
-- In: the window w(k) = x[n-k], k = 0..TAPS-1 (flattened, element k in bits
-- (k+1)*WIDTH-1 downto k*WIDTH). Out: the stage values, element m of stage i
-- in bits (i*TAPS+m+1)*OW-1 downto (i*TAPS+m)*OW. The structure is the same
-- as in fir_complex_pipe (stage 0: resize(cmul(w(k), c(k))), levels 1..L:
-- cadd in pairs, an odd last element unchanged, output stage = element 0 of
-- level L), and the multipliers and adders are marked with the same
-- uf_instance names. Therefore, in the UF model, the invariant "the data of
-- stage i = the reference value" is plain equality reasoning (congruence),
-- and the semantics of multiplication or addition is not needed.
--
-- Users: fir_complex_pipe_inv.psl (for every slot of the DUT) and
-- tb_fir_pipe_data_formal_inv.psl (the reference value of beat j). Not used in
-- the DUT.
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

use work.fir_complex_pipe_pkg.all;

entity fir_pipe_ref is
    generic (
        TAPS  : positive := 5;
        WIDTH : positive := 8
    );
    port (
        w_re_in   : in  signed(TAPS * WIDTH - 1 downto 0);
        w_im_in   : in  signed(TAPS * WIDTH - 1 downto 0);
        st_re_out : out signed(pipe_depth(TAPS) * TAPS * out_width(TAPS, WIDTH) - 1 downto 0);
        st_im_out : out signed(pipe_depth(TAPS) * TAPS * out_width(TAPS, WIDTH) - 1 downto 0)
    );
end;

architecture rtl of fir_pipe_ref is
    constant PW : positive := prod_width(WIDTH);
    constant OW : positive := out_width(TAPS, WIDTH);
    constant L  : natural  := clog2(TAPS);
    constant D  : positive := pipe_depth(TAPS);

    type vec_t is array (0 to TAPS - 1) of signed(OW - 1 downto 0);
    type stg_t is array (0 to D - 1) of vec_t;

    signal lv_re : stg_t;
    signal lv_im : stg_t;

    attribute uf_instance : string;
begin
    gen_tap : for k in 0 to TAPS - 1 generate
        signal c_re : signed(WIDTH - 1 downto 0);
        signal c_im : signed(WIDTH - 1 downto 0);
        signal p_re : signed(PW - 1 downto 0);
        signal p_im : signed(PW - 1 downto 0);
        attribute uf_instance of u_mul : label is "cmul";
    begin
        c_re <= to_signed(COEF_RE(k), WIDTH);
        c_im <= to_signed(COEF_IM(k), WIDTH);

        u_mul : entity work.cmul
            generic map (
                WIDTH => WIDTH
            )
            port map (
                a_re_in  => w_re_in((k + 1) * WIDTH - 1 downto k * WIDTH),
                a_im_in  => w_im_in((k + 1) * WIDTH - 1 downto k * WIDTH),
                b_re_in  => c_re,
                b_im_in  => c_im,
                y_re_out => p_re,
                y_im_out => p_im
            );

        lv_re(0)(k) <= resize(p_re, OW);
        lv_im(0)(k) <= resize(p_im, OW);
    end generate;

    gen_lvl : for lvl in 1 to L generate
        gen_el : for m in 0 to TAPS - 1 generate
            gen_add : if 2 * m + 1 < stage_cnt(TAPS, lvl - 1) generate
                attribute uf_instance of u_add : label is "cadd";
            begin
                u_add : entity work.cadd
                    generic map (
                        W => OW
                    )
                    port map (
                        a_re_in  => lv_re(lvl - 1)(2 * m),
                        a_im_in  => lv_im(lvl - 1)(2 * m),
                        b_re_in  => lv_re(lvl - 1)(2 * m + 1),
                        b_im_in  => lv_im(lvl - 1)(2 * m + 1),
                        y_re_out => lv_re(lvl)(m),
                        y_im_out => lv_im(lvl)(m)
                    );
            end generate;

            gen_pass : if 2 * m + 1 = stage_cnt(TAPS, lvl - 1) generate
                lv_re(lvl)(m) <= lv_re(lvl - 1)(2 * m);
                lv_im(lvl)(m) <= lv_im(lvl - 1)(2 * m);
            end generate;

            gen_zero : if 2 * m >= stage_cnt(TAPS, lvl - 1) generate
                lv_re(lvl)(m) <= (others => '0');
                lv_im(lvl)(m) <= (others => '0');
            end generate;
        end generate;
    end generate;

    lv_re(D - 1)(0) <= lv_re(D - 2)(0);
    lv_im(D - 1)(0) <= lv_im(D - 2)(0);
    gen_out_zero : for m in 1 to TAPS - 1 generate
        lv_re(D - 1)(m) <= (others => '0');
        lv_im(D - 1)(m) <= (others => '0');
    end generate;

    gen_flat : for i in 0 to D - 1 generate
        gen_flat_el : for m in 0 to TAPS - 1 generate
            st_re_out((i * TAPS + m + 1) * OW - 1 downto (i * TAPS + m) * OW) <= lv_re(i)(m);
            st_im_out((i * TAPS + m + 1) * OW - 1 downto (i * TAPS + m) * OW) <= lv_im(i)(m);
        end generate;
    end generate;
end;

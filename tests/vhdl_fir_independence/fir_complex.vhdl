-- Complex FIR filter, AXI Stream in and out.
--
--   y[n] = sum_{k=0}^{TAPS-1} c(k) * x[n-k],   x[m] = 0 for m < 0
--
-- x and c are complex numbers (signed re/im, WIDTH bits), the coefficients are
-- fixed (fir_complex_pkg: COEF_RE, COEF_IM). n is the index of the accepted
-- input beat since reset; every input beat produces exactly one output beat.
--
-- Structure:
-- - The delay line dl(0..TAPS-2) holds the TAPS-1 previous accepted samples
--   (dl(0) newest). It advances ONLY on an accepted input beat
--   (s_valid_in = '1' and s_ready_out = '1') and clears on reset.
-- - Window win(0) = s_*_in, win(k) = dl(k-1): the products c(k)*win(k) and
--   their sum are combinational (one cmul instance per tap, gen_tap/u_mul).
-- - The output register (m_valid_out, m_re_out, m_im_out) loads on an accepted
--   input beat. Latency 1 cycle: beat n is accepted in cycle t, and
--   m_valid_out = '1' with its data from cycle t+1 until m_ready_in = '1'.
-- - Backpressure: s_ready_out = not m_valid_out or m_ready_in. A stalled
--   output register stalls the input. m_valid_out comes straight from a
--   register (no combinational ready->valid path); s_ready_out depends
--   combinationally on m_ready_in (ready->ready, allowed in AXI Stream).
-- - The control state is one bit (m_valid). Data does not affect control.
--
-- Generics: TAPS (2..MAX_TAPS), WIDTH (>= 4, the coefficients fit in 4 bits),
-- UF_MODE (formal model only: true = cmul/csum as uninterpreted functions,
-- false = the marks switched off with the uf_disable attribute; default true,
-- so the DUT as is uses the abstraction written into the source).
-- Output width out_width(TAPS, WIDTH) = 2*WIDTH+1+ceil(log2(TAPS)): the sum
-- cannot overflow, so there is no truncation.
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

use work.fir_complex_pkg.all;

entity fir_complex is
    generic (
        TAPS    : positive := 5;
        WIDTH   : positive := 8;
        UF_MODE : boolean  := true
    );
    port (
        clk_in      : in  std_logic;
        rst_in      : in  std_logic;
        s_valid_in  : in  std_logic;
        s_ready_out : out std_logic;
        s_re_in     : in  signed(WIDTH - 1 downto 0);
        s_im_in     : in  signed(WIDTH - 1 downto 0);
        m_valid_out : out std_logic;
        m_ready_in  : in  std_logic;
        m_re_out    : out signed(out_width(TAPS, WIDTH) - 1 downto 0);
        m_im_out    : out signed(out_width(TAPS, WIDTH) - 1 downto 0)
    );
end;

architecture rtl of fir_complex is
    constant PW : positive := prod_width(WIDTH);
    constant OW : positive := out_width(TAPS, WIDTH);

    type smp_t is array (natural range <>) of signed(WIDTH - 1 downto 0);
    type prod_t is array (natural range <>) of signed(PW - 1 downto 0);

    function coefs(v : integer_vector) return smp_t is
        variable r : smp_t(0 to TAPS - 1);
    begin
        for k in 0 to TAPS - 1 loop
            r(k) := to_signed(v(k), WIDTH);
        end loop;
        return r;
    end function;

    constant C_RE : smp_t(0 to TAPS - 1) := coefs(COEF_RE);
    constant C_IM : smp_t(0 to TAPS - 1) := coefs(COEF_IM);

    signal dl_re   : smp_t(0 to TAPS - 2);
    signal dl_im   : smp_t(0 to TAPS - 2);
    signal win_re  : smp_t(0 to TAPS - 1);
    signal win_im  : smp_t(0 to TAPS - 1);
    signal p_re    : prod_t(0 to TAPS - 1);
    signal p_im    : prod_t(0 to TAPS - 1);
    signal pf_re   : signed(TAPS * PW - 1 downto 0);
    signal pf_im   : signed(TAPS * PW - 1 downto 0);
    signal sum_re  : signed(OW - 1 downto 0);
    signal sum_im  : signed(OW - 1 downto 0);
    signal m_valid : std_logic;
    signal s_ready : std_logic;
    signal accept  : std_logic;

    attribute uf_instance : string;
    -- The adder is an uninterpreted function in the formal model.
    attribute uf_instance of u_sum : label is "csum";
    -- UF_MODE = false: the marks are ignored, the boxes are exported interpreted.
    attribute uf_disable : boolean;
    attribute uf_disable of u_sum : label is not UF_MODE;
begin
    assert TAPS >= 2 and TAPS <= MAX_TAPS severity failure;
    assert WIDTH >= 4 severity failure;

    s_ready <= not m_valid or m_ready_in;
    accept  <= s_valid_in and s_ready;

    s_ready_out <= s_ready;
    m_valid_out <= m_valid;

    win_re(0) <= s_re_in;
    win_im(0) <= s_im_in;
    win_re(1 to TAPS - 1) <= dl_re;
    win_im(1 to TAPS - 1) <= dl_im;

    gen_tap : for k in 0 to TAPS - 1 generate
        -- The multiplier is an uninterpreted function in the formal model.
        attribute uf_instance of u_mul : label is "cmul";
        attribute uf_disable of u_mul : label is not UF_MODE;
    begin
        u_mul : entity work.cmul
            generic map (
                WIDTH => WIDTH
            )
            port map (
                a_re_in  => win_re(k),
                a_im_in  => win_im(k),
                b_re_in  => C_RE(k),
                b_im_in  => C_IM(k),
                y_re_out => p_re(k),
                y_im_out => p_im(k)
            );
    end generate;

    -- Products as flat vectors for the adder (tap k in bits
    -- (k+1)*PW-1 downto k*PW).
    gen_flat : for k in 0 to TAPS - 1 generate
        pf_re((k + 1) * PW - 1 downto k * PW) <= p_re(k);
        pf_im((k + 1) * PW - 1 downto k * PW) <= p_im(k);
    end generate;

    u_sum : entity work.csum
        generic map (
            TAPS  => TAPS,
            WIDTH => WIDTH
        )
        port map (
            p_re_in  => pf_re,
            p_im_in  => pf_im,
            s_re_out => sum_re,
            s_im_out => sum_im
        );

    process (clk_in) is
    begin
        if rising_edge(clk_in) then
            if rst_in = '1' then
                m_valid <= '0';
                dl_re   <= (others => (others => '0'));
                dl_im   <= (others => (others => '0'));
            else
                if accept = '1' then
                    dl_re    <= s_re_in & dl_re(0 to TAPS - 3);
                    dl_im    <= s_im_in & dl_im(0 to TAPS - 3);
                    m_re_out <= sum_re;
                    m_im_out <= sum_im;
                    m_valid  <= '1';
                elsif m_ready_in = '1' then
                    m_valid <= '0';
                end if;
            end if;
        end if;
    end process;
end;

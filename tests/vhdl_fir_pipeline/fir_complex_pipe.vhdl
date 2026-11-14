-- Pipelined complex FIR filter, AXI Stream in and out.
--
--   y[n] = sum_{k=0}^{TAPS-1} c(k) * x[n-k],   x[m] = 0 when m < 0
--
-- The same function as in tests/vhdl_fir_independence, but the computation
-- is split into registered stages, each with its own valid and its own ready:
--
--   stage 0        multiplier stage: the TAPS products c(k)*win(k) of the
--                  window (cmul)
--   stage 1..L     adder tree, L = ceil(log2(TAPS)) levels; level l adds the
--                  elements of the previous level in pairs (cadd), an odd
--                  last element passes through unchanged
--   stage L+1      output register (m_*_out)
--
-- D = L+2 stages (pipe_depth). The input of stage i is the main register of
-- the previous stage (stage 0: s_*_in and the delay line), its input valid is
-- in_v(i) and its ready rdy(i); rdy(D) = m_ready_in.
--
-- The delay line dl(0..TAPS-2) (dl(0) newest) advances ONLY on an accepted
-- input beat (s_valid_in = '1' and s_ready_out = '1') and is cleared on
-- reset. The window is win(0) = s_*_in, win(k) = dl(k-1).
--
-- Handshake style (generic SKID):
-- - SKID = false, a bubble-collapsing pipeline: rdy(i) = not mn_v(i) or
--   rdy(i+1). A stage loads when it is empty or its beat moves on. The ready
--   chain is combinational from m_ready_in to s_ready_out.
-- - SKID = true, a skid buffer in every stage: two slots (main mn_*, skid
--   sk_*), rdy(i) = not sk_v(i) is a register. There is no combinational
--   path m_ready_in -> s_ready_out. When the main register is stalled and a
--   beat comes in, it goes to the skid slot; when the main register frees
--   up, the skid beat moves to the main register before any new beat.
-- Both styles run at full rate (one beat per cycle) without back pressure.
--
-- Data: every stage stores its elements at width OW = out_width(TAPS, WIDTH)
-- (products sign extended), so the adder tree has no truncation. Stage i has
-- stage_cnt(TAPS, i) elements; the other elements are zeros and do not affect
-- the output. Data registers load only on a valid beat and are not cleared on
-- reset.
--
-- Control does not depend on data: the valid and ready bits are functions of
-- the control only. m_valid_out and m_*_out come directly from the registers
-- of the output stage (no combinational ready -> valid or ready -> data
-- paths).
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

use work.fir_complex_pipe_pkg.all;

entity fir_complex_pipe is
    generic (
        TAPS    : positive := 5;
        WIDTH   : positive := 8;
        -- false: combinational ready chain, true: skid buffer per stage.
        SKID    : boolean  := false;
        -- Formal model only: true = cmul/cadd as uninterpreted functions,
        -- false = marks switched off (uf_disable), non-UF datapath. Default
        -- true: the DUT as such uses the abstraction written in the source.
        -- No effect on synthesis or simulation.
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

architecture rtl of fir_complex_pipe is
    constant PW : positive := prod_width(WIDTH);
    constant OW : positive := out_width(TAPS, WIDTH);
    constant L  : natural  := clog2(TAPS);
    constant D  : positive := pipe_depth(TAPS);

    type smp_t is array (natural range <>) of signed(WIDTH - 1 downto 0);
    type vec_t is array (0 to TAPS - 1) of signed(OW - 1 downto 0);
    type stg_t is array (0 to D - 1) of vec_t;

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

    signal dl_re  : smp_t(0 to TAPS - 2);
    signal dl_im  : smp_t(0 to TAPS - 2);
    signal win_re : smp_t(0 to TAPS - 1);
    signal win_im : smp_t(0 to TAPS - 1);
    -- Input data of stage i (combinational, from the previous stage's main register).
    signal nx_re  : stg_t;
    signal nx_im  : stg_t;
    -- Main registers and (SKID) skid registers.
    signal mn_re  : stg_t;
    signal mn_im  : stg_t;
    signal sk_re  : stg_t;
    signal sk_im  : stg_t;
    signal mn_v   : std_logic_vector(0 to D - 1);
    signal sk_v   : std_logic_vector(0 to D - 1);
    -- Input valid and ready of stage i; rdy(D) = m_ready_in.
    signal in_v   : std_logic_vector(0 to D - 1);
    signal rdy    : std_logic_vector(0 to D);
    signal accept : std_logic;

    attribute uf_instance : string;
    -- UF_MODE = false: the marks are ignored, the boxes are exported interpreted.
    attribute uf_disable : boolean;
begin
    assert TAPS >= 2 and TAPS <= MAX_TAPS severity failure;
    assert WIDTH >= 4 severity failure;

    in_v(0)          <= s_valid_in;
    in_v(1 to D - 1) <= mn_v(0 to D - 2);
    rdy(D)           <= m_ready_in;
    accept           <= s_valid_in and rdy(0);

    s_ready_out <= rdy(0);
    m_valid_out <= mn_v(D - 1);
    m_re_out    <= mn_re(D - 1)(0);
    m_im_out    <= mn_im(D - 1)(0);

    win_re(0) <= s_re_in;
    win_im(0) <= s_im_in;
    win_re(1 to TAPS - 1) <= dl_re;
    win_im(1 to TAPS - 1) <= dl_im;

    -- Stage 0: multipliers (one per tap).
    gen_tap : for k in 0 to TAPS - 1 generate
        signal p_re : signed(PW - 1 downto 0);
        signal p_im : signed(PW - 1 downto 0);
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
                y_re_out => p_re,
                y_im_out => p_im
            );

        nx_re(0)(k) <= resize(p_re, OW);
        nx_im(0)(k) <= resize(p_im, OW);
    end generate;

    -- Stages 1..L: the adder tree levels. Element m of level lvl = elements
    -- 2m and 2m+1 of the previous level (cadd), or an odd last element 2m
    -- unchanged.
    gen_lvl : for lvl in 1 to L generate
        gen_el : for m in 0 to TAPS - 1 generate
            gen_add : if 2 * m + 1 < stage_cnt(TAPS, lvl - 1) generate
                -- The adder is an uninterpreted function in the formal model.
                attribute uf_instance of u_add : label is "cadd";
                attribute uf_disable of u_add : label is not UF_MODE;
            begin
                u_add : entity work.cadd
                    generic map (
                        W => OW
                    )
                    port map (
                        a_re_in  => mn_re(lvl - 1)(2 * m),
                        a_im_in  => mn_im(lvl - 1)(2 * m),
                        b_re_in  => mn_re(lvl - 1)(2 * m + 1),
                        b_im_in  => mn_im(lvl - 1)(2 * m + 1),
                        y_re_out => nx_re(lvl)(m),
                        y_im_out => nx_im(lvl)(m)
                    );
            end generate;

            gen_pass : if 2 * m + 1 = stage_cnt(TAPS, lvl - 1) generate
                nx_re(lvl)(m) <= mn_re(lvl - 1)(2 * m);
                nx_im(lvl)(m) <= mn_im(lvl - 1)(2 * m);
            end generate;

            gen_zero : if 2 * m >= stage_cnt(TAPS, lvl - 1) generate
                nx_re(lvl)(m) <= (others => '0');
                nx_im(lvl)(m) <= (others => '0');
            end generate;
        end generate;
    end generate;

    -- Stage L+1: output register.
    nx_re(D - 1)(0) <= mn_re(D - 2)(0);
    nx_im(D - 1)(0) <= mn_im(D - 2)(0);
    gen_out_zero : for m in 1 to TAPS - 1 generate
        nx_re(D - 1)(m) <= (others => '0');
        nx_im(D - 1)(m) <= (others => '0');
    end generate;

    -- Delay line: advances only on an accepted input beat.
    process (clk_in) is
    begin
        if rising_edge(clk_in) then
            if rst_in = '1' then
                dl_re <= (others => (others => '0'));
                dl_im <= (others => (others => '0'));
            elsif accept = '1' then
                dl_re <= s_re_in & dl_re(0 to TAPS - 3);
                dl_im <= s_im_in & dl_im(0 to TAPS - 3);
            end if;
        end if;
    end process;

    -- Bubble-collapsing pipeline: combinational ready chain.
    gen_comb : if not SKID generate
        sk_v  <= (others => '0');
        sk_re <= (others => (others => (others => '0')));
        sk_im <= (others => (others => (others => '0')));

        gen_stage : for i in 0 to D - 1 generate
            rdy(i) <= not mn_v(i) or rdy(i + 1);

            process (clk_in) is
            begin
                if rising_edge(clk_in) then
                    if rst_in = '1' then
                        mn_v(i) <= '0';
                    elsif rdy(i) = '1' then
                        mn_v(i) <= in_v(i);
                        if in_v(i) = '1' then
                            mn_re(i) <= nx_re(i);
                            mn_im(i) <= nx_im(i);
                        end if;
                    end if;
                end if;
            end process;
        end generate;
    end generate;

    -- Skid buffer in every stage: registered ready.
    gen_skid : if SKID generate
        gen_stage : for i in 0 to D - 1 generate
            rdy(i) <= not sk_v(i);

            process (clk_in) is
            begin
                if rising_edge(clk_in) then
                    if rst_in = '1' then
                        mn_v(i) <= '0';
                        sk_v(i) <= '0';
                    elsif mn_v(i) = '0' or rdy(i + 1) = '1' then
                        -- The main register frees up: the skid beat first,
                        -- otherwise the input (accepted, since sk_v = '0').
                        if sk_v(i) = '1' then
                            mn_re(i) <= sk_re(i);
                            mn_im(i) <= sk_im(i);
                            mn_v(i)  <= '1';
                            sk_v(i)  <= '0';
                        else
                            mn_v(i) <= in_v(i);
                            if in_v(i) = '1' then
                                mn_re(i) <= nx_re(i);
                                mn_im(i) <= nx_im(i);
                            end if;
                        end if;
                    elsif in_v(i) = '1' and sk_v(i) = '0' then
                        -- The main register is stalled: the accepted beat goes to the skid slot.
                        sk_re(i) <= nx_re(i);
                        sk_im(i) <= nx_im(i);
                        sk_v(i)  <= '1';
                    end if;
                end if;
            end process;
        end generate;
    end generate;
end;

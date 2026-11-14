-- Property 1: DATA DOES NOT DEPEND ON CONTROL.
--
-- The same DUT (fir_complex) twice with different control sequences:
-- - A: reference channel, full rate (s_valid = '1', m_ready = '1' after
--   reset; assumption a_ref_rate). A DEFINES the output function out_f
--   (a_define).
-- - B: free s_valid and m_ready (AXI rules as assumptions on the side driven
--   by the testbench). B is CHECKED against out_f (a_match).
--
-- The input is an uninterpreted function of the input beat index, stim_f(icnt),
-- so both channels see the same logical sample sequence even if they accept
-- the beats in different cycles. The expected output is an uninterpreted
-- function of the output beat index, out_f(ocnt). Since out_f is the same
-- symbol for both, congruence forces B's beat k to equal A's beat k.
--
-- UF_MODE = false (non-UF reference run): the stimulus is a free table and
-- the expected output an interpreted FIR reference (as in
-- tests/vhdl_fir_pipeline), the DUT's marks are switched off (the DUT's
-- generic UF_MODE, uf_disable), and a_define is an assertion (a_define_chk).
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

use work.fir_complex_pkg.all;

entity tb_fir_data_formal is
    generic (
        TAPS    : positive := 5;
        WIDTH   : positive := 8;
        -- true:  stim_f and out_f are UFs, the DUT's cmul/csum are UFs, and
        --        a_define (assume) binds out_f to the output of channel A.
        -- false: non-UF run: the stimulus is a free anyconst table, the
        --        expected output an interpreted FIR reference and the DUT's
        --        marks are switched off (generic passed to the DUT), so the
        --        same condition is CHECKED (a_define_chk, assert). As an
        --        assumption it would silently prune the paths on which the DUT
        --        deviates from the reference. The sby file gives the value
        --        (-gUF_MODE=...). The default false is the safe direction: a
        --        forgotten -g turns the condition into an assertion.
        UF_MODE : boolean  := false
    );
    port (
        clk_in       : in std_logic;
        rst_in       : in std_logic;
        s_valid_a_in : in std_logic;
        m_ready_a_in : in std_logic;
        s_valid_b_in : in std_logic;
        m_ready_b_in : in std_logic
    );
end;

architecture formal of tb_fir_data_formal is
    constant OW : positive := out_width(TAPS, WIDTH);

    signal icnt_a, icnt_b       : unsigned(15 downto 0) := (others => '0');
    signal ocnt_a, ocnt_b       : unsigned(15 downto 0) := (others => '0');
    signal s_re_a, s_im_a       : signed(WIDTH - 1 downto 0);
    signal s_re_b, s_im_b       : signed(WIDTH - 1 downto 0);
    signal s_ready_a, s_ready_b : std_logic;
    signal m_valid_a, m_valid_b : std_logic;
    signal m_re_a, m_im_a       : signed(OW - 1 downto 0);
    signal m_re_b, m_im_b       : signed(OW - 1 downto 0);
    signal uf_re_a, uf_im_a     : signed(OW - 1 downto 0);
    signal uf_re_b, uf_im_b     : signed(OW - 1 downto 0);
    signal s_xfer_a, s_xfer_b   : std_logic;
    signal m_xfer_a, m_xfer_b   : std_logic;
    signal armed                : std_logic := '0';
    signal first                : std_logic := '1';
    -- Previous cycle's s-side wait (valid and not ready) for B.
    signal s_wait_b_q           : std_logic := '0';
    -- Vacuity cover flags (B, after reset): on the s-side a bubble
    -- (s_valid = '0' after the first beat) and backpressure (s_valid and not
    -- s_ready), on the m-side backpressure (m_valid and not m_ready).
    signal b_s_idle             : std_logic := '0';
    signal b_s_wait             : std_logic := '0';
    signal b_m_wait             : std_logic := '0';

    -- Symbolic beat index: free initial value, stays constant (a_match).
    signal j                    : unsigned(15 downto 0);
    attribute anyconst : boolean;
    attribute anyconst of j : signal is true;

    -- The a_define condition is written once; UF_MODE selects assume or assert.
    signal a_def_ok             : std_logic;

    attribute uf_instance : string;

    -- Free stimulus table of the non-UF reference run (UF_MODE = false):
    -- sample i in bits (i+1)*WIDTH-1 downto i*WIDTH. TAB_N > BMC depth, so the
    -- index does not wrap (checked by a_tab_range_chk).
    constant TAB_N : positive := 32;
    signal tab_re, tab_im : std_logic_vector(TAB_N * WIDTH - 1 downto 0);
    attribute anyconst of tab_re : signal is true;
    attribute anyconst of tab_im : signal is true;

    function tab_at(t : std_logic_vector; idx : unsigned) return signed is
        variable i : natural range 0 to TAB_N - 1;
    begin
        i := to_integer(idx mod TAB_N);
        return signed(t((i + 1) * WIDTH - 1 downto i * WIDTH));
    end function;

    -- FIR reference y[idx] = sum_k c(k) * x[idx-k], x[m] = table, or 0 when
    -- m < 0 (the DUT's delay line is cleared on reset); im = false: real part,
    -- true: imaginary part. The widths suffice (out_width), so the sum is exact.
    function fir_ref(tr, ti : std_logic_vector; idx : unsigned; im : boolean) return signed is
        variable acc  : signed(OW - 1 downto 0);
        variable x_re : signed(WIDTH - 1 downto 0);
        variable x_im : signed(WIDTH - 1 downto 0);
        variable c_re : signed(WIDTH - 1 downto 0);
        variable c_im : signed(WIDTH - 1 downto 0);
    begin
        acc := (others => '0');
        for k in 0 to TAPS - 1 loop
            if idx >= k then
                x_re := tab_at(tr, idx - k);
                x_im := tab_at(ti, idx - k);
            else
                x_re := (others => '0');
                x_im := (others => '0');
            end if;
            c_re := to_signed(COEF_RE(k), WIDTH);
            c_im := to_signed(COEF_IM(k), WIDTH);
            if im then
                acc := acc + resize(x_re * c_im, OW) + resize(x_im * c_re, OW);
            else
                acc := acc + resize(x_re * c_re, OW) - resize(x_im * c_im, OW);
            end if;
        end loop;
        return acc;
    end function;
begin
    s_xfer_a <= s_valid_a_in and s_ready_a;
    s_xfer_b <= s_valid_b_in and s_ready_b;
    m_xfer_a <= m_valid_a and m_ready_a_in;
    m_xfer_b <= m_valid_b and m_ready_b_in;

    -- UF_MODE = true: stimulus and expected output as uninterpreted functions.
    g_uf_fun : if UF_MODE generate
        attribute uf_instance of u_stim_a : label is "stim_f";
        attribute uf_instance of u_stim_b : label is "stim_f";
        attribute uf_instance of u_out_a  : label is "out_f";
        attribute uf_instance of u_out_b  : label is "out_f";
    begin
        -- Stimulus: the same uninterpreted function for both, each channel's own index.
        u_stim_a : entity work.tb_fir_stim_formal
            generic map (
                WIDTH => WIDTH
            )
            port map (
                idx_in => icnt_a,
                re_out => s_re_a,
                im_out => s_im_a
            );

        u_stim_b : entity work.tb_fir_stim_formal
            generic map (
                WIDTH => WIDTH
            )
            port map (
                idx_in => icnt_b,
                re_out => s_re_b,
                im_out => s_im_b
            );

        -- Expected output: the same uninterpreted function for both.
        u_out_a : entity work.tb_fir_out_formal
            generic map (
                OW => OW
            )
            port map (
                idx_in => ocnt_a,
                re_out => uf_re_a,
                im_out => uf_im_a
            );

        u_out_b : entity work.tb_fir_out_formal
            generic map (
                OW => OW
            )
            port map (
                idx_in => ocnt_b,
                re_out => uf_re_b,
                im_out => uf_im_b
            );
    end generate;

    -- UF_MODE = false (non-UF reference run): the stimulus is a free table
    -- (anyconst, TAB_N samples, index icnt mod TAB_N), and the expected output
    -- is the real FIR reference from the same table. The input is thus as free
    -- as in the UF run (every index < TAB_N arbitrary), but the datapath and
    -- the reference are interpreted.
    g_nouf_fun : if not UF_MODE generate
        s_re_a <= tab_at(tab_re, icnt_a);
        s_im_a <= tab_at(tab_im, icnt_a);
        s_re_b <= tab_at(tab_re, icnt_b);
        s_im_b <= tab_at(tab_im, icnt_b);
        uf_re_a <= fir_ref(tab_re, tab_im, ocnt_a, false);
        uf_im_a <= fir_ref(tab_re, tab_im, ocnt_a, true);
        uf_re_b <= fir_ref(tab_re, tab_im, ocnt_b, false);
        uf_im_b <= fir_ref(tab_re, tab_im, ocnt_b, true);
    end generate;

    a : entity work.fir_complex
        generic map (
            TAPS    => TAPS,
            WIDTH   => WIDTH,
            UF_MODE => UF_MODE
        )
        port map (
            clk_in      => clk_in,
            rst_in      => rst_in,
            s_valid_in  => s_valid_a_in,
            s_ready_out => s_ready_a,
            s_re_in     => s_re_a,
            s_im_in     => s_im_a,
            m_valid_out => m_valid_a,
            m_ready_in  => m_ready_a_in,
            m_re_out    => m_re_a,
            m_im_out    => m_im_a
        );

    b : entity work.fir_complex
        generic map (
            TAPS    => TAPS,
            WIDTH   => WIDTH,
            UF_MODE => UF_MODE
        )
        port map (
            clk_in      => clk_in,
            rst_in      => rst_in,
            s_valid_in  => s_valid_b_in,
            s_ready_out => s_ready_b,
            s_re_in     => s_re_b,
            s_im_in     => s_im_b,
            m_valid_out => m_valid_b,
            m_ready_in  => m_ready_b_in,
            m_re_out    => m_re_b,
            m_im_out    => m_im_b
        );

    process (clk_in) is
    begin
        if rising_edge(clk_in) then
            first <= '0';
            armed <= not rst_in;
            if rst_in = '1' then
                icnt_a      <= (others => '0');
                icnt_b      <= (others => '0');
                ocnt_a      <= (others => '0');
                ocnt_b      <= (others => '0');
                s_wait_b_q  <= '0';
                b_s_idle    <= '0';
                b_s_wait    <= '0';
                b_m_wait    <= '0';
            else
                if s_xfer_a = '1' then icnt_a <= icnt_a + 1; end if;
                if s_xfer_b = '1' then icnt_b <= icnt_b + 1; end if;
                if m_xfer_a = '1' then ocnt_a <= ocnt_a + 1; end if;
                if m_xfer_b = '1' then ocnt_b <= ocnt_b + 1; end if;
                s_wait_b_q <= s_valid_b_in and not s_ready_b;
                if s_valid_b_in = '0' and icnt_b /= 0 then
                    b_s_idle <= '1';
                end if;
                if s_valid_b_in = '1' and s_ready_b = '0' then
                    b_s_wait <= '1';
                end if;
                if m_valid_b = '1' and m_ready_b_in = '0' then
                    b_m_wait <= '1';
                end if;
            end if;
        end if;
    end process;

    a_def_ok <= '1' when armed = '0' or rst_in = '1' or m_xfer_a = '0' or
                         (m_re_a = uf_re_a and m_im_a = uf_im_a) else '0';

    default clock is rising_edge(clk_in);

    -- Initial reset: without it the uninitialized DUT state could produce phantom beats.
    a_init_reset : assume always
        (first = '1') -> (rst_in = '1');

    -- A is the reference channel: full rate, so that it defines out_f at every
    -- index B can reach. Without this out_f stays free at indices A did not
    -- produce, and a_match fails trivially.
    a_ref_rate : assume always
        (rst_in = '0') -> (s_valid_a_in = '1' and m_ready_a_in = '1');

    -- Modelling bound: the index counters (16 bits) do not wrap. After a
    -- wrap stim_f(icnt) would repeat periodically and the beat indices would
    -- get mixed up (zero fill at the start of beat j vs. samples of the
    -- previous round). A transfers a beat every cycle, so this limits the
    -- check to the first 2^16-1 cycles after each reset; B is always behind
    -- A. At BMC depths the bound restricts nothing; in k-induction it
    -- excludes wrapped states.
    a_no_wrap : assume always
        (rst_in = '0') -> (icnt_a /= x"FFFF");

    -- AXI s-side (testbench obligation): valid holds until the beat is
    -- accepted. Data is stable by construction: stim_f(icnt_b) changes only
    -- on a transfer.
    a_b_valid_hold : assume always
        (rst_in = '0' and s_wait_b_q = '1') -> (s_valid_b_in = '1');

    -- Channel A defines the output function on every transfer (UF), or in
    -- the non-UF run A is checked against the reference.
    g_uf : if UF_MODE generate
        a_define : assume always a_def_ok = '1';
    end generate;

    g_nouf : if not UF_MODE generate
        a_define_chk : assert always a_def_ok = '1';
        -- The table suffices: the index does not wrap within the BMC horizon (a
        -- run that is too deep fails here instead of silently pruning paths).
        a_tab_range_chk : assert always
            (rst_in = '0') -> (icnt_a < TAB_N - 1);
    end generate;

    -- Channel B is checked against the same function at the symbolic beat
    -- index j (equivalent to checking every beat: if B's beat k is wrong, the
    -- solver picks j = k).
    a_match : assert always
        (armed = '1' and rst_in = '0' and m_xfer_b = '1' and ocnt_b = j) ->
        (m_re_b = uf_re_b and m_im_b = uf_im_b);
end;

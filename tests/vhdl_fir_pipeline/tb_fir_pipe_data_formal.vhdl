-- Property 1: DATA DOES NOT DEPEND ON CONTROL (pipelined FIR).
--
-- The same DUT (fir_complex_pipe) twice with different control sequences:
-- - A: reference channel at full rate (s_valid = '1', m_ready = '1' after
--   reset; assumption a_ref_rate). A DEFINES the output function out_f
--   (a_define).
-- - B: free s_valid and m_ready (AXI rules as assumptions on the side the
--   testbench drives). B is CHECKED against out_f (a_match) and the stability
--   of an m-side stall is checked (a_m_stable_b). In addition, bounded
--   progress of B (a_prog_m_b, a_prog_s_b): when m_ready has been up long
--   enough, a beat in flight comes out and a waiting input beat is accepted.
--
-- The input is an uninterpreted function stim_f(icnt) of the input beat
-- index, so both channels see the same logical sample sequence even if they
-- accept the beats on different cycles. The expected output is an
-- uninterpreted function out_f(ocnt) of the output beat index. Because out_f
-- is the same symbol for both, congruence forces beat k of B to equal beat k
-- of A.
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

use work.fir_complex_pipe_pkg.all;

entity tb_fir_pipe_data_formal is
    generic (
        TAPS    : positive := 5;
        WIDTH   : positive := 8;
        SKID    : boolean  := false;
        -- true:  out_f is a UF, and a_define (assume) ties it to the output
        --        of channel A.
        -- false: non-UF run: the DUT's marks are switched off (generic to
        --        the DUT, uf_disable), the stimulus is a free anyconst table
        --        and the expected output an interpreted FIR reference, so
        --        the same condition is CHECKED (a_define_chk, assert). As an
        --        assumption it would silently prune the paths on which the
        --        DUT deviates from the reference. sby sets the value
        --        (-gUF_MODE=...). The default false is the safe
        --        direction: a forgotten -g turns the condition into an
        --        assertion.
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

architecture formal of tb_fir_pipe_data_formal is
    constant OW : positive := out_width(TAPS, WIDTH);
    constant D  : positive := pipe_depth(TAPS);

    -- Bounds of the bounded progress of B, derived from the DUT structure:
    -- M_WAIT: how many consecutive cycles B's m_ready can be up without
    --   m_valid while beats are in flight (icnt_b /= ocnt_b).
    --   Both styles: the oldest beat is in the main slot of some stage i
    --   (skid: sk_v -> mn_v) and the stages downstream of it are empty, so it
    --   advances one stage per cycle regardless of m_ready, and in the output
    --   stage (i = D-1) m_valid is up. Worst case: the beat was just accepted
    --   (stage 0), m_valid rises D-1 cycles later. So at most D-1
    --   consecutive cycles; the bound is tight (test_prog_bound_tight).
    -- S_WAIT: how many consecutive cycles a waiting input beat of B
    --   (s_valid and not s_ready) can wait while m_ready is up.
    --   comb: s_ready = rdy(0) is combinationally up whenever m_ready is
    --   (rdy(i) = not mn_v(i) or rdy(i+1), rdy(D) = m_ready), so 0.
    --   skid: s_ready = not sk_v(0); while m_ready is up the output stage
    --   frees up every cycle, so sk_v(D-1) empties in 1 cycle, sk_v(D-2) in
    --   2 cycles, ..., sk_v(0) in D cycles, and an emptied skid slot does not
    --   fill again. So at most D consecutive cycles.
    constant M_WAIT : natural := D - 1;
    function s_wait_of(skid_style : boolean; depth : positive) return natural is
    begin
        if skid_style then
            return depth;
        end if;
        return 0;
    end function;
    constant S_WAIT : natural := s_wait_of(SKID, D);

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
    -- s-side wait (valid and not ready) of B on the previous cycle.
    signal s_wait_b_q           : std_logic := '0';
    -- m-side stall (valid and not ready) and data of B on the previous cycle.
    signal m_wait_b_q           : std_logic := '0';
    signal m_re_b_q, m_im_b_q   : signed(OW - 1 downto 0);
    -- Flags of the vacuity cover (B, after reset): on the s-side a bubble
    -- (s_valid = '0' after the first beat) and back pressure (s_valid and not
    -- s_ready), on the m-side back pressure (m_valid and not m_ready).
    signal b_s_idle             : std_logic := '0';
    signal b_s_wait             : std_logic := '0';
    signal b_m_wait             : std_logic := '0';
    -- Progress conditions (B) and counters of their consecutive cycles
    -- (saturating at D): prog_m_b = m_ready up, beats in flight, but m_valid
    -- low; prog_s_b = m_ready up and an input beat waiting.
    signal prog_m_b             : std_logic;
    signal prog_s_b             : std_logic;
    signal cnt_m_b              : natural range 0 to D := 0;
    signal cnt_s_b              : natural range 0 to D := 0;
    -- The a_define condition is written once; UF_MODE selects assume or assert.
    signal a_def_ok             : std_logic;

    -- Symbolic beat index: free initial value, stays constant (a_match).
    signal j                    : unsigned(15 downto 0);
    attribute anyconst : boolean;
    attribute anyconst of j : signal is true;

    attribute uf_instance : string;

    -- Free stimulus table of the non-UF comparison run (UF_MODE = false):
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

    -- FIR reference y[idx] = sum_k c(k) * x[idx-k], x[m] = table or 0 when m < 0;
    -- im = false: real part, true: imaginary part.
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

    prog_m_b <= '1' when rst_in = '0' and m_ready_b_in = '1' and m_valid_b = '0' and
                         icnt_b /= ocnt_b else '0';
    prog_s_b <= '1' when rst_in = '0' and m_ready_b_in = '1' and s_valid_b_in = '1' and
                         s_ready_b = '0' else '0';

    -- UF_MODE = true: stimulus and expected output as uninterpreted functions.
    g_uf_fun : if UF_MODE generate
        attribute uf_instance of u_stim_a : label is "stim_f";
        attribute uf_instance of u_stim_b : label is "stim_f";
        attribute uf_instance of u_out_a  : label is "out_f";
        attribute uf_instance of u_out_b  : label is "out_f";
    begin
        -- Stimulus: the same uninterpreted function for both, each channel's own index.
        u_stim_a : entity work.tb_fir_pipe_stim_formal
            generic map (
                WIDTH => WIDTH
            )
            port map (
                idx_in => icnt_a,
                re_out => s_re_a,
                im_out => s_im_a
            );

        u_stim_b : entity work.tb_fir_pipe_stim_formal
            generic map (
                WIDTH => WIDTH
            )
            port map (
                idx_in => icnt_b,
                re_out => s_re_b,
                im_out => s_im_b
            );

        -- Expected output: the same uninterpreted function for both.
        u_out_a : entity work.tb_fir_pipe_out_formal
            generic map (
                TAPS  => TAPS,
                WIDTH => WIDTH
            )
            port map (
                idx_in => ocnt_a,
                re_out => uf_re_a,
                im_out => uf_im_a
            );

        u_out_b : entity work.tb_fir_pipe_out_formal
            generic map (
                TAPS  => TAPS,
                WIDTH => WIDTH
            )
            port map (
                idx_in => ocnt_b,
                re_out => uf_re_b,
                im_out => uf_im_b
            );
    end generate;

    -- UF_MODE = false (non-UF comparison run): the stimulus is a free table
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

    a : entity work.fir_complex_pipe
        generic map (
            TAPS    => TAPS,
            WIDTH   => WIDTH,
            SKID    => SKID,
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

    b : entity work.fir_complex_pipe
        generic map (
            TAPS    => TAPS,
            WIDTH   => WIDTH,
            SKID    => SKID,
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
            first    <= '0';
            armed    <= not rst_in;
            m_re_b_q <= m_re_b;
            m_im_b_q <= m_im_b;
            if rst_in = '1' then
                icnt_a     <= (others => '0');
                icnt_b     <= (others => '0');
                ocnt_a     <= (others => '0');
                ocnt_b     <= (others => '0');
                s_wait_b_q <= '0';
                m_wait_b_q <= '0';
                b_s_idle   <= '0';
                b_s_wait   <= '0';
                b_m_wait   <= '0';
                cnt_m_b    <= 0;
                cnt_s_b    <= 0;
            else
                if prog_m_b = '0' then
                    cnt_m_b <= 0;
                elsif cnt_m_b < D then
                    cnt_m_b <= cnt_m_b + 1;
                end if;
                if prog_s_b = '0' then
                    cnt_s_b <= 0;
                elsif cnt_s_b < D then
                    cnt_s_b <= cnt_s_b + 1;
                end if;
                if s_xfer_a = '1' then icnt_a <= icnt_a + 1; end if;
                if s_xfer_b = '1' then icnt_b <= icnt_b + 1; end if;
                if m_xfer_a = '1' then ocnt_a <= ocnt_a + 1; end if;
                if m_xfer_b = '1' then ocnt_b <= ocnt_b + 1; end if;
                s_wait_b_q <= s_valid_b_in and not s_ready_b;
                m_wait_b_q <= m_valid_b and not m_ready_b_in;
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

    -- Initial reset: without it the uninitialised state of the DUT could
    -- produce phantom beats.
    a_init_reset : assume always
        (first = '1') -> (rst_in = '1');

    -- A is the reference channel: full rate, so that it ties out_f at every
    -- index that B can reach. Without this out_f stays free at the indices A
    -- did not produce, and a_match fails trivially.
    a_ref_rate : assume always
        (rst_in = '0') -> (s_valid_a_in = '1' and m_ready_a_in = '1');

    -- Modelling bound: the index counters (16 bits) do not wrap (as in
    -- tests/vhdl_fir_independence). A transfers a beat on every cycle, so this
    -- limits the analysis to the first 2^16-1 cycles after each reset; B is
    -- always behind A. At BMC depths the bound restricts nothing; in
    -- k-induction it excludes the wrapped states.
    a_no_wrap : assume always
        (rst_in = '0') -> (icnt_a /= x"FFFF");

    -- AXI s-side (obligation of the testbench): valid stays up until the beat
    -- is accepted. Data is stable by construction: stim_f(icnt_b) changes only
    -- on a transfer.
    a_b_valid_hold : assume always
        (rst_in = '0' and s_wait_b_q = '1') -> (s_valid_b_in = '1');

    -- Channel A ties the output function on every transfer (UF), or in the
    -- non-UF run A is checked against the reference.
    g_uf : if UF_MODE generate
        a_define : assume always a_def_ok = '1';
    end generate;

    g_nouf : if not UF_MODE generate
        a_define_chk : assert always a_def_ok = '1';
        -- The table is large enough: the index does not wrap within the BMC
        -- horizon (a run that is too deep fails here instead of silently
        -- pruning paths).
        a_tab_range_chk : assert always
            (rst_in = '0') -> (icnt_a < TAB_N - 1);
    end generate;

    -- Channel B is checked against the same function at the symbolic beat
    -- index j (equivalent to checking every beat: if beat k of B is wrong,
    -- the solver picks j = k).
    a_match : assert always
        (armed = '1' and rst_in = '0' and m_xfer_b = '1' and ocnt_b = j) ->
        (m_re_b = uf_re_b and m_im_b = uf_im_b);

    -- AXI m-side (obligation of the DUT): a stalled beat (m_valid and not
    -- m_ready) stays on the next cycle, and its data does not change. a_match
    -- does not see this: it looks at the data only on a transfer cycle.
    a_m_stable_b : assert always
        (armed = '1' and rst_in = '0' and m_wait_b_q = '1') ->
        (m_valid_b = '1' and m_re_b = m_re_b_q and m_im_b = m_im_b_q);

    -- Bounded progress (obligation of the DUT, not an assumption): a_match
    -- checks only delivered beats and a_m_stable_b does not require a
    -- transfer, so without these a deadlocked DUT or one that loses beats
    -- would pass. The condition includes m_ready, so no fairness assumption
    -- is needed: the testbench requires nothing from the environment, it only
    -- bounds how long the DUT may fail to make progress on cycles on which
    -- the environment is ready.
    -- m-side: m_ready up and beats in flight -> m_valid rises after at most
    -- M_WAIT consecutive cycles.
    a_prog_m_b : assert always
        (prog_m_b = '1') -> (cnt_m_b < M_WAIT);

    -- s-side: m_ready up and an input beat waiting -> the beat is accepted
    -- after at most S_WAIT consecutive cycles (comb: immediately).
    a_prog_s_b : assert always
        (prog_s_b = '1') -> (cnt_s_b < S_WAIT);
end;

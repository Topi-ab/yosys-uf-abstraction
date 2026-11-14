library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

-- Property: the value of the output data does not depend on the control sequence.
-- The same DUT is run twice with different valid sequences.
--
-- The output is modelled as an uninterpreted function of the output beat index.
-- A is the reference channel that DEFINES this function (assume); B is CHECKED
-- against it (assert). Since the function is the same symbol for both,
-- congruence forces the channels to agree per index -- without either channel's
-- beat having to wait for the other.
--
-- The input is likewise a function of the beat index, so both instances see
-- the same logical sequence even if they accept beats on different clock cycles.
--
-- When valid is '0', the DUT's data_in is a free input (data_a_idle_in /
-- data_b_idle_in, separate for each instance): data is defined only on a
-- valid cycle. Without this, stim_f(icnt) would stay constant between beats,
-- and a DUT that reads the data on the cycle after valid would go unnoticed
-- (mutation M1_skip_s1 in the test file).
entity tb_dsp_formal is
    generic (
        -- true:  out_f is a UF, and a_define (assume) ties it to channel A's output.
        -- false: non-UF run: all marks (testbench, vunit and, through the
        --        DUT generic, the DUT) are switched off (uf_disable = not UF_MODE),
        --        out_f is an interpreted architecture, so the same condition is
        --        CHECKED (a_define_chk, assert).
        --        As an assume it would silently prune the paths on which the DUT
        --        differs from out_f (vacuous PASS). sby sets the value
        --        (-gUF_MODE=...). The default false is the safe direction: a
        --        forgotten -g turns the condition into an assert.
        UF_MODE : boolean := false
    );
    port (
        clk_in         : in std_logic;
        rst_in         : in std_logic;
        valid_a_in     : in std_logic;
        valid_b_in     : in std_logic;
        data_a_idle_in : in signed(15 downto 0);
        data_b_idle_in : in signed(15 downto 0)
    );
end;

architecture formal of tb_dsp_formal is
    signal icnt_a, icnt_b     : unsigned(15 downto 0) := (others => '0');
    signal ocnt_a, ocnt_b     : unsigned(15 downto 0) := (others => '0');
    signal a_feed, b_feed     : signed(15 downto 0);
    signal a_data, b_data     : signed(15 downto 0);
    signal a_res, b_res       : signed(15 downto 0);
    signal yvalid_a, yvalid_b : std_logic;
    signal ufout_a, ufout_b   : signed(15 downto 0);
    signal armed              : std_logic := '0';
    signal first              : std_logic := '1';
    -- The a_define condition is written once; UF_MODE selects assume or assert.
    signal a_def_ok           : std_logic;

    -- Symbolic beat index: free initial value, stays constant (a_match).
    signal j                  : unsigned(15 downto 0);
    attribute anyconst : boolean;
    attribute anyconst of j : signal is true;

    attribute uf_instance : string;
    attribute uf_instance of u_stim_a : label is "stim_f";
    attribute uf_instance of u_stim_b : label is "stim_f";
    attribute uf_instance of u_out_a  : label is "out_f";
    attribute uf_instance of u_out_b  : label is "out_f";
    -- UF_MODE = false: the marks are ignored, the boxes are exported interpreted.
    attribute uf_disable : boolean;
    attribute uf_disable of u_stim_a : label is not UF_MODE;
    attribute uf_disable of u_stim_b : label is not UF_MODE;
    attribute uf_disable of u_out_a  : label is not UF_MODE;
    attribute uf_disable of u_out_b  : label is not UF_MODE;

begin
    -- Stimulus: the same uninterpreted function for both, with different indices.
    u_stim_a : entity work.tb_stim_formal
        port map (
            idx_in   => signed(icnt_a),
            data_out => a_feed
        );

    u_stim_b : entity work.tb_stim_formal
        port map (
            idx_in   => signed(icnt_b),
            data_out => b_feed
        );

    -- Expected output: the same uninterpreted function for both, with different indices.
    u_out_a : entity work.tb_out_formal
        port map (
            idx_in   => signed(ocnt_a),
            data_out => ufout_a
        );

    u_out_b : entity work.tb_out_formal
        port map (
            idx_in   => signed(ocnt_b),
            data_out => ufout_b
        );

    -- Data is stim_f(icnt) only on a valid cycle, free otherwise.
    a_data <= a_feed when valid_a_in = '1' else data_a_idle_in;
    b_data <= b_feed when valid_b_in = '1' else data_b_idle_in;

    -- The same DUT twice, with different control sequences.
    a : entity work.dsp
        generic map (
            UF_MODE => UF_MODE
        )
        port map (
            clk_in    => clk_in,
            rst_in    => rst_in,
            valid_in  => valid_a_in,
            data_in   => a_data,
            valid_out => yvalid_a,
            data_out  => a_res
        );

    b : entity work.dsp
        generic map (
            UF_MODE => UF_MODE
        )
        port map (
            clk_in    => clk_in,
            rst_in    => rst_in,
            valid_in  => valid_b_in,
            data_in   => b_data,
            valid_out => yvalid_b,
            data_out  => b_res
        );

    process (clk_in) is
    begin
        if rising_edge(clk_in) then
            first <= '0';
            armed <= not rst_in;
            if rst_in = '1' then
                icnt_a <= (others => '0');
                icnt_b <= (others => '0');
                ocnt_a <= (others => '0');
                ocnt_b <= (others => '0');
            else
                -- Input beats: the testbench itself knows when a beat is accepted.
                if valid_a_in = '1' then icnt_a <= icnt_a + 1; end if;
                if valid_b_in = '1' then icnt_b <= icnt_b + 1; end if;

                -- Output beats.
                if yvalid_a = '1' then ocnt_a <= ocnt_a + 1; end if;
                if yvalid_b = '1' then ocnt_b <= ocnt_b + 1; end if;
            end if;
        end if;
    end process;

    default clock is rising_edge(clk_in);

    -- Initial reset: without this, the DUT's uninitialized valid_out could produce
    -- a phantom beat in the formal initial state and corrupt the output counters.
    a_init_reset : assume always
        (first = '1') -> (rst_in = '1');

    -- A is the reference channel: it runs at full rate so that it defines the
    -- output function at every index that B can reach.
    -- Without this, out_f stays unconstrained at indices that A did not produce,
    -- and B's assert fails trivially.
    a_ref_rate : assume always
        (rst_in = '0') -> (valid_a_in = '1');

    -- Channel A's output = out_f(ocnt_a) on every checked beat.
    a_def_ok <= '0' when armed = '1' and rst_in = '0' and yvalid_a = '1' and a_res /= ufout_a else
                '1';

    -- UF mode: channel A defines the output function.
    g_uf : if UF_MODE generate
        a_define : assume always a_def_ok = '1';
    end generate;

    -- Non-UF mode: out_f is interpreted, so the condition is checked.
    g_nouf : if not UF_MODE generate
        a_define_chk : assert always a_def_ok = '1';
    end generate;

    -- Channel B is checked against the same function, at the symbolic beat
    -- index j. This is equivalent to checking every beat: j is a free
    -- constant, so if B's beat k is wrong, the solver finds a counterexample
    -- by choosing j = k. Restricting the check to one index makes the
    -- assertion provable by k-induction (helper invariants: tb_dsp_formal_inv.psl).
    a_match : assert always
        (armed = '1' and rst_in = '0' and yvalid_b = '1' and ocnt_b = j) -> (b_res = ufout_b);
end;

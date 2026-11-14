library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

-- Claim: the value of the output data does not depend on the control sequence.
-- The same DUT is run twice with different valid sequences.
--
-- Same testbench as tests/vhdl_control_independence_setattr, but the data
-- width is the generic WIDTH (sby: ghdl -gWIDTH=..). The counters and the
-- symbolic index j stay 16 bits wide. Both prove tasks (uf_prove.sby) use this
-- testbench, vunit and assertion as they are; the only difference is the DUT
-- $mul (prove_uf: the UF mulw, prove_nouf: an interpreted multiplication).
--
-- The output is modelled as an uninterpreted function of the output beat index.
-- A is the reference channel that BINDS this function (assume); B is CHECKED
-- against it (assert). Since the function is the same symbol for both,
-- congruence forces the channels to agree per index -- without either channel's
-- beat having to wait for the other.
--
-- The input is likewise a function of the beat index, so both instances see
-- the same logical sequence even if they accept beats on different cycles.
--
-- When valid is '0', the DUT's data_in is a free input (data_a_idle_in /
-- data_b_idle_in, separate for each instance): the data is defined only on a
-- valid cycle. Without this, stim_f(icnt) would stay constant between beats,
-- and a DUT that reads the data on the cycle after valid would go unnoticed.
entity tb_dsp_formal is
    generic (
        WIDTH : positive := 8
    );
    port (
        clk_in     : in std_logic;
        rst_in     : in std_logic;
        valid_a_in     : in std_logic;
        valid_b_in     : in std_logic;
        data_a_idle_in : in signed(WIDTH - 1 downto 0);
        data_b_idle_in : in signed(WIDTH - 1 downto 0)
    );
end;

architecture formal of tb_dsp_formal is
    signal icnt_a, icnt_b     : unsigned(15 downto 0) := (others => '0');
    signal ocnt_a, ocnt_b     : unsigned(15 downto 0) := (others => '0');
    signal a_feed, b_feed     : signed(WIDTH - 1 downto 0);
    signal a_data, b_data     : signed(WIDTH - 1 downto 0);
    signal a_res, b_res       : signed(WIDTH - 1 downto 0);
    signal yvalid_a, yvalid_b : std_logic;
    signal ufout_a, ufout_b   : signed(WIDTH - 1 downto 0);
    signal armed              : std_logic := '0';
    signal first              : std_logic := '1';

    -- Symbolic beat index: free initial value, stays constant (a_match).
    signal j                  : unsigned(15 downto 0);
    attribute anyconst : boolean;
    attribute anyconst of j : signal is true;

    -- The testbench's own UFs are marked here; the DUT's internal datapath is
    -- not a VHDL object (it is a $mul cell created from an expression), so it
    -- has to be abstracted in the sby script.
    attribute uf_instance : string;
    attribute uf_instance of u_stim_a : label is "stim_f";
    attribute uf_instance of u_stim_b : label is "stim_f";
    attribute uf_instance of u_out_a  : label is "out_f";
    attribute uf_instance of u_out_b  : label is "out_f";
begin
    -- Stimulus: the same uninterpreted function for both, with different indices.
    u_stim_a : entity work.tb_stim_formal
        generic map (
            WIDTH => WIDTH
        )
        port map (
            idx_in   => signed(icnt_a),
            data_out => a_feed
        );

    u_stim_b : entity work.tb_stim_formal
        generic map (
            WIDTH => WIDTH
        )
        port map (
            idx_in   => signed(icnt_b),
            data_out => b_feed
        );

    -- Expected output: the same uninterpreted function for both, with different indices.
    u_out_a : entity work.tb_out_formal
        generic map (
            WIDTH => WIDTH
        )
        port map (
            idx_in   => signed(ocnt_a),
            data_out => ufout_a
        );

    u_out_b : entity work.tb_out_formal
        generic map (
            WIDTH => WIDTH
        )
        port map (
            idx_in   => signed(ocnt_b),
            data_out => ufout_b
        );

    -- The data is stim_f(icnt) only on a valid cycle, otherwise free.
    a_data <= a_feed when valid_a_in = '1' else data_a_idle_in;
    b_data <= b_feed when valid_b_in = '1' else data_b_idle_in;

    -- The same DUT twice, with different control sequences.
    a : entity work.dsp
        generic map (
            WIDTH => WIDTH
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
            WIDTH => WIDTH
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

    -- Initial reset: without it, the DUT's uninitialized valid_out could produce
    -- a phantom beat in the formal initial state and corrupt the output counters.
    a_init_reset : assume always
        (first = '1') -> (rst_in = '1');

    -- A is the reference channel: it runs at full rate so that it binds the
    -- output function at every index that B can reach.
    -- Without this, out_f stays free at indices that A did not produce, and
    -- B's assert fails trivially.
    a_ref_rate : assume always
        (rst_in = '0') -> (valid_a_in = '1');

    -- Channel A binds the output function.
    a_define : assume always
        (armed = '1' and rst_in = '0' and yvalid_a = '1') -> (a_res = ufout_a);

    -- Channel B is checked against the same function, at the symbolic beat
    -- index j. This is equivalent to checking every beat: j is a free
    -- constant, so if beat k of B is wrong, the solver finds a counterexample
    -- by choosing j = k. Restricting the check to one index makes the claim
    -- provable by k-induction (helper invariants: tb_dsp_formal_inv.psl).
    a_match : assert always
        (armed = '1' and rst_in = '0' and yvalid_b = '1' and ocnt_b = j) -> (b_res = ufout_b);
end;

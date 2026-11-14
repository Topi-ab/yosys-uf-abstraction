-- Wolper checker (data independence): the FIFO with two symbolic values.
--
-- Three anyconst values: the tracked beat index k (32 bits, the same width as
-- icnt) and two data values a and b. On a valid cycle the input data is a
-- when the index of the beat being input is icnt = k, and b otherwise. On
-- every output transfer the expected data is a when ocnt = k, and b
-- otherwise:
--   - beat k comes out exactly at position k (not lost, not moved: order),
--   - a does not come out at any other position (not duplicated),
--   - the other beats are b (no corruption; a copy or garbage shows when
--     a /= b).
-- Since k, a and b are symbolic, the solver picks the most interesting beat
-- and value pair. The checker is a special case of the UF checker
-- (tb_axis_fifo_uf_formal): stim(i) = (a when i = k, otherwise b), i.e. a
-- two-valued stim function.
-- The assumption a /= b is not needed: runs with a = b are just weaker cases
-- and do not produce false counterexamples.
--
-- When s_valid_in = '0', s_data is the free input s_data_idle_in (as in the
-- UF testbench; without it the stale_capture mutation would go unnoticed).
-- The testbench has no memory: the checker state is three constants and the
-- counters of the control checker.
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity tb_axis_fifo_wolper_formal is
    generic (
        DEPTH : positive := 4;
        WIDTH : positive := 8
    );
    port (
        clk_in         : in std_logic;
        rst_in         : in std_logic;
        s_valid_in     : in std_logic;
        s_data_idle_in : in std_logic_vector(WIDTH - 1 downto 0);
        m_ready_in     : in std_logic
    );
end;

architecture formal of tb_axis_fifo_wolper_formal is
    signal icnt     : unsigned(31 downto 0);
    signal ocnt     : unsigned(31 downto 0);
    signal was_full : std_logic;
    signal s_ready  : std_logic;
    signal s_data   : std_logic_vector(WIDTH - 1 downto 0);
    signal m_valid  : std_logic;
    signal m_data   : std_logic_vector(WIDTH - 1 downto 0);
    signal exp_data : std_logic_vector(WIDTH - 1 downto 0);

    -- Tracked beat and two data values: constant for the whole run (anyconst).
    signal k : unsigned(31 downto 0);
    signal a : std_logic_vector(WIDTH - 1 downto 0);
    signal b : std_logic_vector(WIDTH - 1 downto 0);

    attribute anyconst : boolean;
    attribute anyconst of k : signal is true;
    attribute anyconst of a : signal is true;
    attribute anyconst of b : signal is true;
begin
    s_data   <= s_data_idle_in when s_valid_in = '0' else
                a when icnt = k else
                b;
    exp_data <= a when ocnt = k else b;

    dut : entity work.axis_fifo
        generic map (
            DEPTH => DEPTH,
            WIDTH => WIDTH
        )
        port map (
            clk_in      => clk_in,
            rst_in      => rst_in,
            s_valid_in  => s_valid_in,
            s_ready_out => s_ready,
            s_data_in   => s_data,
            m_valid_out => m_valid,
            m_ready_in  => m_ready_in,
            m_data_out  => m_data
        );

    ctrl : entity work.tb_axis_ctrl_formal
        generic map (
            DEPTH => DEPTH,
            WIDTH => WIDTH
        )
        port map (
            clk_in       => clk_in,
            rst_in       => rst_in,
            s_valid_in   => s_valid_in,
            s_ready_in   => s_ready,
            m_valid_in   => m_valid,
            m_ready_in   => m_ready_in,
            m_data_in    => m_data,
            icnt_out     => icnt,
            ocnt_out     => ocnt,
            was_full_out => was_full
        );

    default clock is rising_edge(clk_in);

    -- Data check on every output transfer: a exactly on beat k, otherwise b.
    a_wolper_match : assert always
        (rst_in = '0' and m_valid = '1' and m_ready_in = '1') -> (m_data = exp_data);
end;

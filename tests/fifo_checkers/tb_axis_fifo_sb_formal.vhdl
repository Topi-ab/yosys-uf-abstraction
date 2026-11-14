-- Scoreboard checker: tb_stream_scoreboard_formal (one symbolic sequence
-- number, no shadow queue).
--
-- s_data_in is free (top-level input, anyseq). Stream a = accepted input beats
-- (s_valid and s_ready), stream b = accepted output beats (m_valid and
-- m_ready): the k-th accepted input must be the k-th accepted output. The
-- checker adds no register delay and contains no DEPTH-sized structure. The
-- control assumptions and assertions are the same as in the UF testbench
-- (tb_axis_ctrl_formal).
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity tb_axis_fifo_sb_formal is
    generic (
        DEPTH : positive := 4;
        WIDTH : positive := 8
    );
    port (
        clk_in     : in std_logic;
        rst_in     : in std_logic;
        s_valid_in : in std_logic;
        s_data_in  : in std_logic_vector(WIDTH - 1 downto 0);
        m_ready_in : in std_logic
    );
end;

architecture formal of tb_axis_fifo_sb_formal is
    signal icnt     : unsigned(31 downto 0);
    signal ocnt     : unsigned(31 downto 0);
    signal was_full : std_logic;
    signal s_ready  : std_logic;
    signal m_valid  : std_logic;
    signal m_data   : std_logic_vector(WIDTH - 1 downto 0);
    signal s_xfer   : std_logic;
    signal m_xfer   : std_logic;
begin
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
            s_data_in   => s_data_in,
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

    s_xfer <= s_valid_in and s_ready;
    m_xfer <= m_valid and m_ready_in;

    sb : entity work.tb_stream_scoreboard_formal
        generic map (
            DATA_BITS => WIDTH,
            PTR_BITS  => 32
        )
        port map (
            clk_in     => clk_in,
            rst_in     => rst_in,
            a_valid_in => s_xfer,
            a_data_in  => s_data_in,
            b_valid_in => m_xfer,
            b_data_in  => m_data
        );

    -- For the testbench's own PSL statements (vunit, test covers).
    default clock is rising_edge(clk_in);
end;

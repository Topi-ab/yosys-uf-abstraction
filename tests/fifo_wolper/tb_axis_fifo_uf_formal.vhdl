-- UF checker: the FIFO without a scoreboard.
--
-- The input is an uninterpreted function of the beat index: s_data = stim(icnt).
-- The FIFO does not transform the data, so every outgoing beat must be
-- m_data = stim(ocnt). Since stim is the same symbol in both instances, the
-- assertion holds for every interpretation of stim only if the FIFO returns
-- the beats without losing, duplicating or reordering them. The testbench
-- does not model any memory at all.
--
-- When s_valid_in = '0', s_data is the free input s_data_idle_in: AXI does not
-- constrain the data without valid, and without it stim(icnt) would stay
-- constant for the whole gap between transfers, so a DUT that stores the data
-- of the wrong (non-valid) cycle would go unnoticed (mutation stale_capture in
-- the tests).
-- When s_valid_in = '1', the data is stim(icnt), which is stable until the
-- transfer.
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity tb_axis_fifo_uf_formal is
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

architecture formal of tb_axis_fifo_uf_formal is
    signal icnt     : unsigned(31 downto 0);
    signal ocnt     : unsigned(31 downto 0);
    signal was_full : std_logic;
    signal s_ready  : std_logic;
    signal s_stim   : std_logic_vector(WIDTH - 1 downto 0);
    signal s_data   : std_logic_vector(WIDTH - 1 downto 0);
    signal m_valid  : std_logic;
    signal m_data   : std_logic_vector(WIDTH - 1 downto 0);
    signal exp_data : std_logic_vector(WIDTH - 1 downto 0);

    attribute uf_instance : string;
    attribute uf_instance of u_stim_in  : label is "stim_f";
    attribute uf_instance of u_stim_out : label is "stim_f";
begin
    -- Input data on a valid cycle: stim(icnt).
    u_stim_in : entity work.tb_axis_stim_formal
        generic map (
            WIDTH => WIDTH
        )
        port map (
            idx_in   => icnt,
            data_out => s_stim
        );

    -- Expected data: the same function at the index of the outgoing beat.
    u_stim_out : entity work.tb_axis_stim_formal
        generic map (
            WIDTH => WIDTH
        )
        port map (
            idx_in   => ocnt,
            data_out => exp_data
        );

    s_data <= s_stim when s_valid_in = '1' else s_data_idle_in;

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

    -- Data check on every output transfer.
    a_uf_match : assert always
        (rst_in = '0' and m_valid = '1' and m_ready_in = '1') -> (m_data = exp_data);
end;

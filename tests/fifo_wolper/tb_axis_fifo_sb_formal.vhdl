-- Traditional scoreboard checker.
--
-- s_data_in is free (top-level input, anyseq). A shadow queue (DEPTH slots,
-- its own read and write pointers) stores every accepted beat; on an output
-- transfer m_data is compared with the head of the shadow queue. The control
-- assumptions and assertions are the same as in the UF testbench
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
    type sb_t is array (0 to DEPTH - 1) of std_logic_vector(WIDTH - 1 downto 0);
    signal sb       : sb_t;
    signal sb_rd    : natural range 0 to DEPTH - 1;
    signal sb_wr    : natural range 0 to DEPTH - 1;
    signal sb_head  : std_logic_vector(WIDTH - 1 downto 0);
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

    s_xfer  <= s_valid_in and s_ready;
    m_xfer  <= m_valid and m_ready_in;
    sb_head <= sb(sb_rd);

    -- Shadow queue. Overflow need not be handled: a_occ_max and a_no_overflow
    -- fail before the shadow queue could overwrite an unread slot.
    process (clk_in) is
    begin
        if rising_edge(clk_in) then
            if s_xfer = '1' then
                sb(sb_wr) <= s_data_in;
            end if;
            if rst_in = '1' then
                sb_rd <= 0;
                sb_wr <= 0;
            else
                if s_xfer = '1' then
                    if sb_wr = DEPTH - 1 then
                        sb_wr <= 0;
                    else
                        sb_wr <= sb_wr + 1;
                    end if;
                end if;
                if m_xfer = '1' then
                    if sb_rd = DEPTH - 1 then
                        sb_rd <= 0;
                    else
                        sb_rd <= sb_rd + 1;
                    end if;
                end if;
            end if;
        end if;
    end process;

    default clock is rising_edge(clk_in);

    -- Data check on every output transfer.
    a_sb_match : assert always
        (rst_in = '0' and m_xfer = '1') -> (m_data = sb_head);
end;

-- Shared control checker for both testbenches (UF and scoreboard): beat
-- counters, the initial-reset assumption and the control assertions. Each
-- testbench checks the data separately.
--
-- The counters are 32 bits wide. Wraparound is harmless for BMC: a counter
-- grows by at most one per cycle and the BMC depth is tens of cycles, so the
-- value cannot wrap within the checked horizon (2^32 >> depth). In addition,
-- the fill level occ = icnt - ocnt is computed with modular arithmetic, so it
-- would stay correct even after a wrap; as a UF index, 32 bits is well above
-- log2(DEPTH).
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity tb_axis_ctrl_formal is
    generic (
        DEPTH : positive := 4;
        WIDTH : positive := 8
    );
    port (
        clk_in       : in  std_logic;
        rst_in       : in  std_logic;
        s_valid_in   : in  std_logic;
        s_ready_in   : in  std_logic;
        m_valid_in   : in  std_logic;
        m_ready_in   : in  std_logic;
        m_data_in    : in  std_logic_vector(WIDTH - 1 downto 0);
        icnt_out     : out unsigned(31 downto 0);
        ocnt_out     : out unsigned(31 downto 0);
        was_full_out : out std_logic
    );
end;

architecture formal of tb_axis_ctrl_formal is
    signal icnt     : unsigned(31 downto 0) := (others => '0');
    signal ocnt     : unsigned(31 downto 0) := (others => '0');
    signal occ      : unsigned(31 downto 0);
    signal s_xfer   : std_logic;
    signal m_xfer   : std_logic;
    signal first    : std_logic := '1';
    signal was_full : std_logic := '0';
    -- Previous cycle of the m channel, for the AXI stability assertions.
    signal m_hold_q : std_logic := '0';
    signal m_data_q : std_logic_vector(WIDTH - 1 downto 0);
begin
    s_xfer <= s_valid_in and s_ready_in;
    m_xfer <= m_valid_in and m_ready_in;
    occ    <= icnt - ocnt;

    icnt_out     <= icnt;
    ocnt_out     <= ocnt;
    was_full_out <= was_full;

    process (clk_in) is
    begin
        if rising_edge(clk_in) then
            first    <= '0';
            m_data_q <= m_data_in;
            if rst_in = '1' then
                icnt     <= (others => '0');
                ocnt     <= (others => '0');
                was_full <= '0';
                m_hold_q <= '0';
            else
                if s_xfer = '1' then
                    icnt <= icnt + 1;
                end if;
                if m_xfer = '1' then
                    ocnt <= ocnt + 1;
                end if;
                if occ = DEPTH then
                    was_full <= '1';
                end if;
                m_hold_q <= m_valid_in and not m_ready_in;
            end if;
        end if;
    end process;

    default clock is rising_edge(clk_in);

    -- The only assumption. Initial reset: without it the uninitialized DUT
    -- state (count, rd, wr) could produce phantom beats in the formal initial
    -- state. Reset is not constrained otherwise. The s side needs NO AXI
    -- assumptions (valid held until accepted, data stable): the FIFO must work
    -- with any valid pattern, and the data check only covers accepted beats.
    -- In the UF testbench s_data on a valid cycle is stim(icnt), which changes
    -- only on a transfer (stable by construction), and is free without valid.
    -- m_ready_in is free as well.
    a_init_reset : assume always
        (first = '1') -> (rst_in = '1');

    -- The fill level never exceeds the depth.
    a_occ_max : assert always
        (rst_in = '0') -> (occ <= DEPTH);

    -- Underflow: an output transfer only when the FIFO holds data (m_valid is
    -- not raised while empty).
    a_no_underflow : assert always
        (rst_in = '0' and m_valid_in = '1') -> (occ /= 0);

    -- Overflow: s_ready is low when the FIFO is full.
    a_no_overflow : assert always
        (rst_in = '0' and occ = DEPTH) -> (s_ready_in = '0');

    -- The reverse directions (DUT specification: s_ready = not full,
    -- m_valid = not empty). Without these, s_ready or m_valid stuck low would
    -- pass all other assertions: the data assertions only cover transfers
    -- that actually happen.
    a_ready_not_full : assert always
        (rst_in = '0' and occ < DEPTH) -> (s_ready_in = '1');

    a_valid_not_empty : assert always
        (rst_in = '0' and occ /= 0) -> (m_valid_in = '1');

    -- AXI master side (DUT obligation): valid is held and data is stable
    -- until the beat is accepted.
    a_m_valid_hold : assert always
        (rst_in = '0' and m_hold_q = '1') -> (m_valid_in = '1');

    a_m_data_stable : assert always
        (rst_in = '0' and m_hold_q = '1') -> (m_data_in = m_data_q);
end;

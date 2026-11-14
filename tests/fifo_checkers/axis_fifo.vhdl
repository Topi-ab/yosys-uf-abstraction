-- AXI Stream FIFO.
--
-- DEPTH: any integer >= 1 (no power of two required); the pointers wrap
-- modulo DEPTH and the fill level is kept in a separate counter
-- (count, 0..DEPTH).
-- WIDTH: data width in bits.
--
-- Semantics: a transfer happens when valid and ready are both '1'.
-- s_ready_out = '1' exactly when the FIFO is not full, m_valid_out = '1'
-- exactly when the FIFO is not empty. Both depend only on the register count,
-- so there are no combinational ready->valid or ready->ready paths (in a full
-- FIFO a simultaneous read does not raise s_ready_out in the same cycle).
-- m_data_out is read directly from memory (first-word fall-through).
-- Reset is synchronous and active high; the memory is not cleared.
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity axis_fifo is
    generic (
        DEPTH : positive := 4;
        WIDTH : positive := 8
    );
    port (
        clk_in      : in  std_logic;
        rst_in      : in  std_logic;
        s_valid_in  : in  std_logic;
        s_ready_out : out std_logic;
        s_data_in   : in  std_logic_vector(WIDTH - 1 downto 0);
        m_valid_out : out std_logic;
        m_ready_in  : in  std_logic;
        m_data_out  : out std_logic_vector(WIDTH - 1 downto 0)
    );
end;

architecture rtl of axis_fifo is
    type mem_t is array (0 to DEPTH - 1) of std_logic_vector(WIDTH - 1 downto 0);
    signal mem     : mem_t;
    signal rd      : natural range 0 to DEPTH - 1;
    signal wr      : natural range 0 to DEPTH - 1;
    signal count   : natural range 0 to DEPTH;
    signal s_ready : std_logic;
    signal m_valid : std_logic;
    signal push    : std_logic;
    signal pop     : std_logic;
begin
    s_ready <= '1' when count < DEPTH else '0';
    m_valid <= '1' when count > 0 else '0';
    push    <= s_valid_in and s_ready;
    pop     <= m_valid and m_ready_in;

    s_ready_out <= s_ready;
    m_valid_out <= m_valid;
    m_data_out  <= mem(rd);

    process (clk_in) is
    begin
        if rising_edge(clk_in) then
            if push = '1' then
                mem(wr) <= s_data_in;
            end if;
            if rst_in = '1' then
                rd    <= 0;
                wr    <= 0;
                count <= 0;
            else
                if push = '1' then
                    if wr = DEPTH - 1 then
                        wr <= 0;
                    else
                        wr <= wr + 1;
                    end if;
                end if;
                if pop = '1' then
                    if rd = DEPTH - 1 then
                        rd <= 0;
                    else
                        rd <= rd + 1;
                    end if;
                end if;
                if push = '1' and pop = '0' then
                    count <= count + 1;
                elsif push = '0' and pop = '1' then
                    count <= count - 1;
                end if;
            end if;
        end if;
    end process;
end;

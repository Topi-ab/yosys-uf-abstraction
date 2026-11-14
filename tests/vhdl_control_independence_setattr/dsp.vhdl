library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

-- One DUT. The testbench instantiates it twice and drives the instances
-- with different control sequences.
-- No verification-related code or structure: the datapath is written
-- inline, not factored out into an entity of its own.
entity dsp is
    port (
        clk_in    : in  std_logic;
        rst_in    : in  std_logic;
        valid_in  : in  std_logic;
        data_in   : in  signed(15 downto 0);
        valid_out : out std_logic;
        data_out  : out signed(15 downto 0)
    );
end;

architecture rtl of dsp is
    signal s1    : signed(15 downto 0);
    signal v1    : std_logic := '0';
begin

    -- Two-stage pipeline: valid_in -> s1 -> data_out
    process (clk_in) is
    begin
        if rising_edge(clk_in) then
            if rst_in = '1' then
                v1        <= '0';
                valid_out <= '0';
            else
                v1        <= valid_in;
                valid_out <= v1;
                if valid_in = '1' then
                    s1 <= resize(data_in * data_in, 16);
                end if;
                if v1 = '1' then
                    data_out <= s1;
                end if;
            end if;
        end if;
    end process;
end;

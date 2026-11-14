library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

-- Same DUT as tests/vhdl_control_independence_setattr/dsp.vhdl, but the
-- datapath width is the generic WIDTH. The multiplication data_in * data_in is
-- the only expensive operation in the DUT; its cost for the solver grows with
-- the width. No verification code or structure: the multiplication is
-- abstracted in the sby script (setattr on the DUT $mul cell), not here.
entity dsp is
    generic (
        WIDTH : positive := 8
    );
    port (
        clk_in    : in  std_logic;
        rst_in    : in  std_logic;
        valid_in  : in  std_logic;
        data_in   : in  signed(WIDTH - 1 downto 0);
        valid_out : out std_logic;
        data_out  : out signed(WIDTH - 1 downto 0)
    );
end;

architecture rtl of dsp is
    signal s1 : signed(WIDTH - 1 downto 0);
    signal v1 : std_logic := '0';
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
                    s1 <= resize(data_in * data_in, WIDTH);
                end if;
                if v1 = '1' then
                    data_out <= s1;
                end if;
            end if;
        end if;
    end process;
end;

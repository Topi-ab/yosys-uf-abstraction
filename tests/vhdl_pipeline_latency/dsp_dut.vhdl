-- DUT: two signed inputs, one signed output, one clock cycle of latency.
-- Surrounded by control signals and state; the output data VALUE does not depend on them.
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity dsp_dut is
    port (
        clk_in    : in  std_logic;
        rst_in    : in  std_logic;
        valid_in  : in  std_logic;
        a_in      : in  signed(15 downto 0);
        b_in      : in  signed(15 downto 0);
        valid_out : out std_logic;
        data_out  : out signed(31 downto 0)
    );
end;

architecture rtl of dsp_dut is
    signal core_y : signed(31 downto 0);

    -- UF marking on the instance: the value is the uninterpreted function's symbol name.
    attribute uf_instance : string;
    attribute uf_instance of u_core : label is "dsp_f";
begin
    u_core : entity work.dsp_core
        port map (
            a_in  => a_in,
            b_in  => b_in,
            y_out => core_y
        );

    process (clk_in) is
    begin
        if rising_edge(clk_in) then
            if rst_in = '1' then
                data_out  <= (others => '0');
                valid_out <= '0';
            else
                valid_out <= valid_in;
                if valid_in = '1' then
                    data_out <= core_y;
                end if;
            end if;
        end if;
    end process;
end;

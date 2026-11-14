-- Formal testbench. It does not know what dsp_core computes.
-- Claim: when valid_in was '1' on the previous clock, data_out is the SAME function
-- of the same inputs from one clock cycle earlier -- and nothing else.
-- The reference instance is the same uninterpreted function as inside the DUT.
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity tb_dsp_dut_formal is
    port (
        clk_in   : in std_logic;
        rst_in   : in std_logic;
        valid_in : in std_logic;
        a_in     : in signed(15 downto 0);
        b_in     : in signed(15 downto 0)
    );
end;

architecture formal of tb_dsp_dut_formal is
    signal y     : signed(31 downto 0);
    signal yvld  : std_logic;
    signal ref_y : signed(31 downto 0);
    signal armed : std_logic := '0';
    -- rst_q = '1' when reset was asserted on the previous clock (initial value '0':
    -- registers are unconstrained in the formal initial state, so prev(rst_in) will not do).
    signal rst_q : std_logic := '0';

    attribute uf_instance : string;
    attribute uf_instance of u_ref : label is "dsp_f";
begin
    dut : entity work.dsp_dut
        port map (
            clk_in    => clk_in,
            rst_in    => rst_in,
            valid_in  => valid_in,
            a_in      => a_in,
            b_in      => b_in,
            valid_out => yvld,
            data_out  => y
        );

    -- Specification: the same uninterpreted function, no latency.
    u_ref : entity work.dsp_core
        port map (
            a_in  => a_in,
            b_in  => b_in,
            y_out => ref_y
        );

    -- armed = '1' when reset was not asserted on the previous clock
    process (clk_in) is
    begin
        if rising_edge(clk_in) then
            armed <= not rst_in;
            rst_q <= rst_in;
        end if;
    end process;

    default clock is rising_edge(clk_in);

    -- Data value: data_out is the function value from the previous cycle.
    a_value : assert always
        (armed = '1' and rst_in = '0' and prev(valid_in) = '1') -> (y = prev(ref_y));

    -- Control: valid_out follows valid_in with one cycle of latency.
    a_valid : assert always
        (armed = '1' and rst_in = '0') -> (yvld = prev(valid_in));

    -- Data hold: if valid_in was '0', data_out does not change.
    a_hold : assert always
        (armed = '1' and rst_in = '0' and prev(valid_in) = '0') -> (y = prev(y));

    -- Reset: after a reset cycle the output carries no valid beat. armed
    -- excludes this cycle from the other assertions, so without this one a
    -- ghost beat after reset (valid_out = '1') would go unnoticed.
    a_rst_valid : assert always
        (rst_q = '1') -> (yvld = '0');
end;

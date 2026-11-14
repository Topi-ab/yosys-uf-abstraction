library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

-- One DUT. The testbench instantiates it twice and drives the instances
-- with different control sequences.
-- The datapath abstraction is marked in the source code with the uf_instance attribute.
entity dsp is
    generic (
        -- true:  the datapath u_f is an uninterpreted function (dsp_f) in the
        --        formal model.
        -- false: the mark is switched off (uf_disable), u_f is exported with
        --        its interpreted architecture. Default true: the DUT as is
        --        uses the abstraction written in the source code.
        --        The generic has no effect on synthesis or simulation.
        UF_MODE : boolean := true
    );
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
    signal f_out : signed(15 downto 0);
    signal s1    : signed(15 downto 0);
    signal v1    : std_logic := '0';
    attribute uf_instance : string;
    attribute uf_instance of u_f : label is "dsp_f";
    attribute uf_disable : boolean;
    attribute uf_disable of u_f : label is not UF_MODE;
begin
    u_f : entity work.dsp_f
        port map (
            data_in  => data_in,
            data_out => f_out
        );

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
                    s1 <= f_out;
                end if;
                if v1 = '1' then
                    data_out <= s1;
                end if;
            end if;
        end if;
    end process;
end;

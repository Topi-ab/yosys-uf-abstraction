library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

-- Same two-instance structure as tests/vhdl_control_independence_setattr:
-- A (full rate) binds the output function out_f with an assumption, B
-- (arbitrary stalls) is checked against it. The stimulus stim_f and the
-- expected output out_f are uninterpreted functions of the beat index in both
-- tasks. The only difference between the tasks is the DUT multiplication
-- (uf: the mulw UF, nouf: bvmul). The data width is the generic WIDTH
-- (sby: ghdl -gWIDTH=..).
entity tb_dsp_formal is
    generic (
        WIDTH : positive := 8
    );
    port (
        clk_in     : in std_logic;
        rst_in     : in std_logic;
        valid_a_in : in std_logic;
        valid_b_in : in std_logic
    );
end;

architecture formal of tb_dsp_formal is
    signal icnt_a, icnt_b     : unsigned(15 downto 0) := (others => '0');
    signal ocnt_a, ocnt_b     : unsigned(15 downto 0) := (others => '0');
    signal a_feed, b_feed     : signed(WIDTH - 1 downto 0);
    signal a_res, b_res       : signed(WIDTH - 1 downto 0);
    signal yvalid_a, yvalid_b : std_logic;
    signal ufout_a, ufout_b   : signed(WIDTH - 1 downto 0);
    signal armed              : std_logic := '0';
    signal first              : std_logic := '1';

    attribute uf_instance : string;
    attribute uf_instance of u_stim_a : label is "stim_f";
    attribute uf_instance of u_stim_b : label is "stim_f";
    attribute uf_instance of u_out_a  : label is "out_f";
    attribute uf_instance of u_out_b  : label is "out_f";
begin
    u_stim_a : entity work.tb_stim_formal
        generic map (
            WIDTH => WIDTH
        )
        port map (
            idx_in   => signed(icnt_a),
            data_out => a_feed
        );

    u_stim_b : entity work.tb_stim_formal
        generic map (
            WIDTH => WIDTH
        )
        port map (
            idx_in   => signed(icnt_b),
            data_out => b_feed
        );

    u_out_a : entity work.tb_out_formal
        generic map (
            WIDTH => WIDTH
        )
        port map (
            idx_in   => signed(ocnt_a),
            data_out => ufout_a
        );

    u_out_b : entity work.tb_out_formal
        generic map (
            WIDTH => WIDTH
        )
        port map (
            idx_in   => signed(ocnt_b),
            data_out => ufout_b
        );

    a : entity work.dsp
        generic map (
            WIDTH => WIDTH
        )
        port map (
            clk_in    => clk_in,
            rst_in    => rst_in,
            valid_in  => valid_a_in,
            data_in   => a_feed,
            valid_out => yvalid_a,
            data_out  => a_res
        );

    b : entity work.dsp
        generic map (
            WIDTH => WIDTH
        )
        port map (
            clk_in    => clk_in,
            rst_in    => rst_in,
            valid_in  => valid_b_in,
            data_in   => b_feed,
            valid_out => yvalid_b,
            data_out  => b_res
        );

    process (clk_in) is
    begin
        if rising_edge(clk_in) then
            first <= '0';
            armed <= not rst_in;
            if rst_in = '1' then
                icnt_a <= (others => '0');
                icnt_b <= (others => '0');
                ocnt_a <= (others => '0');
                ocnt_b <= (others => '0');
            else
                if valid_a_in = '1' then icnt_a <= icnt_a + 1; end if;
                if valid_b_in = '1' then icnt_b <= icnt_b + 1; end if;
                if yvalid_a = '1' then ocnt_a <= ocnt_a + 1; end if;
                if yvalid_b = '1' then ocnt_b <= ocnt_b + 1; end if;
            end if;
        end if;
    end process;

    default clock is rising_edge(clk_in);

    a_init_reset : assume always
        (first = '1') -> (rst_in = '1');

    a_ref_rate : assume always
        (rst_in = '0') -> (valid_a_in = '1');

    a_define : assume always
        (armed = '1' and rst_in = '0' and yvalid_a = '1') -> (a_res = ufout_a);

    a_match : assert always
        (armed = '1' and rst_in = '0' and yvalid_b = '1') -> (b_res = ufout_b);

    -- Vacuity check (same condition as conftest.COVER_BOTH): both channels
    -- produce checked beats after the same reset. The bmc tasks remove it
    -- (chformal -cover -remove), the cover tasks run it (the assertion a_match
    -- stays in the cover run, as in conftest.run_cover).
    c_both_checked : cover {armed = '1' and rst_in = '0' and ocnt_a >= 3 and ocnt_b >= 3};
end;

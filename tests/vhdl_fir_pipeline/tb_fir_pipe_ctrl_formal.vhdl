-- Property 2: CONTROL DOES NOT DEPEND ON DATA (non-interference,
-- self-composition).
--
-- The same DUT (fir_complex_pipe) twice, C and D. The instances have the SAME
-- control inputs (reset, s_valid, m_ready: shared top-level inputs), but
-- MUTUALLY INDEPENDENT free data (s_re/s_im: separate top-level inputs for
-- each). Assertion: the control outputs s_ready and m_valid are equal on
-- every cycle. If any data value influenced the control, the solver would
-- pick different data for C and D and the outputs would differ.
--
-- In the pipeline the control state is truly stateful: one valid bit per
-- stage and (SKID) one skid slot valid per stage. The assertions look only at
-- the ports; the auxiliary invariant for induction (equal internal valid
-- vectors) is in the vunit tb_fir_pipe_ctrl_formal_inv.psl.
--
-- Datapath: in the ctrl_*_nouf tasks (UF_MODE = false, the DUT's marks
-- switched off) cmul and cadd are interpreted (real multiplication and
-- addition, showing that the property really holds), in the ctrl_*_uf tasks
-- (UF_MODE = true) they are uninterpreted (cheaper; sufficient, because
-- control must not depend on data through any datapath function).
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

use work.fir_complex_pipe_pkg.all;

entity tb_fir_pipe_ctrl_formal is
    generic (
        TAPS    : positive := 5;
        WIDTH   : positive := 8;
        SKID    : boolean  := false;
        -- The DUT's marks on (true) or off (false, uf_disable); sby sets the
        -- value (-gUF_MODE=...). Default false: the non-UF model.
        UF_MODE : boolean  := false
    );
    port (
        clk_in     : in std_logic;
        rst_in     : in std_logic;
        s_valid_in : in std_logic;
        m_ready_in : in std_logic;
        s_re_c_in  : in signed(WIDTH - 1 downto 0);
        s_im_c_in  : in signed(WIDTH - 1 downto 0);
        s_re_d_in  : in signed(WIDTH - 1 downto 0);
        s_im_d_in  : in signed(WIDTH - 1 downto 0)
    );
end;

architecture formal of tb_fir_pipe_ctrl_formal is
    constant OW : positive := out_width(TAPS, WIDTH);

    signal s_ready_c, s_ready_d : std_logic;
    signal m_valid_c, m_valid_d : std_logic;
    signal m_re_c, m_im_c       : signed(OW - 1 downto 0);
    signal m_re_d, m_im_d       : signed(OW - 1 downto 0);
    signal first                : std_logic := '1';
    -- s-side wait and data of the previous cycle (AXI stability assumptions).
    signal s_wait_c_q           : std_logic := '0';
    signal s_wait_d_q           : std_logic := '0';
    signal s_re_c_q, s_im_c_q   : signed(WIDTH - 1 downto 0);
    signal s_re_d_q, s_im_d_q   : signed(WIDTH - 1 downto 0);
    -- Helper counters and flags of the vacuity cover (as seen from C).
    signal icnt                 : unsigned(15 downto 0) := (others => '0');
    signal ocnt                 : unsigned(15 downto 0) := (others => '0');
    signal in_bp                : std_logic := '0';
    signal out_bp               : std_logic := '0';
begin
    c : entity work.fir_complex_pipe
        generic map (
            TAPS    => TAPS,
            WIDTH   => WIDTH,
            SKID    => SKID,
            UF_MODE => UF_MODE
        )
        port map (
            clk_in      => clk_in,
            rst_in      => rst_in,
            s_valid_in  => s_valid_in,
            s_ready_out => s_ready_c,
            s_re_in     => s_re_c_in,
            s_im_in     => s_im_c_in,
            m_valid_out => m_valid_c,
            m_ready_in  => m_ready_in,
            m_re_out    => m_re_c,
            m_im_out    => m_im_c
        );

    d : entity work.fir_complex_pipe
        generic map (
            TAPS    => TAPS,
            WIDTH   => WIDTH,
            SKID    => SKID,
            UF_MODE => UF_MODE
        )
        port map (
            clk_in      => clk_in,
            rst_in      => rst_in,
            s_valid_in  => s_valid_in,
            s_ready_out => s_ready_d,
            s_re_in     => s_re_d_in,
            s_im_in     => s_im_d_in,
            m_valid_out => m_valid_d,
            m_ready_in  => m_ready_in,
            m_re_out    => m_re_d,
            m_im_out    => m_im_d
        );

    process (clk_in) is
    begin
        if rising_edge(clk_in) then
            first    <= '0';
            s_re_c_q <= s_re_c_in;
            s_im_c_q <= s_im_c_in;
            s_re_d_q <= s_re_d_in;
            s_im_d_q <= s_im_d_in;
            if rst_in = '1' then
                s_wait_c_q <= '0';
                s_wait_d_q <= '0';
                icnt       <= (others => '0');
                ocnt       <= (others => '0');
                in_bp      <= '0';
                out_bp     <= '0';
            else
                s_wait_c_q <= s_valid_in and not s_ready_c;
                s_wait_d_q <= s_valid_in and not s_ready_d;
                if s_valid_in = '1' and s_ready_c = '1' then
                    icnt <= icnt + 1;
                end if;
                if m_valid_c = '1' and m_ready_in = '1' then
                    ocnt <= ocnt + 1;
                end if;
                if s_valid_in = '1' and s_ready_c = '0' then
                    in_bp <= '1';
                end if;
                if m_valid_c = '1' and m_ready_in = '0' then
                    out_bp <= '1';
                end if;
            end if;
        end if;
    end process;

    default clock is rising_edge(clk_in);

    -- Initial reset: without it the uninitialised valid bits of the DUT could
    -- differ between C and D already in the initial state.
    a_init_reset : assume always
        (first = '1') -> (rst_in = '1');

    -- AXI s-side (obligation of the testbench, only for the signals the
    -- testbench drives): valid stays up and data is stable until the beat is
    -- accepted. The data of each instance is stable according to its own ready.
    a_valid_hold : assume always
        (rst_in = '0' and (s_wait_c_q = '1' or s_wait_d_q = '1')) -> (s_valid_in = '1');
    a_data_stable_c : assume always
        (rst_in = '0' and s_wait_c_q = '1') -> (s_re_c_in = s_re_c_q and s_im_c_in = s_im_c_q);
    a_data_stable_d : assume always
        (rst_in = '0' and s_wait_d_q = '1') -> (s_re_d_in = s_re_d_q and s_im_d_in = s_im_d_q);

    -- Non-interference: the control outputs are equal on every cycle after reset.
    a_s_ready_eq : assert always
        (first = '0') -> (s_ready_c = s_ready_d);
    a_m_valid_eq : assert always
        (first = '0') -> (m_valid_c = m_valid_d);
end;

-- Two-stream scoreboard with a single symbolic sequence number.
--
-- Stream a (e.g. the accepted input beats of a FIFO) and stream b (accepted
-- output beats): beat k must be the same in both streams (order is preserved,
-- nothing is lost or duplicated).
--
-- The checker does not store a queue. master_ptr is a free constant
-- (anyconst), and the checker follows only the beat whose sequence number is
-- master_ptr:
--   *_ptr      sequence number of the next beat (number of beats accepted
--              since reset before this cycle),
--   *_captured beat master_ptr has been seen in this or an earlier cycle,
--   mem_*      its data.
-- Since master_ptr is free, the solver checks every beat.
--
-- Zero delay: *_ptr, *_captured and mem_* are anyseq signals whose value is
-- defined by assumptions from the previous cycle's values (prev) and this
-- cycle's inputs. On the capture cycle mem_* already equals the data and
-- *_captured is already '1', so the comparison happens in the same cycle in
-- which beat master_ptr of b is seen. The checker adds no register delay to
-- the testbench (the BMC horizon does not grow). The assumptions are
-- definitions: for every input history exactly one value satisfies them, so
-- they constrain neither the environment nor the DUT.
--
-- Only the first hit is captured (mem_* updates only when *_captured rises).
-- Otherwise a wrap of the PTR_BITS-bit pointer would capture beat
-- master_ptr + 2^PTR_BITS of a before b has produced the matching beat, and
-- the comparison would go wrong (false FAIL, a real counterexample in
-- k-induction). The checked beats are therefore 0 .. 2^PTR_BITS - 1 after
-- reset.
--
-- Reset (rst_in, synchronous, active high) clears the pointers and captures;
-- beats on the reset cycle are not counted. rst_in = '1' on the first cycle is
-- the user's responsibility (here tb_axis_ctrl_formal assumes it): without it
-- the initial pointers are free (false FAIL, not a false PASS).
--
-- Assert form only (no assume variant).
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity tb_stream_scoreboard_formal is
    generic (
        DATA_BITS : positive := 8;
        PTR_BITS  : positive := 32
    );
    port (
        clk_in     : in std_logic;
        rst_in     : in std_logic;
        a_valid_in : in std_logic;
        a_data_in  : in std_logic_vector(DATA_BITS - 1 downto 0);
        b_valid_in : in std_logic;
        b_data_in  : in std_logic_vector(DATA_BITS - 1 downto 0)
    );
end;

architecture formal of tb_stream_scoreboard_formal is
    attribute anyconst : boolean;
    attribute anyseq   : boolean;

    signal master_ptr : unsigned(PTR_BITS - 1 downto 0);
    attribute anyconst of master_ptr : signal is true;

    signal a_ptr      : unsigned(PTR_BITS - 1 downto 0);
    signal b_ptr      : unsigned(PTR_BITS - 1 downto 0);
    signal a_captured : std_logic;
    signal b_captured : std_logic;
    signal mem_a      : std_logic_vector(DATA_BITS - 1 downto 0);
    signal mem_b      : std_logic_vector(DATA_BITS - 1 downto 0);
    attribute anyseq of a_ptr      : signal is true;
    attribute anyseq of b_ptr      : signal is true;
    attribute anyseq of a_captured : signal is true;
    attribute anyseq of b_captured : signal is true;
    attribute anyseq of mem_a      : signal is true;
    attribute anyseq of mem_b      : signal is true;

    -- A counted beat (not on the reset cycle) and a hit on beat master_ptr.
    signal a_beat : std_logic;
    signal b_beat : std_logic;
    signal a_hit  : std_logic;
    signal b_hit  : std_logic;
begin
    a_beat <= a_valid_in and not rst_in;
    b_beat <= b_valid_in and not rst_in;
    a_hit  <= '1' when a_beat = '1' and a_ptr = master_ptr else '0';
    b_hit  <= '1' when b_beat = '1' and b_ptr = master_ptr else '0';

    default clock is rising_edge(clk_in);

    -- Sequence number: 0 in reset, incremented by one after every beat.
    d_a_ptr_rst : assume always
        (rst_in = '1') -> (a_ptr = 0);
    d_a_ptr_inc : assume always
        (rst_in = '0' and prev(a_beat) = '1') -> (a_ptr = prev(a_ptr) + 1);
    d_a_ptr_hold : assume always
        (rst_in = '0' and prev(a_beat) = '0') -> (a_ptr = prev(a_ptr));

    d_b_ptr_rst : assume always
        (rst_in = '1') -> (b_ptr = 0);
    d_b_ptr_inc : assume always
        (rst_in = '0' and prev(b_beat) = '1') -> (b_ptr = prev(b_ptr) + 1);
    d_b_ptr_hold : assume always
        (rst_in = '0' and prev(b_beat) = '0') -> (b_ptr = prev(b_ptr));

    -- The capture flag rises on the hit cycle and stays up until reset.
    d_a_captured_rst : assume always
        (rst_in = '1') -> (a_captured = '0');
    d_a_captured : assume always
        (rst_in = '0') -> (a_captured = (a_hit or prev(a_captured)));

    d_b_captured_rst : assume always
        (rst_in = '1') -> (b_captured = '0');
    d_b_captured : assume always
        (rst_in = '0') -> (b_captured = (b_hit or prev(b_captured)));

    -- Captured data: this cycle's data when the flag rises; otherwise unchanged.
    d_mem_a_capture : assume always
        rose(a_captured) -> (mem_a = a_data_in);
    d_mem_a_hold : assume always
        rose(a_captured) or stable(mem_a);

    d_mem_b_capture : assume always
        rose(b_captured) -> (mem_b = b_data_in);
    d_mem_b_hold : assume always
        rose(b_captured) or stable(mem_b);

    -- Beat master_ptr is the same in both streams.
    a_sb_match : assert always
        (a_captured = '1' and b_captured = '1') -> (mem_a = mem_b);
end;

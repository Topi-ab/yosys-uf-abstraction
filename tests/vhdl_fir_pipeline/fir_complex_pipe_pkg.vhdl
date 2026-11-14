-- Shared definitions of the pipelined complex FIR filter: coefficients,
-- widths and pipeline dimensions. Users: fir_complex_pipe (the DUT),
-- fir_pipe_ref (the reference computation for the invariants) and the
-- testbenches.
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

package fir_complex_pipe_pkg is
    -- Maximum number of taps (length of the coefficient table).
    constant MAX_TAPS : positive := 16;

    -- Fixed complex coefficients c(k) = COEF_RE(k) + i*COEF_IM(k), the same as
    -- in tests/vhdl_fir_independence: all nonzero and asymmetric, so swapping
    -- taps, swapping a coefficient or mixing up re/im changes the result.
    -- The values fit in a 4-bit signed number (WIDTH >= 4).
    constant COEF_RE : integer_vector(0 to MAX_TAPS - 1) :=
        (3, -2, 5, 1, -7, 4, -1, 6, 2, -5, 7, -3, 1, -6, 4, -2);
    constant COEF_IM : integer_vector(0 to MAX_TAPS - 1) :=
        (-1, 4, 2, -6, 3, -5, 7, 1, -4, 6, -2, 5, -7, 2, -3, 1);

    -- ceil(log2(n)), n >= 1.
    function clog2(n : positive) return natural;

    -- Width of a component of a complex product, 2*WIDTH+1.
    function prod_width(width : positive) return positive;

    -- Width of the output (and of the adder tree) 2*WIDTH+1+ceil(log2(TAPS)):
    -- the sum of TAPS products cannot overflow, so there is no truncation.
    function out_width(taps : positive; width : positive) return positive;

    -- Number of pipeline stages: the multiplier stage (0), the adder tree
    -- levels 1..clog2(TAPS) and the output stage (clog2(TAPS)+1).
    function pipe_depth(taps : positive) return positive;

    -- Number of elements in stage i: stage 0 has TAPS products, tree level l
    -- ceil(previous/2), the output stage 1.
    function stage_cnt(taps : positive; i : natural) return positive;

    -- Length of the input history used by the invariants: at most
    -- 2*pipe_depth beats can be in flight (two slots per stage in the skid
    -- style), and the window of the oldest beat reaches TAPS-1 samples back.
    function hist_len(taps : positive) return positive;
end package;

package body fir_complex_pipe_pkg is
    function clog2(n : positive) return natural is
        variable r : natural := 0;
        variable v : natural := 1;
    begin
        while v < n loop
            v := v * 2;
            r := r + 1;
        end loop;
        return r;
    end function;

    function prod_width(width : positive) return positive is
    begin
        return 2 * width + 1;
    end function;

    function out_width(taps : positive; width : positive) return positive is
    begin
        return prod_width(width) + clog2(taps);
    end function;

    function pipe_depth(taps : positive) return positive is
    begin
        return clog2(taps) + 2;
    end function;

    function stage_cnt(taps : positive; i : natural) return positive is
        variable c : positive := taps;
    begin
        for l in 1 to i loop
            c := (c + 1) / 2;
        end loop;
        return c;
    end function;

    function hist_len(taps : positive) return positive is
    begin
        return 2 * pipe_depth(taps) + taps - 1;
    end function;
end package body;

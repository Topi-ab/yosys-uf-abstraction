-- Shared definitions of the complex FIR filter: coefficients and widths.
-- Users: fir_complex (DUT) and the testbenches (output width).
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

package fir_complex_pkg is
    -- Maximum number of taps (length of the coefficient table).
    constant MAX_TAPS : positive := 16;

    -- Fixed complex coefficients c(k) = COEF_RE(k) + i*COEF_IM(k).
    -- All are nonzero and asymmetric (no c(k) = c(TAPS-1-k) and no re = im), so
    -- that swapped taps, a swapped coefficient or mixed-up re/im parts change
    -- the result. The values fit in a 4-bit signed number, so they fit in every
    -- WIDTH >= 4.
    constant COEF_RE : integer_vector(0 to MAX_TAPS - 1) :=
        (3, -2, 5, 1, -7, 4, -1, 6, 2, -5, 7, -3, 1, -6, 4, -2);
    constant COEF_IM : integer_vector(0 to MAX_TAPS - 1) :=
        (-1, 4, 2, -6, 3, -5, 7, 1, -4, 6, -2, 5, -7, 2, -3, 1);

    -- ceil(log2(n)), n >= 1.
    function clog2(n : positive) return natural;

    -- Width of a complex product component: a_re*b_re - a_im*b_im fits in
    -- 2*WIDTH+1 bits (sum of two 2*WIDTH-bit products).
    function prod_width(width : positive) return positive;

    -- Output width: sum of TAPS products, 2*WIDTH+1+ceil(log2(TAPS)) bits.
    -- Overflow cannot happen, so there is no resize truncation.
    function out_width(taps : positive; width : positive) return positive;
end package;

package body fir_complex_pkg is
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
end package body;

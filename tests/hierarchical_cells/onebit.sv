// Box with a 1-bit (valid) and an 8-bit output.
// The assertion fails because the UF is free: the counterexample must replay from the witness.
module box(input [7:0] a, output valid, output [7:0] d);
    assign valid = a[0];
    assign d = a;
endmodule

module top(input clk, input [7:0] x);
    wire valid;
    wire [7:0] d;
    (* uf_instance = "h" *) box u(.a(x), .valid(valid), .d(d));
    always @* assert (!valid || d != 8'd5);
endmodule

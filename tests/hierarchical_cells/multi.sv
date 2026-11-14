// Two outputs, o0[15:0] before o1[7:0] -> the UF returns (_ BitVec 24),
// with o0 in the most significant bits. The box's own implementation must not appear in the model.
module box(input [7:0] a, input [15:0] b, output [15:0] o0, output [7:0] o1);
    assign o0 = b + a;
    assign o1 = a ^ b[7:0];
endmodule

module top(input clk, input [7:0] x, input [15:0] z,
           output [15:0] p0, output [15:0] q0, output [7:0] p1, output [7:0] q1);
    (* uf_instance = "g" *) box u1(.a(x), .b(z), .o0(p0), .o1(p1));
`ifdef OPEN
    // unconnected output: still part of the return width
    (* uf_instance = "g" *) box u2(.a(x), .b(z), .o0(q0), .o1());
    assign q1 = 8'd0;
`else
    (* uf_instance = "g" *) box u2(.a(x), .b(z), .o0(q0), .o1(q1));
`endif
`ifdef BAD
    // the slices are independent: does not follow from congruence
    always @* assert (p0[7:0] == p1);
`elsif OPEN
    always @* assert (p0 == q0);
`else
    always @* assert (p0 == q0 && p1 == q1);
`endif
endmodule

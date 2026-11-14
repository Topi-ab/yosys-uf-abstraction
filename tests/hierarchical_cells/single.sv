// Single-output box as two marked instances.
module box(input [7:0] a, output [7:0] y);
    assign y = a * 8'd3;
endmodule

module top(input clk, input [7:0] x, output [7:0] o1, output [7:0] o2);
    (* uf_instance = "f" *) box u1(.a(x), .y(o1));
`ifdef UNMARKED
    box u2(.a(x), .y(o2));
`else
    (* uf_instance = "f" *) box u2(.a(x), .y(o2));
`endif
    always @* assert (o1 == o2);
`ifdef BAD
    // the UF is free: the interpreted value x * 3 does not follow from anything
    always @* assert (o1 == x * 8'd3);
`endif
    // reachable only if the UF is free (interpreted: 3 * 3 = 9)
    always @* cover (x == 8'd3 && o1 == 8'd5);
endmodule

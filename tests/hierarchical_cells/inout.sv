// A marked box with an inout port. UNCONN: the inout is left unconnected
// (a connected inout hits the generic direction error of write_smt2).
module boxio(inout [7:0] a, input [7:0] b, output [7:0] y);
    assign y = b;
endmodule

module top(input [7:0] x, output [7:0] o);
    wire [7:0] w = x;
`ifdef UNCONN
    (* uf_instance = "io" *) boxio u(.a(), .b(x), .y(o));
`else
    (* uf_instance = "io" *) boxio u(.a(w), .b(x), .y(o));
`endif
endmodule

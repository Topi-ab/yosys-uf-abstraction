// Reserved and predefined SMT-LIB names as uf_instance symbols.
// HIER: the symbol is on the instance u, otherwise on the $add cell (the test sets it with setattr).
module box(input [7:0] a, output [7:0] y);
    assign y = a + 8'd1;
endmodule

module top(input [7:0] x, input [7:0] z, output [7:0] o);
`ifdef HIER
    box u(.a(x), .y(o));
`else
    assign o = x + z;
`endif
    always @* assert (o == o);
endmodule

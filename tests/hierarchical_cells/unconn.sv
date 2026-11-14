// Unconnected input -> error.
module box(input [7:0] a, input [7:0] b, output [7:0] y);
    assign y = a + b;
endmodule

module top(input [7:0] x, output [7:0] o);
    (* uf_instance = "uc" *) box u(.a(x), .b(), .y(o));
endmodule

// Marked instances of a blackbox module (no implementation).
// UNMARKED: the second instance is unmarked. PARAM: parametric blackbox (an error).
`ifdef PARAM
(* blackbox *)
module box #(parameter W = 8) (input [W-1:0] a, output [W-1:0] y);
endmodule

module top(input [15:0] x, output [15:0] o1);
    (* uf_instance = "b" *) box #(.W(16)) u1(.a(x), .y(o1));
endmodule
`else
(* blackbox *)
module box(input [7:0] a, output [7:0] y);
endmodule

module top(input clk, input [7:0] x, output [7:0] o1, output [7:0] o2);
    (* uf_instance = "b" *) box u1(.a(x), .y(o1));
`ifdef UNMARKED
    box u2(.a(x), .y(o2));
`else
    (* uf_instance = "b" *) box u2(.a(x), .y(o2));
`endif
`ifdef BAD
    always @* assert (o1 == x);
`else
    always @* assert (o1 == o2);
`endif
endmodule
`endif

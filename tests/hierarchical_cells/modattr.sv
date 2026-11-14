// A module-level uf_instance has no effect; instances must be marked.
(* uf_instance = "ma" *)
module box(input [7:0] a, output [7:0] y);
    assign y = a + 8'd1;
endmodule

module top(input [7:0] x, output [7:0] o);
    box u1(.a(x), .y(o));
endmodule

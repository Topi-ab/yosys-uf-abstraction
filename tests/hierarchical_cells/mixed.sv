// Built-in $neg and a hierarchical cell sharing the symbol "f".
// Congruence: same arguments -> same results, even though the implementations differ.
module box(input [7:0] a, output [7:0] y);
    assign y = a + 8'd1;
endmodule

module top(input clk, input [7:0] x, output [7:0] o1, output [7:0] o2);
    assign o1 = -x;
    (* uf_instance = "f" *) box u(.a(x), .y(o2));
    always @* assert (o1 == o2);
endmodule

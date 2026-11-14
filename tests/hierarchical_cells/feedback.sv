// Feedback through the box (b <= y0). The UF output is a free variable,
// so no logic loop error occurs.
module box(input [7:0] a, input [7:0] b, output [7:0] y0, output [7:0] y1);
    assign y0 = a + b;
    assign y1 = a - b;
endmodule

module top(input clk, input [7:0] x, output [7:0] o);
    wire [7:0] t;
    (* uf_instance = "fb" *) box u(.a(x), .b(t), .y0(t), .y1(o));
    always @* assert (o == o);
endmodule

// The box's unused clk input is connected to the parent's clock -> warning.
// CTL: same box, clk input driven by a data signal -> no warning.
module box(input clk, input [7:0] a, output [7:0] y);
    assign y = a + 8'd1;
endmodule

module top(input clk, input [7:0] x, output reg [7:0] r);
    wire [7:0] o;
`ifdef CTL
    (* uf_instance = "c" *) box u(.clk(x[0]), .a(x), .y(o));
`else
    (* uf_instance = "c" *) box u(.clk(clk), .a(x), .y(o));
`endif
    always @(posedge clk) r <= o;
endmodule

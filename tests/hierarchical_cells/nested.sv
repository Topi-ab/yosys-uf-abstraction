// UF cell inside a submodule (mid) instantiated without a UF mark.
module box(input [7:0] a, output [7:0] y);
    assign y = a + 8'd1;
endmodule

module mid(input clk, input [7:0] a, output [7:0] y);
    wire [7:0] t;
    (* uf_instance = "n" *) box ub(.a(a), .y(t));
    reg [7:0] r = 8'd0;
    always @(posedge clk) r <= t;
    assign y = r;
endmodule

module top(input clk, input [7:0] x, output [7:0] o);
    mid um(.clk(clk), .a(x), .y(o));
    always @(posedge clk) assert (o != 8'd5);
endmodule

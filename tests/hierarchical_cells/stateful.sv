// Box that is stateful or contains formal cells. The body is selected with
// a K_* macro, and DEEP moves it one level deeper (core).
`ifdef K_DFF
`define BODY reg [7:0] r; always @(posedge clk) r <= a; assign y = r;
`elsif K_MEM
`define BODY reg [7:0] m [0:3]; always @(posedge clk) m[a[1:0]] <= a; assign y = m[a[3:2]];
`elsif K_ANYSEQ
`define BODY (* anyseq *) reg [7:0] c; assign y = a ^ c;
`elsif K_ANYCONST
`define BODY (* anyconst *) reg [7:0] c; assign y = a ^ c;
`elsif K_ASSERT
`define BODY always @* assert (a != 8'd0); assign y = a;
`elsif K_ASSUME
`define BODY always @* assume (a != 8'd0); assign y = a;
`endif

module core(input clk, input [7:0] a, output [7:0] y);
    `BODY
endmodule

module box(input clk, input [7:0] a, output [7:0] y);
`ifdef DEEP
    core i(.clk(clk), .a(a), .y(y));
`else
    `BODY
`endif
endmodule

module top(input clk, input [7:0] x, output [7:0] o);
    (* uf_instance = "st" *) box u(.clk(clk), .a(x), .y(o));
endmodule

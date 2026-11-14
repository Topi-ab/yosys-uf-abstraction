module sub(input [7:0] a, output [7:0] y); assign y = a + 8'd1; endmodule
module warn(input [7:0] a, input [7:0] b, input s, output lt, output [7:0] m, output [7:0] h, output r, output [7:0] sh);
  assign sh = a << b[2:0];
  assign lt = a < b;
  assign m = s ? a : b;
  wire [7:0] unused = a - b;
  assign r = |a;
  sub u_sub(.a(a), .y(h));
endmodule

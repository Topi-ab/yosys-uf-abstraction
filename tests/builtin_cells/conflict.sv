module conflict(input [7:0] a, input [15:0] c, output [7:0] y, output [15:0] z);
  assign y = a * a;
  assign z = c * c;
endmodule

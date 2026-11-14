module comm(input clk, input [7:0] a, input [7:0] b);
  wire [7:0] p = a * b;
  always @* begin
    assume (b == 8'd1);
    assert (p == a);
  end
endmodule

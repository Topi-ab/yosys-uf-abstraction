// Box without inputs -> (declare-fun |k| () (_ BitVec 8)), used as a bare |k|.
module box(output [7:0] y);
    assign y = 8'd7;
endmodule

module top(input clk, output [7:0] o1, output [7:0] o2);
    (* uf_instance = "k" *) box u1(.y(o1));
    (* uf_instance = "k" *) box u2(.y(o2));
    always @* assert (o1 == o2);
`ifdef BAD
    // the constant is uninterpreted: the value 7 does not follow from anything
    always @* assert (o1 == 8'd7);
`endif
endmodule

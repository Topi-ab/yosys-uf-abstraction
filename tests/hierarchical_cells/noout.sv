// Box without outputs. keep prevents opt_clean from removing the cell.
module box(input [7:0] a);
endmodule

module top(input [7:0] x);
    (* uf_instance = "no", keep *) box u1(.a(x));
endmodule

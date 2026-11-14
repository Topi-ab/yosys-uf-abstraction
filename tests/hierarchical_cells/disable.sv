// uf_disable switches the uf_instance mark of the same cell off. The parameter
// UF_MODE selects the UF model (1, default) or the non-UF model (0); the test or
// sby supplies the value (hierarchy -chparam UF_MODE 0). BAD: an assertion that
// holds only in the non-UF model.
module box(input [7:0] a, output [7:0] y);
    assign y = a * 8'd3;
endmodule

module top #(parameter UF_MODE = 1) (input [7:0] x, output [7:0] o1, output [7:0] o2);
    (* uf_instance = "f", uf_disable = !UF_MODE *) box u1(.a(x), .y(o1));
    (* uf_instance = "f", uf_disable = !UF_MODE *) box u2(.a(x), .y(o2));
    always @* assert (o1 == o2);
`ifdef BAD
    // free as a UF, x * 3 when interpreted
    always @* assert (o1 == x * 8'd3);
`endif
endmodule

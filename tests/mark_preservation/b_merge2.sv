// opt_merge path: two $mul cells with the same inputs and different UF symbols f and g.
// Under UF semantics f(a,b) == g(a,b) does not hold -> expected FAIL.
module b_merge2 (
    input [7:0] a_in,
    input [7:0] b_in
);
    wire [7:0] pf = a_in * (* uf_instance = "f" *) b_in;
    wire [7:0] pg = a_in * (* uf_instance = "g" *) b_in;

    always @* assert (pf == pg);
endmodule

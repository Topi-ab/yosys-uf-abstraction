// uf_disable on a built-in cell in the source. UF_MODE = 1 (default): $add is
// UF g; UF_MODE = 0 (hierarchy -chparam): interpreted. $mul is always UF h (reference).
module dis_top #(parameter UF_MODE = 1) (input [7:0] a, input [7:0] b, output [7:0] s, output [7:0] m);
    assign s = a + (* uf_instance = "g", uf_disable = !UF_MODE *) b;
    assign m = a * (* uf_instance = "h" *) b;
endmodule

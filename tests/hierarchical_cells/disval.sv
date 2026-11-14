// The uf_disable value forms that read_verilog produces. d_* = off,
// e_* = on; p_not depends on the parameter (UF_MODE = 0 -> off).
//   (* uf_disable *)       32-bit 1           = 1 / = 0  32-bit integer
//   = !UF_MODE, = 1'b1     1-bit              = "true"   string
module box(input [7:0] a, output [7:0] y);
    assign y = a + 8'd5;
endmodule

module top #(parameter UF_MODE = 1) (input [7:0] x, output [7:0] o0, output [7:0] o1,
        output [7:0] o2, output [7:0] o3, output [7:0] o4, output [7:0] o5,
        output [7:0] o6, output [7:0] o7);
    (* uf_instance = "d_bare", uf_disable *) box u0(.a(x), .y(o0));
    (* uf_instance = "d_one", uf_disable = 1 *) box u1(.a(x), .y(o1));
    (* uf_instance = "e_zero", uf_disable = 0 *) box u2(.a(x), .y(o2));
    (* uf_instance = "p_not", uf_disable = !UF_MODE *) box u3(.a(x), .y(o3));
    (* uf_instance = "d_str", uf_disable = "true" *) box u4(.a(x), .y(o4));
    (* uf_instance = "e_str", uf_disable = "false" *) box u5(.a(x), .y(o5));
    (* uf_instance = "d_bit", uf_disable = 1'b1 *) box u6(.a(x), .y(o6));
    (* uf_instance = "e_bit", uf_disable = 1'b0 *) box u7(.a(x), .y(o7));
endmodule

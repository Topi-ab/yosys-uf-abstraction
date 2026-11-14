// Feedback through a marked box from the outside (b <= y0) is allowed also when
// the box contains submodule instances. The UF output is a free variable, so the
// loop check does not apply outside the box.
//   (default) box through the instance m (addsub)
//   DEEP      box through two levels (box.m.n)
//   WRAP      the fed-back box inside an unmarked wrap module
//   BAD       assertion o == x, which fails with the UF (the solver really runs the model)
module addsub(input [7:0] a, input [7:0] b, output [7:0] s, output [7:0] d);
    assign s = a + b;
    assign d = a - b;
endmodule

module addsub2(input [7:0] a, input [7:0] b, output [7:0] s, output [7:0] d);
    addsub n(.a(a), .b(b), .s(s), .d(d));
endmodule

module box(input [7:0] a, input [7:0] b, output [7:0] y0, output [7:0] y1);
`ifdef DEEP
    addsub2 m(.a(a), .b(b), .s(y0), .d(y1));
`else
    addsub m(.a(a), .b(b), .s(y0), .d(y1));
`endif
endmodule

module wrap(input [7:0] x, output [7:0] o);
    wire [7:0] t;
    (* uf_instance = "fb" *) box u(.a(x), .b(t), .y0(t), .y1(o));
endmodule

module top(input clk, input [7:0] x, output [7:0] o);
`ifdef WRAP
    wrap w(.x(x), .o(o));
`else
    wire [7:0] t;
    (* uf_instance = "fb" *) box u(.a(x), .b(t), .y0(t), .y1(o));
`endif
`ifdef BAD
    always @* assert (o == x);
`else
    always @* assert (o == o);
`endif
endmodule

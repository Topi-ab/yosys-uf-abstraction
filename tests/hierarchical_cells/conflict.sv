// Signature and port order conflicts. The case is selected with a macro.
module m1(input [7:0] a, input [7:0] b, output [7:0] y);
    assign y = a - b;
endmodule

// same names and widths, inputs in swapped order
module m2(input [7:0] b, input [7:0] a, output [7:0] y);
    assign y = a - b;
endmodule

// same names and same order as m1: may share the symbol
module m3(input [7:0] a, input [7:0] b, output [7:0] y);
    assign y = a + b;
endmodule

// different names, same widths
module g(input [7:0] p, input [7:0] q, output [7:0] y);
    assign y = p - q;
endmodule

// outputs in swapped order
module n1(input [7:0] a, output [7:0] p, output [7:0] q);
    assign p = a;
    assign q = ~a;
endmodule

module n2(input [7:0] a, output [7:0] q, output [7:0] p);
    assign p = a;
    assign q = ~a;
endmodule

// same return width 16, different split (8+8 vs 4+12)
module s1(input [7:0] a, output [7:0] p, output [7:0] q);
    assign p = a;
    assign q = a;
endmodule

module s2(input [7:0] a, output [3:0] p, output [11:0] q);
    assign p = a[3:0];
    assign q = {4'd0, a};
endmodule

// different argument width
module w16(input [15:0] a, input [7:0] b, output [7:0] y);
    assign y = a[7:0] - b;
endmodule

module top(input [7:0] x, input [7:0] z, input [15:0] xx,
           output [7:0] o0, output [7:0] o1, output [7:0] o2,
           output [7:0] o3, output [7:0] o4, output [3:0] o5, output [11:0] o6);
`ifdef BUILTIN
    // the first user is a built-in cell (marked with setattr)
    assign o0 = x - z;
`endif
`ifdef MIDDLE
    (* uf_instance = "f" *) g ug(.p(x), .q(z), .y(o0));
`endif
`ifdef IN_SWAP
    (* uf_instance = "f" *) m1 u1(.a(x), .b(z), .y(o1));
    (* uf_instance = "f" *) m2 u2(.a(x), .b(z), .y(o2));
`endif
`ifdef SAME
    (* uf_instance = "f" *) m1 u1(.a(x), .b(z), .y(o1));
    (* uf_instance = "f" *) m3 u2(.a(x), .b(z), .y(o2));
`endif
`ifdef OUT_SWAP
    (* uf_instance = "f" *) n1 u1(.a(x), .p(o1), .q(o2));
    (* uf_instance = "f" *) n2 u2(.a(x), .p(o3), .q(o4));
`endif
`ifdef SPLIT
    (* uf_instance = "f" *) s1 u1(.a(x), .p(o1), .q(o2));
    (* uf_instance = "f" *) s2 u2(.a(x), .p(o5), .q(o6));
`endif
`ifdef WIDTH
    (* uf_instance = "f" *) m1 u1(.a(x), .b(z), .y(o1));
    (* uf_instance = "f" *) w16 u2(.a(xx), .b(z), .y(o2));
`endif
endmodule

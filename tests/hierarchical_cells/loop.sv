// Combinational loop inside a marked box. A loop through a submodule instance is
// not a "logic loop" error of write_smt2, because the instance output is a free
// variable bound by the hierarchy equation: t = a & t is free when a = 1. In the
// non-UF design ua and ub have their own free t (ya == yb FAILs); with
// uf_instance both are the same function, so without the check the result would
// be a false PASS.
//   (default) loop through the instance s in the box (t = a & t)
//   PASS2     loop through two pass-through instances (t -> p -> q -> t)
//   DEEP      loop inside a submodule (box.m)
//   INNER     loop through a nested uf_instance instance
//   CELLS     loop through built-in cells only
//   XLEVEL    loop across two hierarchy levels: the box connects the output of
//             instance m to its input, and m's dependency goes through its own instance
//   DEEP2     loop on the third level (box.m.n)
//   ROT       bit-level loop: b = t rotated (t[7] -> t[0] -> ... -> t[7])
//   INNER_NOLOOP control: NOLOOP with a nested uf_instance instance -> accepted
//   NOLOOP    control: independent paths of the instance (x = a, y = a ^ b), the box
//             connects x to b -> no loop, accepted
module and2(input [7:0] a, input [7:0] b, output [7:0] y);
    assign y = a & b;
endmodule

module thru(input [7:0] a, output [7:0] y);
    assign y = a;
endmodule

module pair(input [7:0] a, input [7:0] b, output [7:0] x, output [7:0] y);
    assign x = a;
    assign y = a ^ b;
endmodule

module mid(input [7:0] a, output [7:0] y);
    wire [7:0] t;
    and2 s(.a(a), .b(t), .y(t));
    assign y = t;
endmodule

module mid2(input [7:0] a, input [7:0] b, output [7:0] y);
    and2 s(.a(a), .b(b), .y(y));
endmodule

module deep2(input [7:0] a, output [7:0] y);
    mid n(.a(a), .y(y));
endmodule

module box(input [7:0] a, output [7:0] y);
`ifdef PASS2
    wire [7:0] t;
    wire [7:0] p;
    and2 s(.a(a), .b(p), .y(t));
    thru u1(.a(t), .y(p));
    assign y = t;
`elsif DEEP
    mid m(.a(a), .y(y));
`elsif INNER
    wire [7:0] t;
    (* uf_instance = "inner" *) and2 s(.a(a), .b(t), .y(t));
    assign y = t;
`elsif CELLS
    wire [7:0] t;
    assign t = a & t;
    assign y = t;
`elsif NOLOOP
    wire [7:0] u;
    pair s(.a(a), .b(u), .x(u), .y(y));
`elsif INNER_NOLOOP
    wire [7:0] u;
    (* uf_instance = "inner" *) pair s(.a(a), .b(u), .x(u), .y(y));
`elsif XLEVEL
    wire [7:0] t;
    mid2 m(.a(a), .b(t), .y(t));
    assign y = t;
`elsif DEEP2
    deep2 m(.a(a), .y(y));
`elsif ROT
    wire [7:0] t;
    and2 s(.a(a), .b({t[6:0], t[7]}), .y(t));
    assign y = t;
`else
    wire [7:0] t;
    and2 s(.a(a), .b(t), .y(t));
    assign y = t;
`endif
endmodule

module top(input [7:0] x, output [7:0] ya, output [7:0] yb);
    (* uf_instance = "f" *) box ua(.a(x), .y(ya));
    (* uf_instance = "f" *) box ub(.a(x), .y(yb));
    always @* assert (ya == yb);
endmodule

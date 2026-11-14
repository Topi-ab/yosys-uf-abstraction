// A marked box (ua and ub share the symbol f) whose outputs depend on bits that
// are not a function of the box inputs. The non-UF design fails (ya == yb FAILs,
// each instance has its own free bits); with uf_instance both instances are the
// same function, so without the check the result would be a false PASS.
//   UNCONN      input b of the submodule left unconnected in the box
//   DEEP        the same two levels deeper (box.m.s)
//   (default)   fully connected control; PARTIAL case: the test connects 4 of
//               the 8 bits of b (connect -port)
//   UNDRIVEN_IN input b of the submodule connected to an undriven wire
//   BB          unmarked blackbox instance in the box
//   BB_UF       blackbox instance marked with uf_instance in the box (nested UF, OK)
module leaf(input [7:0] a, input [7:0] b, output [7:0] y);
    assign y = a ^ b;
endmodule

module mid(input [7:0] a, output [7:0] y);
`ifdef DEEP
    leaf s(.a(a), .y(y));
`else
    leaf s(.a(a), .b(a), .y(y));
`endif
endmodule

(* blackbox *)
module bbx(input [7:0] a, output [7:0] y);
endmodule

module box(input [7:0] a, output [7:0] y);
`ifdef UNCONN
    leaf s(.a(a), .y(y));
`elsif DEEP
    mid m(.a(a), .y(y));
`elsif UNDRIVEN_IN
    wire [7:0] n;
    leaf s(.a(a), .b(n), .y(y));
`elsif BB
    bbx s(.a(a), .y(y));
`elsif BB_UF
    (* uf_instance = "inner" *) bbx s(.a(a), .y(y));
`else
    leaf s(.a(a), .b(a), .y(y));
`endif
endmodule

module top(input [7:0] x, output [7:0] ya, output [7:0] yb);
    (* uf_instance = "f" *) box ua(.a(x), .y(ya));
    (* uf_instance = "f" *) box ub(.a(x), .y(yb));
    always @* assert (ya == yb);
endmodule

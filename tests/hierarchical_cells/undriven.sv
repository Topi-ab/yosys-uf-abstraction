// A box that is not a function of its inputs. An undriven bit is free in every
// step (like $anyseq), so a UF does not over-approximate the box.
// Default: undriven wire directly in the box. NESTED: in an ordinary submodule,
// WB_SUB: in a (* whitebox *) submodule. LATCH: a latch (async2sync / clk2fflogic
// turns it into a $ff). INIT: $initstate.
module box(input [7:0] a, output [7:0] y);
`ifdef NESTED
    sub s(.a(a), .y(y));
`elsif WB_SUB
    sub s(.a(a), .y(y));
`elsif LATCH
    reg [7:0] l;
    always @* if (a[0]) l = a;
    assign y = l;
`elsif INIT
    assign y = a ^ {7'd0, $initstate};
`else
    wire [7:0] n;
    assign y = a ^ n;
`endif
endmodule

`ifdef WB_SUB
(* whitebox *)
`endif
module sub(input [7:0] a, output [7:0] y);
    wire [7:0] n;
    assign y = a ^ n;
endmodule

module top(input clk, input [7:0] x, output [7:0] ya, output [7:0] yb);
    (* uf_instance = "f" *) box ua(.a(x), .y(ya));
    (* uf_instance = "f" *) box ub(.a(x), .y(yb));
    always @* assert (ya == yb);
endmodule

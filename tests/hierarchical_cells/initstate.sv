// The smtlib2_comb_expr refers to the initial-state flag (|smtis_is| state): in the
// first step y = a, otherwise ~a. The box is not a function of its inputs.
//   mark    box marked with uf_instance -> error (would otherwise be a false PASS)
//   nomark  unmarked control: the assertion prev == ya fails (FAIL)
(* blackbox *)
(* smtlib2_module *)
module smtis(input [7:0] a, (* smtlib2_comb_expr = "(ite (|smtis_is| state) a (bvnot a))" *) output [7:0] y);
endmodule

module box(input [7:0] a, output [7:0] y);
    smtis s(.a(a), .y(y));
endmodule

module top(input clk, output [7:0] ya);
    (* anyconst *) reg [7:0] x;
    (* uf_instance = "f" *) box ua(.a(x), .y(ya));
    reg pv = 0;
    reg [7:0] prev;
    always @(posedge clk) begin
        pv <= 1;
        prev <= ya;
        if (pv) assert (prev == ya);
    end
endmodule

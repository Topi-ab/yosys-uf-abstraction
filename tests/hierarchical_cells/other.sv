// An instance inside the box that is not an ordinary module.
//   An unmarked smtlib2_module instance (blackbox or whitebox) in the output cone of
//   the box is always an error: yosys cannot verify that the user-written SMT-LIB
//   (smtlib2_comb_expr) is a function of the inputs (the expression may refer to state).
//   SMTLIB2  unmarked smtlib2_module blackbox (smtlib2_comb_expr) -> error
//   WB       unmarked whitebox instance: write_smt2 does not export whitebox modules,
//            so a direct export would refer to an undefined sort -> error
//   WB_UF    whitebox instance marked with uf_instance (nested UF) -> accepted
//   SMTLIB2_LOOP  loop through a marked smtlib2_module instance (t = a + t): the
//            instance is conservatively "every output depends on every input"
//            -> loop error
//   WB_DEEP  unmarked whitebox in a submodule (box.m.s) -> error
//   SMT_NOEXPR  unmarked smtlib2_module whose read output has no
//            smtlib2_comb_expr: write_smt2 exports it as a free function of the state
//            (declare-fun |m#N| (|m_s|) ...) -> error (would otherwise be a false PASS)
//   SMT_NOEXPR_DEEP  the same in a submodule (box.m.s) -> error
//   SMT_HALF the box reads output z of the smtlib2_module, which has no expression -> error
//   SMT_HALF_OK  the box reads only output y, which has an expression -> error
//   SMT_FULL two outputs, both with smtlib2_comb_expr -> error
//   SMT_STATEREF  the expression refers to state, (|smtsr_n y| state) -> error
//            (would otherwise be a false PASS)
//   SMT_STATEREF2 the expression (bvadd a (|smtsr2_n a| state)) -> error
//   SMT_WB   unmarked whitebox smtlib2_module -> error naming the smtlib2_module
//   SMT_UF   smtlib2_module blackbox marked with uf_instance (nested UF) -> accepted
//   SMT_WB_UF  whitebox smtlib2_module marked with uf_instance -> accepted
(* blackbox *)
(* smtlib2_module *)
module smtadd(input [7:0] a, input [7:0] b, (* smtlib2_comb_expr = "(bvadd a b)" *) output [7:0] y);
endmodule

(* blackbox *)
(* smtlib2_module *)
module smtnoexpr(input [7:0] a, output [7:0] y);
endmodule

(* blackbox *)
(* smtlib2_module *)
module smthalf(input [7:0] a, (* smtlib2_comb_expr = "a" *) output [7:0] y, output [7:0] z);
endmodule

(* blackbox *)
(* smtlib2_module *)
module smtfull(input [7:0] a, input [7:0] b, (* smtlib2_comb_expr = "(bvxor a b)" *) output [7:0] x,
               (* smtlib2_comb_expr = "(bvand a b)" *) output [7:0] y);
endmodule

(* blackbox *)
(* smtlib2_module *)
module smtsr(input [7:0] a, output [7:0] y, (* smtlib2_comb_expr = "(|smtsr_n y| state)" *) output [7:0] z);
endmodule

(* blackbox *)
(* smtlib2_module *)
module smtsr2(input [7:0] a, (* smtlib2_comb_expr = "(bvadd a (|smtsr2_n a| state))" *) output [7:0] z);
endmodule

(* whitebox *)
(* smtlib2_module *)
module smtwb(input [7:0] a, (* smtlib2_comb_expr = "(bvnot a)" *) output [7:0] y);
endmodule

module smid(input [7:0] a, output [7:0] y);
    smtnoexpr s(.a(a), .y(y));
endmodule

(* whitebox *)
module wbx(input [7:0] a, output [7:0] y);
    assign y = ~a;
endmodule

module wmid(input [7:0] a, output [7:0] y);
    wbx s(.a(a), .y(y));
endmodule

module box(input [7:0] a, output [7:0] y);
`ifdef SMTLIB2
    smtadd s(.a(a), .b(a), .y(y));
`elsif SMTLIB2_LOOP
    wire [7:0] t;
    (* uf_instance = "inner" *) smtadd s(.a(a), .b(t), .y(t));
    assign y = t;
`elsif SMT_NOEXPR
    smtnoexpr s(.a(a), .y(y));
`elsif SMT_NOEXPR_DEEP
    smid m(.a(a), .y(y));
`elsif SMT_HALF
    wire [7:0] u;
    smthalf s(.a(a), .y(u), .z(y));
`elsif SMT_HALF_OK
    wire [7:0] u;
    smthalf s(.a(a), .y(y), .z(u));
`elsif SMT_FULL
    wire [7:0] p, q;
    smtfull s(.a(a), .b(~a), .x(p), .y(q));
    assign y = p ^ q;
`elsif SMT_STATEREF
    smtsr s(.a(a), .y(), .z(y));
`elsif SMT_STATEREF2
    smtsr2 s(.a(a), .z(y));
`elsif SMT_WB
    smtwb s(.a(a), .y(y));
`elsif SMT_UF
    (* uf_instance = "inner" *) smtadd s(.a(a), .b(a), .y(y));
`elsif SMT_WB_UF
    (* uf_instance = "inner" *) smtwb s(.a(a), .y(y));
`elsif WB_DEEP
    wmid m(.a(a), .y(y));
`elsif WB_UF
    (* uf_instance = "inner" *) wbx s(.a(a), .y(y));
`else
    wbx s(.a(a), .y(y));
`endif
endmodule

module top(input [7:0] x, output [7:0] ya, output [7:0] yb);
    (* uf_instance = "f" *) box ua(.a(x), .y(ya));
    (* uf_instance = "f" *) box ub(.a(x), .y(yb));
    always @* assert (ya == yb);
endmodule

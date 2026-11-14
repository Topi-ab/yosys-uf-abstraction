// UF width experiment: effect of the argument width (WI) and the return value
// width (WO) on the BMC time of a UF-abstracted model.
//
// Structure as in vhdl_control_independence_setattr: the same N-stage
// pipeline twice (channels A and B), each with its own free valid sequence.
// The input is an uninterpreted function of the beat index, stim(icnt), so
// the channels see the same logical sequence on different clock cycles.
// Claim: the output beats of A and B at the symbolic index j are equal. Since
// the timing of the channels is free, the equality is not syntactic: the
// solver has to use congruence over a chain of N box applications at
// different time steps (2*N applications per step).
//
// BAD: the input of B is stim(icnt_b + 1) (an off-by-one beat error): a
// counterexample exists both with the UF and with an interpreted multiplication.
//
// UF_MODE (parameter of top, the sby gives the value with chparam): 1 = the box
// instances are uninterpreted functions (mul), 0 = the marks are switched off
// (uf_disable = !UF_MODE) and the box is an interpreted multiplication. stim is
// always a UF.

module box #(
    parameter WI = 10,
    parameter WO = 10
) (
    input  [WI-1:0] a_in,
    input  [WI-1:0] b_in,
    output [WO-1:0] y_out
);
    // Own implementation (nouf run only, UF_MODE = 0): the product truncated/extended to WO.
    wire [2*WI-1:0] p = a_in * b_in;
    assign y_out = p;
endmodule

// Stimulus as a function of the beat index (always a UF; the implementation body is only a placeholder).
module stim #(
    parameter CW = 16,
    parameter WI = 10
) (
    input  [CW-1:0] idx_in,
    output [WI-1:0] data_out
);
    assign data_out = {(WI + CW - 1) / CW {idx_in ^ 16'h5a3c}};
endmodule

module chan #(
    parameter WI = 10,
    parameter WO = 10,
    parameter N = 4,
    parameter CW = 16,
    parameter OFS = 0,
    parameter UF_MODE = 1
) (
    input clk,
    input valid_in,
    output reg valid_out = 0,
    output [WO-1:0] data_out,
    output reg [CW-1:0] ocnt_out = 0
);
    reg [CW-1:0] icnt = 0;
    wire [WI-1:0] d0;
    (* uf_instance = "stim" *) stim #(.CW(CW), .WI(WI)) us (
        .idx_in(icnt + OFS),
        .data_out(d0)
    );

    // Stage k: acc[k] = box(acc[k-1] fitted to WI, d[k-1]); stage 0: box(d0, d0).
    reg [N*WO-1:0] acc = 0;
    reg [N*WI-1:0] d = 0;
    reg [N-1:0] v = 0;
    wire [N*WO-1:0] y;

    genvar k;
    generate
        for (k = 0; k < N; k = k + 1) begin : st
            wire [WI-1:0] fa;
            wire [WI-1:0] fb;
            if (k == 0) begin : first
                assign fa = d0;
                assign fb = d0;
            end else begin : rest
                assign fa = acc[(k-1)*WO +: WO];
                assign fb = d[(k-1)*WI +: WI];
            end
            (* uf_instance = "mul", uf_disable = !UF_MODE *) box #(.WI(WI), .WO(WO)) ub (
                .a_in(fa),
                .b_in(fb),
                .y_out(y[k*WO +: WO])
            );
        end
    endgenerate

    always @(posedge clk) begin
        if (valid_in)
            icnt <= icnt + 1;
        v <= {v[N-2:0], valid_in};
        d <= {d[(N-1)*WI-1:0], d0};
        acc <= y;
        valid_out <= v[N-1];
        if (valid_out)
            ocnt_out <= ocnt_out + 1;
    end
    assign data_out = acc[(N-1)*WO +: WO];
endmodule

module top #(
    parameter WI = 10,
    parameter WO = 10,
    parameter N = 4,
    parameter CW = 16,
    parameter UF_MODE = 1
) (
    input clk,
    input valid_a_in,
    input valid_b_in
);
    (* anyconst *) reg [CW-1:0] j;

    wire va, vb;
    wire [WO-1:0] ra, rb;
    wire [CW-1:0] oa, ob;

    chan #(.WI(WI), .WO(WO), .N(N), .CW(CW), .OFS(0), .UF_MODE(UF_MODE)) a (
        .clk(clk),
        .valid_in(valid_a_in),
        .valid_out(va),
        .data_out(ra),
        .ocnt_out(oa)
    );

`ifdef BAD
    chan #(.WI(WI), .WO(WO), .N(N), .CW(CW), .OFS(1), .UF_MODE(UF_MODE)) b (
`else
    chan #(.WI(WI), .WO(WO), .N(N), .CW(CW), .OFS(0), .UF_MODE(UF_MODE)) b (
`endif
        .clk(clk),
        .valid_in(valid_b_in),
        .valid_out(vb),
        .data_out(rb),
        .ocnt_out(ob)
    );

    reg seen_a = 0;
    reg seen_b = 0;
    reg [WO-1:0] cap_a = 0;
    reg [WO-1:0] cap_b = 0;
    always @(posedge clk) begin
        if (va && oa == j) begin
            seen_a <= 1;
            cap_a <= ra;
        end
        if (vb && ob == j) begin
            seen_b <= 1;
            cap_b <= rb;
        end
    end

    always @*
        if (seen_a && seen_b)
            a_match: assert (cap_a == cap_b);
endmodule

// wreduce path: two 16-bit f multiplications of which only the low byte is read.
// As a 16-bit UF, f(a,b)[7:0] also depends on the high byte of a, so
// a[7:0] == c[7:0] is not sufficient -> expected FAIL. FULL: the whole result is an output.
module b_wreduce (
    input  [15:0] a_in,
    input  [15:0] b_in,
    input  [15:0] c_in,
`ifdef FULL
    output [15:0] p_out,
    output [15:0] q_out
`else
    output [7:0]  p_out,
    output [7:0]  q_out
`endif
);
    wire [15:0] p = a_in * (* uf_instance = "f" *) b_in;
    wire [15:0] q = c_in * (* uf_instance = "f" *) b_in;

`ifdef FULL
    assign p_out = p;
    assign q_out = q;
`else
    assign p_out = p[7:0];
    assign q_out = q[7:0];
`endif

    always @* if (a_in[7:0] == c_in[7:0]) assert (p[7:0] == q[7:0]);
endmodule

// opt_merge path: a marked $mul (f) and an unmarked $mul with the same inputs.
// The unmarked use is interpreted: b == 1 -> a * b == a -> expected PASS.
module b_merge_one (
    input  [7:0] a_in,
    input  [7:0] b_in,
    output [7:0] pf_out
);
    wire [7:0] pc;

    assign pf_out = a_in * (* uf_instance = "f" *) b_in;
    assign pc = a_in * b_in;

    always @* if (b_in == 8'd1) assert (pc == a_in);
endmodule

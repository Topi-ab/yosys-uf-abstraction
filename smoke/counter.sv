module counter (
    input  logic clk,
    input  logic rst,
    output logic [7:0] cnt
);
    always_ff @(posedge clk)
        if (rst) cnt <= 8'd0;
        else     cnt <= cnt + 8'd1;

`ifdef FORMAL
    logic past_valid = 1'b0;
    always_ff @(posedge clk) past_valid <= 1'b1;

    always_ff @(posedge clk)
        if (past_valid && $past(rst)) assert (cnt == 8'd0);
`endif
endmodule

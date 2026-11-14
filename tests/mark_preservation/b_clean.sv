// opt_clean path, built-in cell: the result of the marked $mul is never read.
module b_clean (
    input  [7:0] a_in,
    input  [7:0] b_in,
    output [7:0] y_out
);
    wire [7:0] p = a_in * (* uf_instance = "f" *) b_in;

    assign y_out = a_in ^ b_in;
endmodule

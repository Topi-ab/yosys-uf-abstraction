// Arguments and outputs follow the module's port order (port_id),
// not the instance's connection order or the port widths.
module wbox(input [15:0] b_in, input [7:0] a_in, output [7:0] y1_out, output [3:0] y0_out);
    assign y1_out = b_in[7:0] ^ a_in;
    assign y0_out = a_in[3:0];
endmodule

module top(input [7:0] x, input [15:0] z, output [7:0] p, output [3:0] q);
    (* uf_instance = "w" *) wbox u(.y0_out(q), .a_in(x), .y1_out(p), .b_in(z));
endmodule

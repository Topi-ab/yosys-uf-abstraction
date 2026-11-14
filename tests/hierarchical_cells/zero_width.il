# Zero-width ports (RTLIL: Verilog does not produce width-0 ports).
# box: a zero-width input and output between 8-bit ones. ua leaves them out,
#   ub connects them to empty { }. Expected: (declare-fun |f| ((_ BitVec 8)) (_ BitVec 8)),
#   no "not connected" error for z_in.
# zin: the only input is zero-width -> zero-argument |k|.
# nobox: the only output is zero-width -> "module has no output ports".
module \box
  wire width 0 input 1 \z_in
  wire width 8 input 2 \a
  wire width 0 output 3 \z_out
  wire width 8 output 4 \y
  connect \y \a
end
module \zin
  wire width 0 input 1 \z_in
  wire width 8 output 2 \y
  connect \y 8'00000111
end
module \nobox
  wire width 8 input 1 \a
  wire width 0 output 2 \z_out
end
module \top
  wire width 8 input 1 \x
  wire width 8 output 2 \ya
  wire width 8 output 3 \yb
  wire width 8 output 4 \yk
  attribute \uf_instance "f"
  cell \box \ua
    connect \a \x
    connect \y \ya
  end
  attribute \uf_instance "f"
  cell \box \ub
    connect \z_in { }
    connect \a \x
    connect \z_out { }
    connect \y \yb
  end
  attribute \uf_instance "k"
  cell \zin \uk
    connect \z_in { }
    connect \y \yk
  end
  attribute \keep 1
  attribute \uf_instance "g"
  cell \nobox \un
    connect \a \x
  end
end

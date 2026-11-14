# Uninterpreted functions for Yosys/SymbiYosys formal verification

This repository extends the open-source formal verification flow
(GHDL + ghdl-yosys-plugin + Yosys + SymbiYosys) with **uninterpreted functions (UFs)**.

A datapath operator or a whole datapath block is marked with the attribute `uf_instance`.
Yosys's SMT-LIBv2 backend (`write_smt2`) then exports it as an uninterpreted function: a
symbol whose only property is that **equal inputs give equal outputs**. Control logic, FSMs
and handshakes stay bit-accurate, while the proof no longer depends on what the datapath
computes.

Typical uses:

- **Control/data independence:** prove that the data delivered by a design does not depend
  on its control sequence (back-pressure, stalls, valid patterns), for every possible
  datapath function, and that the control signals do not depend on the data.
- **Solver performance:** a multiplier on symbolic data is expensive for a bit-vector solver.
  As a UF it costs only congruence reasoning, and its width hardly matters.
- **Memory-free checkers:** a testbench generates stimulus as a UF of the beat index and
  checks every output beat against the same function of the output beat index, without a
  reference model or a scoreboard queue.

## Quick start (prebuilt image, no build)

```bash
git clone https://github.com/Topi-ab/yosys-uf-abstraction.git    # no --recurse-submodules needed
cd yosys-uf-abstraction
export TC_IMAGE=ghcr.io/topi-ab/yosys-uf-abstraction:v0.1.1      # complete toolchain, about 470 MB
docker pull "$TC_IMAGE"
./tc.sh yosys -V                                # check the toolchain
./tc.sh pytest smoke tests/builtin_cells        # a few seconds
./tc.sh pytest -n auto                          # default suite: about 1060 tests, ~20 min on 4 cores
```

`tc.sh` runs a command in the image as the calling user with the current directory mounted,
so run it from the repository root. See [Running the tests with the prebuilt
image](#running-the-tests-with-the-prebuilt-image-no-local-build) for which image to choose.

## What is included

| component | branch | change |
|---|---|---|
| [`ext/yosys`](https://github.com/Topi-ab/yosys) | `uf-blackbox` | `write_smt2`: `uf_instance` for built-in arithmetic cells and hierarchical cells, signature and safety checks, `uf_disable` to switch a mark off; `hierarchy -smtcheck` accepts marked blackbox instances; `yosys-smtbmc` keeps UF logic in unroll mode |
| [`ext/ghdl-yosys-plugin`](https://github.com/Topi-ab/ghdl-yosys-plugin) | `uf-blackbox` | VHDL instance (label) attributes are carried to the RTLIL cell |
| `ext/ghdl`, `ext/sby`, `ext/yices2`, `ext/z3`, `ext/bitwuzla` | upstream | unmodified |
| `ext/boolector`, `ext/cvc5` | upstream releases | unmodified, included as sources for additional SMT solvers (not built by default) |

Everything else in this repository is the Docker-based build, wrapper scripts and the test
suite.

### Upstream versions

The forks are based on these upstream commits; the `uf-blackbox` branches add the changes
above on top of them:

| fork | upstream | base commit | fork commits |
|---|---|---|---|
| `ext/yosys` | [YosysHQ/yosys](https://github.com/YosysHQ/yosys) `main` | `567837f` (2026-11-13, Yosys 0.71+) | `519b53e` built-in cells, `c365d92` hierarchical cells, `a893651` `uf_instance` attribute and box checks, `f1bb92d` `uf_disable` attribute |
| `ext/ghdl-yosys-plugin` | [ghdl/ghdl-yosys-plugin](https://github.com/ghdl/ghdl-yosys-plugin) `master` | `c21051d` (2026-11-02) | `25df6d8` instance attributes |

The unmodified submodules are pinned to:

| submodule | upstream | commit |
|---|---|---|
| `ext/ghdl` | [ghdl/ghdl](https://github.com/ghdl/ghdl) `master` | `8e642a9` (2026-11-11) |
| `ext/sby` | [YosysHQ/sby](https://github.com/YosysHQ/sby) | `v0.71` (`79fc9ed`) |
| `ext/yices2` | [SRI-CSL/yices2](https://github.com/SRI-CSL/yices2) `master` | `195552c` (2026-11-12) |
| `ext/z3` | [Z3Prover/z3](https://github.com/Z3Prover/z3) `master` | `de3ccca` (2026-11-12) |
| `ext/bitwuzla` | [bitwuzla/bitwuzla](https://github.com/bitwuzla/bitwuzla) | `0.9.1` (`8d1eb01`) |
| `ext/boolector` | [Boolector/boolector](https://github.com/Boolector/boolector) | `3.2.4` |
| `ext/cvc5` | [cvc5/cvc5](https://github.com/cvc5/cvc5) | `cvc5-1.4.2` |

## Marking

The attribute value is the **function symbol name** and must be a string. Cells that share
a name share the function. The mark always goes on the **instance** (cell), never on the
module: a module attribute would apply to every instance, including ones that must keep
their actual semantics, so `write_smt2` warns about it and ignores it.

### VHDL: a datapath block as a hierarchical cell

Mark the **instance label**. The attribute is declared and specified in the declarative part
of the architecture (before `begin`); the instance it names is in the statement part (after
`begin`):

```vhdl
architecture rtl of dsp is
    signal f_out : signed(15 downto 0);

    attribute uf_instance : string;
    attribute uf_instance of u_f : label is "dsp_f";
begin
    u_f : entity work.dsp_f
        port map (
            data_in  => data_in,
            data_out => f_out
        );
    ...
end architecture;
```

Inside a `for ... generate`, declare the attribute in the generate's declarative part; every
generated instance then calls the same function:

```vhdl
gen_tap : for k in 0 to TAPS - 1 generate
    attribute uf_instance of u_mul : label is "cmul";
begin
    u_mul : entity work.cmul
        port map (
            ...
        );
end generate;
```

### Verilog / SystemVerilog

```verilog
(* uf_instance = "dsp_f" *) dsp_f u_f (.data_in(data_in), .data_out(f_out));

assign p = a * (* uf_instance = "mul16" *) b;   // a built-in operator
```

### From the Yosys script (design sources untouched)

A cell that synthesis creates from an expression (for example the `$mul` of `a * b` in VHDL)
has no source name to attach an attribute to. `setattr` sets the same RTLIL attribute:

```
setattr -set uf_instance "mul16" dsp_Brtl/t:$mul
setattr -set uf_instance "dsp_f" t:dsp_f_Brtl     # every instance of a module (GHDL appends _Brtl)
```

To run the same design without the source marks, do not remove them in the script; switch
them off with `uf_disable` from a generic or parameter (next section).

### Switching a mark off: `uf_disable`

Whether a run uses UFs or the non-UF model is an elaboration choice, so it is made with a
generic or parameter. A second attribute `uf_disable` on the same cell switches the
`uf_instance` mark off. In VHDL both attributes are declared and specified next to each
other in the declarative part of the architecture:

```vhdl
architecture rtl of dsp is
    attribute uf_instance : string;
    attribute uf_disable  : boolean;
    attribute uf_instance of u_sum : label is "csum";
    attribute uf_disable  of u_sum : label is not UF_MODE;
begin
    u_sum : entity work.csum
        port map (
            ...
        );
end architecture;
```

In Verilog, on an instance or on an operator:

```verilog
(* uf_instance = "csum", uf_disable = !UF_MODE *) csum u_sum (...);

assign s = a + (* uf_instance = "csum", uf_disable = !UF_MODE *) b;
```

- A missing `uf_disable` is false. When it is true, `write_smt2` exports the cell **exactly
  as an unmarked cell**: no `declare-fun`, none of the box checks, the normal (interpreted)
  semantics. The symbol name is still validated, so a typo is found in both modes.
- Accepted values are the boolean forms the frontends produce: integer and bit constants
  (a VHDL boolean from GHDL, `(* uf_disable *)`, `= 1`, `= 0`, `= !P`, `= 1'b1` in Verilog)
  and the strings `"true"`/`"false"` (any case), `"1"` and `"0"`. Any other value is an
  error, so a typo cannot silently switch between the two exports.
- `uf_disable` true on an instance of a blackbox or whitebox module (other than an
  `smtlib2_module`) is an error: such a module has no implementation that could be exported
  instead. `hierarchy -smtcheck` then rejects the instance like any unmarked blackbox
  instance.
- `uf_disable` on a cell without `uf_instance`, or on a module, has no effect and gives a
  warning (also for instances dissolved by `flatten`).

The sby script then only passes the value: `ghdl ... -gUF_MODE=false ...` for VHDL, or
`hierarchy -chparam UF_MODE 0 ...` (or `chparam`) for Verilog. The marks stay in the
sources and in RTLIL in both modes.

## What `write_smt2 -bv` emits

For each symbol, exactly one declaration for the whole file, placed before its first use:

```smt2
(declare-fun |dsp_f| ((_ BitVec 16)) (_ BitVec 16)) ; uf_instance, first use: dsp_Brtl.u_f (module dsp_f_Brtl): args data_in[16] -> data_out[15:0]
(= (|dsp_Brtl#8| state) (|dsp_f| (|dsp_Brtl#1| state)))
```

### Built-in cells

`$add`, `$sub`, `$mul`, `$neg`, `$div`, `$mod`, `$divfloor`, `$modfloor`. The operands are
extended to the width the non-UF export would use, and the result is narrowed to the
output width as usual. Signedness and cell type are not part of the function signature.

### Hierarchical cells (instances of user or blackbox modules)

- **Arguments:** the input ports in module port order, each at its full port width.
- **Result:** the concatenation of all output ports in port order, **first output in the most
  significant bits**; each output is an `extract` of the call. A box with several outputs
  (for example the real and imaginary part of a complex multiplier) is therefore one
  function with tuple semantics, without SMT datatypes, so it works with every solver.
- The submodule contributes **no state and no hierarchy equations**; the instance is not
  listed as a `yosys-smt2-cell`. Unmarked instances of the same module keep the normal
  hierarchical export.
- **Submodules and nested functions:** a box may contain instances of other modules; their
  contents are checked like the box itself. A blackbox, whitebox or `smtlib2_module` instance
  inside a box is accepted when it is itself marked with `uf_instance` (a nested UF), since
  the box is then still a function of its inputs.
- **Blackbox targets:** a marked instance of a blackbox module (no RTLIL contents) is
  exported as a UF and passes `hierarchy -smtcheck`, so a datapath block can be abstracted
  without its implementation being available.
- Feedback through a box (an output wired back to an input of the same box) is supported.
- A box with no inputs becomes a free constant (`(declare-fun |k| () ...)`). Zero-width
  ports carry no data and are not part of the signature.
- Witness: each UF output gets a `blackbox` witness entry, so `--dump-yw` traces contain the
  UF values and `yosys-smtbmc --check-witness` replays counterexamples.
- Works with the default state encoding, `-stbv` and `-stdt`.

## Guarantees: what `write_smt2` checks on marked cells

A UF over-approximates the marked logic only if that logic is a deterministic function of
its current inputs. `write_smt2` checks this for every marked box and **stops with an error**
otherwise, so a mark can never turn into a silent false PASS:

- **No state or nondeterminism inside the box:** no flip-flops, latches, memories,
  `$anyseq`/`$anyconst`/`$allseq`/`$allconst`/`$anyinit`, `$initstate`, formal cells
  (`$assert`, `$cover`, `$live`, `$fair`) or unprocessed processes.
- **Every output bit is a function of the inputs:** no undriven wires in the cone of the
  outputs, no unconnected inputs of submodules, no combinational loops through the box.
- **Every submodule has known semantics:** an unmarked blackbox, whitebox or
  `smtlib2_module` instance inside a box is rejected (mark it as a nested UF instead).
- **Well-formed interface:** every input of the box is connected at its full width; inout
  ports and parametric blackbox targets are rejected.
- **Consistent signatures:** all uses of one symbol agree on argument widths, on the split of
  the result into outputs and on port order; two modules whose ports have the same names in
  a different order cannot share a symbol. A built-in cell and a hierarchical cell may share
  a symbol when the widths match.
- **Valid symbol names:** a symbol must be a plain SMT-LIB identifier and must not collide
  with an SMT-LIB or Z3 reserved name (`bvadd`, `bvredor`, ...) or with a name the backend
  generates itself.
- **`-bv` is required** whenever a mark is present.

Every mark that `write_smt2` cannot export as a UF is **named in a warning** (a mark switched
off with `uf_disable` is intentional and gives none) and keeps its
actual semantics: an unsupported cell type, a box without outputs, a mark on a module, a
marked instance dissolved by `flatten`, a mark inside a module that is not written. Further
warnings point out a UF argument that is a clock in the parent and an `$assume` inside a box
(it is dropped). A run without `uf_instance` warnings has abstracted every mark that reached
`write_smt2`.

## Keeping a mark alive through synthesis passes

A mark is honoured only if the cell still exists when `write_smt2` runs. Protection that
works in the usual flow:

| pass | effect on an unprotected marked cell | protection |
|---|---|---|
| `opt_clean` | removes a cell whose output is unused | `keep` on the cell (built-in or hierarchical) or on a hierarchical cell's module; `keep` on the output wire |
| `opt_merge` | merges identical cells (attributes are not compared) | `keep` on **all** identical cells |
| `flatten` | dissolves a hierarchical cell | `keep_hierarchy` on the cell or its module |
| `wreduce` | narrows a built-in cell to the result bits that are used | `keep` on the output wire |

Because `opt_merge` does not compare attributes, two otherwise identical cells that use the
same symbol but have different `uf_disable` values can be merged into one, and which of the
two marks survives depends on the source order. Put `keep` on both cells in that case.

In VHDL, `keep` and `keep_hierarchy` can be given as boolean **entity** attributes; GHDL turns
them into module attributes. The `uf_instance` mark itself goes on the instance label.

`select -assert-count N a:uf_instance=<name>` right after `prep` in the sby script fails
loudly if a mark was lost or duplicated during the user script.

## Example sby

```
[tasks]
bmc_uf
bmc_nouf

[options]
mode bmc
depth 20

[engines]
smtbmc bitwuzla

[script]
plugin -i ghdl
bmc_uf:   ghdl --std=08 -gUF_MODE=true  dsp.vhdl tb_formal.vhdl -e tb_formal
bmc_nouf: ghdl --std=08 -gUF_MODE=false dsp.vhdl tb_formal.vhdl -e tb_formal
bmc_uf:   setattr -set uf_instance "mul16" dsp_Brtl/t:$mul
bmc_uf:   setattr -set keep 1 dsp_Brtl/t:$mul
prep -top tb_formal
bmc_uf:   select -assert-count 1 a:uf_instance=mul16

[files]
dsp.vhdl
tb_formal.vhdl
```

The testbench marks are VHDL label attributes with `uf_disable = not UF_MODE`, so the
`-gUF_MODE` value alone selects the model; only the `$mul` cell that synthesis creates is
marked from the script, in the UF task.

**Bitwuzla** (0.9.1) is the default solver of the whole test suite: on the UF models it was
the fastest of the bundled solvers (BMC of the control-independence testbench at depth 24:
bitwuzla 23 s, z3 50 s, yices 162 s). Yices and Z3 work as well.

## Testbench patterns

The VHDL examples in `tests/` share a few patterns that make UF proofs both sound and
provable by induction.

### Defining a free function with an assumption (`UF_MODE`)

To check that a design's output does not depend on its control sequence, the testbench runs
two copies of the DUT on the same stimulus `stim_f(beat index)`: copy A at full rate, copy B
with arbitrary stalls. `stim_f` is a UF as well, and both copies call the same symbol with
their own input beat index. That is exactly why A and B see the same input sequence: equal
indices give equal data (congruence), although the solver is free to choose what the data
is, so the check holds for every input sequence, and B's beat k carries A's beat k even when
B accepts it in a different clock cycle. The expected output `out_f(beat index)` is a UF
that is *defined* by copy A with an assumption and *checked* on copy B with an assertion. An
assumption that defines a free function constrains nothing: for every behaviour of copy A
there is a function `out_f` that matches it.

The same condition must not stay an assumption when the marks are switched off and `out_f`
is a fixed, interpreted function: then it would prune the paths on which the DUT deviates and
hide data errors. One boolean generic `UF_MODE` therefore drives both choices: the
`uf_disable` attributes of the marks and the keyword of the condition, which is written
once:

```vhdl
generic (
    UF_MODE : boolean := false    -- set by the sby task: -gUF_MODE=true|false
);
...
attribute uf_instance : string;
attribute uf_disable  : boolean;
attribute uf_instance of u_out_a : label is "out_f";
attribute uf_disable  of u_out_a : label is not UF_MODE;
...
a_def_ok <= '0' when armed = '1' and yvalid_a = '1' and a_res /= ufout_a else '1';

g_uf : if UF_MODE generate
    a_define : assume always a_def_ok = '1';        -- out_f is free: defined by copy A
end generate;
g_nouf : if not UF_MODE generate
    a_define_chk : assert always a_def_ok = '1';    -- out_f is interpreted: checked
end generate;
```

The default `false` is the safe direction: if the `-g` option is forgotten, the marks are
off and the condition is an assertion. The testbench passes `UF_MODE` on to the DUT's generic
of the same name, so the DUT's own marks follow the same mode.

### Symbolic beat index and invariants for k-induction

The check on copy B is made at one **symbolic beat index** `j`, a free constant
(`anyconst`):

```vhdl
signal j : unsigned(15 downto 0);
attribute anyconst : boolean;
attribute anyconst of j : signal is true;
...
a_match : assert always
    (armed = '1' and yvalid_b = '1' and ocnt_b = j) -> (b_res = ufout_b);
```

This is equivalent to checking every beat (if beat `k` is wrong, the solver picks `j = k`),
but it turns a property that would need a quantifier over all pending beats into a single
flag and equation, which a finite inductive invariant can express. The auxiliary invariants
live in a PSL `vunit` bound to the testbench architecture and are analysed only in the
`prove` tasks, so the BMC tasks run the plain testbench:

```
prove_uf: ghdl --std=08 -gUF_MODE=true dsp.vhdl tb_dsp_formal.vhdl tb_dsp_formal_inv.psl -e tb_dsp_formal
```

With a handful of invariants (counter relations, ordering of the two copies, a bound on the
distance between them) k-induction proves the property for unbounded traces at k = 3.

### Vacuity covers

Assumption-based testbenches can pass vacuously when the assumptions contradict each other.
Every UF task in the suite comes with a `cover` that requires the checked behaviour to occur
(copy B delivers a beat that is checked against a beat produced by copy A), and the tests
check that the cover becomes unreachable when a contradictory assumption is injected.

## Measured results

All numbers are wall-clock times of complete sby runs on one machine (AMD Threadripper PRO,
bitwuzla 0.9.1, several runs in parallel), so they indicate orders of magnitude, not exact
figures.

| experiment | UF model | non-UF model |
|---|---|---|
| control-independence BMC, 16-bit multiplier datapath, depth 8 (`vhdl_control_independence_setattr`) | 0.26 s | 17.3 s (about 68x) |
| k-induction of the same property, datapath width 18 / 20 / 22 (`speedup_prove`) | 0.36 / 0.42 / 0.37 s | 24 / 125 / 756 s |
| k-induction, width 24..32 (`speedup_prove`) | 0.4 s | not finished in 30 min |
| complex FIR data independence BMC, 3 taps, 8 bits (`vhdl_fir_independence`) | 2.8 s (depth 10) | 189 s (depth 9, i.e. one step less) |
| complex FIR data independence by k-induction, up to 5 taps, 16 bits | 1.6 s | - |
| FIFO ordering and integrity by k-induction, depths 3..32 (`fifo_checkers`) | a few seconds | - |

With the multiplier as a UF, the k-induction time stays at about 0.4 s for every width from 4
to 32 bits, while the non-UF model grows about 5x per 2 bits of width from 16 bits on.

## Building and running

To run the tools and the tests, a plain clone and a prebuilt image are enough (see
[Quick start](#quick-start-prebuilt-image-no-build)): `--recurse-submodules` can be left out
when you only use the prebuilt image. The submodules are needed only to build the toolchain
yourself (see [Building with Docker](#building-with-docker)).

### Docker image

A prebuilt image with the complete toolchain is published on the GitHub Container Registry
for every version tag `v*` (`release` workflow): `:<version>` (for example `:v0.1.1`), and
`:latest` for tags without a pre-release suffix. Once the package is public, no login is needed:

```bash
docker pull ghcr.io/topi-ab/yosys-uf-abstraction:latest
```

Run it as the calling user, with the current directory mounted as the working directory:

```bash
docker run --rm --user "$(id -u):$(id -g)" \
    --mount type=bind,src="$PWD",dst=/work -w /work \
    ghcr.io/topi-ab/yosys-uf-abstraction:latest sby -f design.sby
```

The image contains GHDL with ghdl-yosys-plugin, Yosys (with `yosys-smtbmc`), SymbiYosys,
Yices 2, Z3 and Bitwuzla, plus Python 3 with pytest and pytest-xdist for the test suite. The
image label `toolchain.components` lists the exact submodule commit of every component:

```bash
docker inspect --format '{{ index .Config.Labels "toolchain.components" }}' \
    ghcr.io/topi-ab/yosys-uf-abstraction:latest
```

The bundled components keep their own licenses: GHDL is GPL-2.0-or-later,
ghdl-yosys-plugin and Yices are GPL-3.0-or-later, Yosys and SymbiYosys are ISC, Z3 and
Bitwuzla are MIT. The license files are included in the image under
`/opt/toolchain/share/licenses`.

### Running the tests with the prebuilt image (no local build)

The test suite can be run without building anything, with one of the images that the
workflows publish:

- the **CI toolchain image** `ghcr.io/topi-ab/yosys-uf-abstraction-toolchain:<hash>`, where
  `<hash>` is the output of `scripts/toolchain-hash.sh` for the checkout. The hash covers the
  submodule commits and the build files, so it identifies exactly the toolchain that CI built
  and tested for that commit. The script reads the submodule commits from the git index, so
  it works without initialising the submodules;
- the **release image** `ghcr.io/topi-ab/yosys-uf-abstraction:<version>` (for example
  `:v0.1.1`) or `:latest`. It contains the same toolchain as the CI toolchain image of the
  tagged commit. Both packages are public; no login is needed to pull them.

Which image to use: for a release tag (or `latest`), use the release image of that version;
for a checkout of `main` (or a pull request of this repository), use the CI toolchain image of
its hash. Both are about 470 MB. `tc.sh` and `sby.sh` use the image named by `TC_IMAGE`
(default: the locally built `yosys-uf/toolchain:latest`), so nothing is retagged:

```bash
git clone https://github.com/Topi-ab/yosys-uf-abstraction.git   # no --recurse-submodules needed
cd yosys-uf-abstraction
export TC_IMAGE=ghcr.io/topi-ab/yosys-uf-abstraction-toolchain:$(scripts/toolchain-hash.sh)
# or, for a release: export TC_IMAGE=ghcr.io/topi-ab/yosys-uf-abstraction:v0.1.1
docker pull "$TC_IMAGE"
./tc.sh yosys -V                       # check the toolchain
./tc.sh pytest smoke tests/builtin_cells   # a few seconds
./tc.sh pytest -n auto                 # default suite: about 1060 tests, ~20 min on 4 cores
./tc.sh pytest -m slow -n auto         # runs of minutes (non-UF reference runs)
./tc.sh pytest -m validation -n auto   # heavy proofs and larger parameter grids
```

`tc.sh` runs the given command in that image as the calling user (`-u $(id -u):$(id -g)`,
`HOME=/tmp`), with the current directory mounted at `/work`, so run it from the repository
root; files written by the tests belong to you. A CI toolchain image exists for every
toolchain hash that CI has built, that is, for commits on `main` and pull requests from this
repository; for other checkouts use the release image.

### Building with Docker

Everything is built and run inside Docker; nothing is installed on the host. The images pin
compilers and libraries, so results are reproducible. Building needs the submodules:

```bash
git clone --recurse-submodules https://github.com/Topi-ab/yosys-uf-abstraction.git
# (leave out --recurse-submodules if you only use the prebuilt image)
# or, in an existing clone: git submodule update --init --recursive
./build.sh                 # build all tools and the runtime image (takes a while)
./build.sh yosys           # rebuild one component: yosys|ghdl|ghdl-plugin|yices|z3|bitwuzla|sby
./build.sh shell           # interactive shell in the builder container
./tc.sh yosys -V           # run any tool in the runtime image (cwd mounted at /work)
./sby.sh -f design.sby     # run SymbiYosys
```

`build.sh` runs `scripts/build-all.sh` inside the builder container and installs into
`ext/_install`, which becomes `/opt/toolchain` in the runtime image `yosys-uf/toolchain`.
`tc.sh` mounts only the current directory, so run it from the directory that contains
everything the command needs (for the test suite: the repository root). ccache is used; its
cache lives in `ext/_ccache/`. Bitwuzla's build fetches its dependencies (CaDiCaL, SymFPU)
through meson wraps, so it needs network access.

### Native build

The same build script runs on a host. Install the dependencies (Ubuntu 24.04 package names):

```bash
sudo apt-get install build-essential clang bison flex gawk gperf git make cmake pkg-config \
    autoconf automake libtool libreadline-dev tcl-dev libffi-dev zlib1g-dev libgmp-dev \
    libboost-system-dev libboost-python-dev libboost-filesystem-dev gnat gnat-13 \
    python3 python3-dev python3-setuptools python3-click python3-pytest python3-pytest-xdist \
    ccache libmpfr-dev meson ninja-build python3-pyparsing python3-tomli python3-venv m4
```

Then build into a prefix of your choice and put it on `PATH`:

```bash
PREFIX=$HOME/uf-toolchain scripts/build-all.sh          # or: ... scripts/build-all.sh yosys
export PATH=$HOME/uf-toolchain/bin:$PATH
export LD_LIBRARY_PATH=$HOME/uf-toolchain/lib
```

`EXT` (source directory, default `ext/` next to the script) and `JOBS` (default `nproc`) can
be set in the environment as well. ghdl-yosys-plugin must be built against the same Yosys it
is loaded into, so build both from this repository.

## Tests

```bash
./tc.sh pytest -n auto                     # Docker
./tc.sh pytest tests/builtin_cells         # one directory
./tc.sh pytest -m "slow or validation" -n auto   # the long runs as well
pytest -n auto                             # native, with the toolchain on PATH
```

sby runs use temporary copies, so the test directories stay clean. Tests marked `slow`
(runs of minutes, such as the non-UF reference runs of the speed comparisons) and
`validation` (heavy proofs and larger parameter grids) are deselected by default.

Every end-to-end example also contains **mutation tests**: deliberately broken copies of the
DUT (wrong latency, data depending on the stall pattern, lost or duplicated beats, control
depending on data, ...) that the checker must reject. They show that a PASS of the checker
means something.

| directory | covers |
|---|---|
| `tests/builtin_cells/` | built-in cells: congruence, signature conflicts, warnings, invalid names, `uf_disable` |
| `tests/hierarchical_cells/` | hierarchical cells: multi-output layout, port order, the box checks (state, undriven bits, unconnected and unknown submodules, loops, inout ports, reserved names), nested functions, zero-input and zero-width cases, feedback, clocks, blackbox targets, witness replay, `-stbv`/`-stdt`/unroll mode, `uf_disable` (values, errors, warnings, `hierarchy -smtcheck`) |
| `tests/mark_preservation/` | how `keep`, `keep_hierarchy` and wire `keep` keep a mark alive through `opt_clean`, `opt_merge`, `flatten` and `wreduce`; how GHDL places VHDL `keep` attributes |
| `tests/vhdl_pipeline_latency/` | VHDL: the output equals the datapath function of the inputs one cycle earlier (checked against a UF reference), by BMC and induction; wrong-latency mutation, vacuity covers |
| `tests/vhdl_control_independence/` | VHDL: data independent of the control sequence, marks as VHDL label attributes, `UF_MODE` driving `uf_disable` and the assume/assert choice, symbolic beat index and k-induction with invariants; mutations, vacuity covers |
| `tests/vhdl_control_independence_setattr/` | the same proof on an untouched DUT, multiplier marked with `setattr` in the sby script; UF and non-UF runs |
| `tests/vhdl_fir_independence/` | parametric complex FIR (AXI Stream): data independent of control and control independent of data, by BMC and k-induction, multi-output UF boxes in a generate loop |
| `tests/vhdl_fir_pipeline/` | the same properties for a pipelined FIR with per-stage valid/ready (combinational ready chain or skid buffers), bounded progress |
| `tests/fifo_checkers/` | parametric AXI Stream FIFO checked with a memory-free UF checker and with a single-beat scoreboard; k-induction for depths 3..32 |
| `tests/fifo_wolper/` | the same FIFO with Wolper's two-value data-independence checker (a special case of the UF checker), by BMC and induction |
| `tests/speedup_bmc/` | BMC speed of the UF model against the non-UF model (interpreted multiplier) as a function of data width and depth |
| `tests/speedup_prove/` | k-induction speed of the UF model against the non-UF model; the two models differ only in the multiplier line |
| `tests/width_scaling/` | cost of wide UF arguments and results, and of wide beat-index counters |
| `smoke/` | toolchain sanity |

## Soundness notes

- A UF over-approximates the marked logic: a **PASS** with UFs implies a PASS of the non-UF
  design for safety properties. What a **FAIL** means depends on the property. For an
  independence property (the data does not depend on the control sequence, or the control
  does not depend on the data) the claim is that it holds for *every* datapath function, so
  a UF counterexample is a genuine one: it exhibits a function for which the control and the
  data interact, even if the present arithmetic happens to hide it. Check only that the
  testbench binds every function value the property compares (an unbound UF value, such as
  an expected output at an index that the defining channel never produced, also fails the
  assertion). For a property that is meant to hold for one specific arithmetic, a FAIL may
  be spurious (the UF chose a value the real function cannot produce); rerun the
  counterexample without the marks, or remove the mark.
- A cover reached under abstraction shows reachability in the abstract model.
- Traces: `yosys-smtbmc`'s own VCD and Yosys witness (`.yw`) files contain the UF values.
  `sim`/`vcd_sim` replay uses the actual semantics of the marked logic.

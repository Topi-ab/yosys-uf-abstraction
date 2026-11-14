#!/bin/bash
# Measurement grid: WIDTH x DEPTH; for each point first uf, then nouf.
# nouf is stopped when it exceeds RATIO_CAP x the uf time (default 20) or CAP_S
# seconds (default 2400); a stopped time is a lower bound (status TIMEOUT).
# The points of one repetition run in parallel, at most MAXPAR (default 8) at
# a time (running the whole grid at once loads the machine so much that the
# times stretch 2-3x and the ratio is distorted); repetitions run one after
# another.
#   tests/speedup_bmc/grid.sh <outdir> "<widths>" "<depths>" [repetitions]
# Result: <outdir>/results.tsv, columns
#   width depth rep uf_wall uf_solver uf_status nouf_wall nouf_solver nouf_status
# wall = the whole sby run (ghdl/yosys included), solver = wall-clock time of
# the yosys-smtbmc process (measured with the sby --smtbmc wrapper; '-' if the
# run was stopped).
# Completion marker: <outdir>/grid.done
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=$(mkdir -p "$1" && cd "$1" && pwd); WIDTHS=$2; DEPTHS=$3; REPS=${4:-1}
RATIO_CAP=${RATIO_CAP:-20}; CAP_S=${CAP_S:-2400}; MAXPAR=${MAXPAR:-8}
rm -f "$OUT/grid.done"; : > "$OUT/results.tsv"

SMTBMC=$(command -v yosys-smtbmc)
cat > "$OUT/smtbmc_timed.sh" <<EOW
#!/bin/bash
t0=\$(date +%s.%N)
"$SMTBMC" "\$@"; rc=\$?
t1=\$(date +%s.%N)
awk -v a="\$t0" -v b="\$t1" 'BEGIN { printf "%.2f\n", b - a }' > "\$SPEEDUP_TIMEFILE"
exit \$rc
EOW
chmod +x "$OUT/smtbmc_timed.sh"

run1() {   # $1 = task, $2 = work, $3 = timeout_s -> "wall solver status"
    local t0 t1 st sv
    rm -f "$2/$1.solver_s"
    t0=$(date +%s.%N)
    ( cd "$2" && SPEEDUP_TIMEFILE="$2/$1.solver_s" timeout "$3" \
        sby --smtbmc "$OUT/smtbmc_timed.sh" -f speedup.sby "$1" > "$1.log" 2>&1 )
    t1=$(date +%s.%N)
    st=$(grep -o 'DONE ([A-Z]*' "$2/$1.log" | tail -1 | cut -c7-); [ -n "$st" ] || st=TIMEOUT
    sv=$(cat "$2/$1.solver_s" 2>/dev/null); [ -n "$sv" ] && [ "$st" != TIMEOUT ] || sv=-
    echo "$(awk -v a="$t0" -v b="$t1" 'BEGIN { printf "%.2f", b - a }') $sv $st"
}

point() {  # $1 width, $2 depth, $3 rep
    local w="$OUT/w$1_d$2_r$3"; rm -rf "$w"; mkdir -p "$w"
    cp "$HERE"/speedup.sby "$HERE"/*.vhdl "$w/"
    export SPEEDUP_WIDTH=$1 SPEEDUP_DEPTH=$2
    local uw us ust cw cs cst cap
    read -r uw us ust < <(run1 uf "$w" "$CAP_S")
    cap=$(awk -v u="$uw" -v r="$RATIO_CAP" -v m="$CAP_S" \
        'BEGIN { c = u * r; if (c < 10) c = 10; if (c > m) c = m; printf "%.0f", c }')
    read -r cw cs cst < <(run1 nouf "$w" "$cap")
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$1" "$2" "$3" \
        "$uw" "$us" "$ust" "$cw" "$cs" "$cst" >> "$OUT/results.tsv"
}

for r in $(seq 1 "$REPS"); do
    n=0
    for wd in $WIDTHS; do for d in $DEPTHS; do
        if [ "$n" -ge "$MAXPAR" ]; then wait -n; n=$((n - 1)); fi
        point "$wd" "$d" "$r" & n=$((n + 1))
    done; done
    wait
done
echo done > "$OUT/grid.done"

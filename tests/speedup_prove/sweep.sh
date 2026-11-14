#!/bin/bash
# Measurement grid: WIDTH x TASK, all points in parallel (one sby run per point).
# Every run is stopped after CAP_S seconds (default 1800); a stopped time is a
# lower bound (status TIMEOUT).
#   tests/speedup_prove/sweep.sh <outdir> "<widths>" "<tasks>" [depth]
# The depth (PROVE_DEPTH) is optional; the default is the per-task default of
# uf_prove.sby.
# Result: <outdir>/results.tsv, columns
#   width task depth wall_s status
# wall = wall-clock time of the whole sby run (ghdl/yosys included, under 1 s).
# Completion marker: <outdir>/sweep.done (written when all points are done).
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=$(mkdir -p "$1" && cd "$1" && pwd); WIDTHS=$2; TASKS=$3; DEPTH=${4:-}
CAP_S=${CAP_S:-1800}
rm -f "$OUT/sweep.done"; : > "$OUT/results.tsv"

point() {  # $1 width, $2 task
    local w="$OUT/w$1_$2" t0 t1 st
    rm -rf "$w"; mkdir -p "$w"
    cp "$HERE"/uf_prove.sby "$HERE"/*.vhdl "$HERE"/*.psl "$w/"
    t0=$(date +%s.%N)
    ( cd "$w" && env PROVE_WIDTH="$1" ${DEPTH:+PROVE_DEPTH="$DEPTH"} timeout "$CAP_S" \
        sby -f uf_prove.sby "$2" > "$2.log" 2>&1 )
    t1=$(date +%s.%N)
    st=$(grep -o 'DONE ([A-Z]*' "$w/$2.log" | tail -1 | cut -c7-); [ -n "$st" ] || st=TIMEOUT
    printf '%s\t%s\t%s\t%s\t%s\n' "$1" "$2" "${DEPTH:-default}" \
        "$(awk -v a="$t0" -v b="$t1" 'BEGIN { printf "%.2f", b - a }')" "$st" >> "$OUT/results.tsv"
}

pids=()
for wd in $WIDTHS; do for t in $TASKS; do
    point "$wd" "$t" & pids+=($!)
done; done
for p in "${pids[@]}"; do wait "$p"; done
echo done > "$OUT/sweep.done"

#!/usr/bin/env bash
# Bulk-export chapter triage dumps as JSON files, one per chapter.
#
# Usage:
#   ./scripts/dump-triage-range.sh                 # default: 12..120, ./triage-dumps/
#   ./scripts/dump-triage-range.sh 12 30           # only chapters 12-30
#   ./scripts/dump-triage-range.sh 12 120 my-dir   # custom output dir
#
# Each chapter writes to <outdir>/output<N>.txt (matches the per-chapter
# convention used so far).  Failures abort the loop and print a resume
# command so you can pick up from the failing chapter.
#
# Run from the project root on the VPS where the rotk.net docker stack
# is up — `docker compose exec` needs the `app` service running.

set -euo pipefail

START=${1:-12}
END=${2:-120}
OUTDIR=${3:-./triage-dumps}

if ! [[ "$START" =~ ^[0-9]+$ ]] || ! [[ "$END" =~ ^[0-9]+$ ]]; then
    echo "error: start and end must be integers (got '$START' '$END')" >&2
    exit 2
fi
if (( START > END )); then
    echo "error: start ($START) > end ($END)" >&2
    exit 2
fi

mkdir -p "$OUTDIR"
total=$((END - START + 1))
i=0
for n in $(seq "$START" "$END"); do
    i=$((i + 1))
    out="$OUTDIR/output${n}.txt"
    printf "[%3d/%3d] chapter %3d -> %s ... " "$i" "$total" "$n" "$out"
    # -T disables pseudo-TTY so the redirect lands cleanly in the file.
    if docker compose exec -T app flask dump-chapter-triage "$n" > "$out" 2>&1; then
        echo "ok ($(wc -l < "$out") lines, $(du -h "$out" | cut -f1))"
    else
        echo "FAILED — see $out for the traceback"
        echo "Resume: $0 $n $END $OUTDIR" >&2
        exit 1
    fi
done

echo
echo "Done. $total dumps in $OUTDIR/"

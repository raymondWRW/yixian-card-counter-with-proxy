#!/bin/bash
# FAST full-suite sweep: N in-process Oracle shards in parallel, each over a slice of the records, each
# writing per-round results; then merge into data/fixtures/_results.json. Replaces both the 20-min
# per-record sweep AND the 20-min gen_fixture_results.py with one ~1-min run.
#   in-process (configs loaded once, ~3.5x) × N-way process sharding (~Nx) = ~20-30x overall.
# Usage:  bash tools/game-oracle/scripts/fast_sweep.sh [N]   (N = parallel shards, default = cores-2)
set -u
ORACLE="C:/Users/danhc/Documents/Projects/Yi-Xian-Solver/tools/game-oracle/Oracle"
REC="C:/Users/danhc/AppData/LocalLow/DarkSunStudio/YiXianPai/userLocalDatas/68e92665d06c85745f644008/recentBattleDatas"
OUT="C:/Users/danhc/Documents/Projects/Yi-Xian-Solver/data/fixtures/_results.json"
cd "$ORACLE" || exit 1
N=${1:-$(( $(nproc 2>/dev/null || echo 8) - 2 ))}; [ "$N" -lt 1 ] && N=1
export ORACLE_MAXDEPTH=1000
echo "=== fast sweep: $N parallel shards ==="
rm -f /tmp/shard_*.json /tmp/shard_*.log
t0=$(date +%s)
pids=()
for i in $(seq 0 $((N-1))); do
  dotnet run --project Oracle.csproj -c Release --no-build -- \
    --records-dir "$REC" --shard "$i" "$N" --results-out "/tmp/shard_${i}.json" > "/tmp/shard_${i}.log" 2>&1 &
  pids+=($!)
done
fail=0
for p in "${pids[@]}"; do wait "$p" || fail=1; done
t1=$(date +%s)
# Merge shard result files INTO the existing _results.json (accumulate coverage across runs, and
# NEVER overwrite with empty when shards crash/produce nothing — that previously wiped all results).
"$ORACLE/../../../.venv/Scripts/python.exe" - "$OUT" "/tmp/shard_" <<'PY'
import json, sys, glob, os
out, prefix = sys.argv[1], sys.argv[2]
merged = {}
if os.path.exists(out):
    try: merged = json.load(open(out, encoding="utf-8"))
    except Exception: merged = {}
shards = sorted(glob.glob(prefix + "*.json"))  # glob in python so an unmatched pattern => [], not a literal arg
new = {}
for s in shards:
    try: new.update(json.load(open(s, encoding="utf-8")))
    except Exception as e: print(f"  skip {s}: {e}", file=sys.stderr)
if not new:
    print(f"  WARNING: 0 shard rounds parsed ({len(shards)} shard files) — keeping existing {len(merged)} rounds, NOT overwriting", file=sys.stderr)
else:
    merged.update(new)
    json.dump(merged, open(out, "w", encoding="utf-8"), indent=0)
npass = sum(1 for v in merged.values() if v.get("pass"))
print(f"merged {len(new)} new / {len(merged)} total rounds -> {out}  ({npass} combat-exact = {100*npass/max(len(merged),1):.1f}%)")
PY
echo "=== wall-clock: $((t1 - t0))s for the combat sweep (shards), exit-fail=$fail ==="

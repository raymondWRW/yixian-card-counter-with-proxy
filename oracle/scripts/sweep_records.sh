#!/bin/bash
# Full combat-accuracy sweep over every recorded battle.
#  - Combat-only criterion (hpDelta+turns); destiny flagged separately by Oracle, not counted.
#  - ORACLE_MAXDEPTH caps the ILRuntime call-depth guard LOW so a headless trigger-loop bails in
#    seconds instead of recursing to 6000 (which took >90s -> hit `timeout` -> orphaned Oracle.exe).
#    1000 keeps sample_battle.bin at 18/18 (no legit combat that deep), so it's safe.
#  - taskkill cleans any lingering Oracle.exe after each record (belt-and-suspenders vs orphans).
#  - Captures charId per record for a per-character breakdown.
cd "C:/Users/danhc/Documents/Projects/Yi-Xian-Solver/tools/game-oracle/Oracle" || exit 1
REC="C:/Users/danhc/AppData/LocalLow/DarkSunStudio/YiXianPai/userLocalDatas/68e92665d06c85745f644008/recentBattleDatas"
export ORACLE_MAXDEPTH=1000
tp=0; tt=0; full=0; n=0; crash=0
for f in "$REC"/*.bin; do
  out=$(timeout 60 dotnet run --project Oracle.csproj -c Release --no-build -- --batch --execute --record "$f" 2>/dev/null)
  taskkill //F //IM Oracle.exe >/dev/null 2>&1
  line=$(echo "$out" | grep -E "RESULT:")
  cid=$(echo "$out" | grep -oE "charId=[0-9]+" | head -1 | cut -d= -f2)
  p=$(echo "$line" | grep -oE "[0-9]+/[0-9]+" | head -1 | cut -d/ -f1)
  t=$(echo "$line" | grep -oE "[0-9]+/[0-9]+" | head -1 | cut -d/ -f2)
  if [ -n "$p" ] && [ -n "$t" ]; then
    tp=$((tp+p)); tt=$((tt+t)); n=$((n+1)); [ "$p" = "$t" ] && full=$((full+1))
    echo "$(basename "$f") char=${cid:-?}: $p/$t"
  else
    crash=$((crash+1)); echo "$(basename "$f") char=${cid:-?}: PROCESS-CRASH"
  fi
done
echo ""
echo "=== AGGREGATE: $tp/$tt rounds combat-exact across $n records ($full fully-exact, $crash process-crashes) ==="
[ "$tt" -gt 0 ] && awk "BEGIN{printf \"accuracy: %.1f%%\n\", $tp*100/$tt}"

#!/bin/bash
# Export EVERY recorded battle's rounds as season-tagged, uniquely-id'd fixtures into data/fixtures/.
# Each fixture: id="{recordStem}-r{NN}", record="{recordStem}", season="<SeasonMechanismType>", + the
# game-native combat inputs. This is the full Oracle test suite for the UI test list (grouped by
# record/season). One-time generation (~20 min); re-run only when the record set changes.
cd "C:/Users/danhc/Documents/Projects/Yi-Xian-Solver/tools/game-oracle/Oracle" || exit 1
REC="C:/Users/danhc/AppData/LocalLow/DarkSunStudio/YiXianPai/userLocalDatas/68e92665d06c85745f644008/recentBattleDatas"
FIX="C:/Users/danhc/Documents/Projects/Yi-Xian-Solver/data/fixtures"
# Drop superseded auto-exports (old "recorded-rNN" collided across records); keep hand-made fixtures.
rm -f "$FIX"/recorded-r*.json
n=0
for f in "$REC"/*.bin; do
  timeout 60 dotnet run --project Oracle.csproj -c Release --no-build -- --export-fixtures --record "$f" >/dev/null 2>&1
  taskkill //F //IM Oracle.exe >/dev/null 2>&1
  n=$((n+1)); echo "[$n] $(basename "$f")"
done
echo "DONE — fixtures now in $FIX:"
ls "$FIX"/*.json | wc -l

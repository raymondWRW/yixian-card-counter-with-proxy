"""
dump_cards.py
────────────
Extract every card name (id → Chinese + English) from YiXianPai's
localization bundle. Same parser as dump_derivations.py but keyed on
CardName_<id> / CardDesc_<id>.

Output: tools/cards_game.json
"""
from __future__ import annotations
import json, sys, re, struct
from pathlib import Path

import UnityPy
UnityPy.config.FALLBACK_UNITY_VERSION = "2022.3.40f1"

BUNDLE = Path(
    r"C:/Program Files (x86)/Steam/steamapps/common/YiXianPai/"
    r"YiXianPai_Data/StreamingAssets/aa/StandaloneWindows64/"
    r"61f07ae57a1be89b8c28c474bb230304.bundle"
)
OUT = Path(__file__).resolve().parent / "cards_game.json"


def get_localization_blob() -> bytes:
    env = UnityPy.load(str(BUNDLE))
    for obj in env.objects:
        if obj.type.name == 'MonoBehaviour':
            return obj.get_raw_data()
    raise RuntimeError("no MonoBehaviour found")


def read_string_at(raw: bytes, pos: int) -> tuple[str, int]:
    if pos + 4 > len(raw):
        return '', pos
    length = struct.unpack_from('<I', raw, pos)[0]
    pos += 4
    if length > 100000 or pos + length > len(raw):
        return '', pos
    s = raw[pos:pos + length].decode('utf-8', errors='replace')
    pos += length
    pad = (4 - length % 4) % 4
    pos += pad
    return s, pos


def parse_term_at(raw: bytes, key_start: int) -> tuple[str, list[str]] | None:
    p = key_start
    key, p = read_string_at(raw, p)
    if not key:
        return None
    p += 4  # padding after key
    if p + 4 > len(raw):
        return None
    count = struct.unpack_from('<I', raw, p)[0]
    p += 4
    if count == 0 or count > 10:
        return None
    values = []
    for _ in range(count):
        v, p = read_string_at(raw, p)
        values.append(v)
    return key, values


def main():
    print("Loading bundle...", file=sys.stderr)
    raw = get_localization_blob()
    print(f"Raw size: {len(raw):,}", file=sys.stderr)

    by_id: dict[int, dict] = {}
    seen_offsets = set()

    for prefix in (b'CardName_', b'CardDesc_'):
        plen = len(prefix)
        for m in re.finditer(re.escape(prefix) + rb'(\d+)', raw):
            try:
                fid = int(m.group(1).decode())
            except ValueError:
                continue
            length_pos = m.start() - 4
            if length_pos < 0 or length_pos in seen_offsets:
                continue
            seen_offsets.add(length_pos)
            try:
                exp_len = struct.unpack_from('<I', raw, length_pos)[0]
            except struct.error:
                continue
            actual_key_len = plen + len(m.group(1))
            if exp_len != actual_key_len:
                continue
            result = parse_term_at(raw, length_pos)
            if not result:
                continue
            key, values = result
            entry = by_id.setdefault(fid, {})
            cn = values[0] if len(values) >= 1 else None
            en = values[1] if len(values) >= 2 else None
            if key.startswith('CardName_'):
                entry['name_cn'] = cn
                entry['name_en'] = en
            elif key.startswith('CardDesc_'):
                entry['desc_cn'] = cn
                entry['desc_en'] = en

    entries = []
    for fid in sorted(by_id.keys()):
        d = by_id[fid]
        entries.append({
            'id': fid,
            'name_cn': d.get('name_cn'),
            'name_en': d.get('name_en'),
            'desc_cn': d.get('desc_cn'),
            'desc_en': d.get('desc_en'),
        })

    OUT.write_text(json.dumps({
        'total': len(entries),
        'entries': entries,
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"\nWrote {len(entries)} cards → {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()

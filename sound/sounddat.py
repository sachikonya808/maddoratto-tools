#!/usr/bin/env python3
"""Mad Rat Dead  Data/Database/Sound.dat  <->  JSON.

Format (all little-endian u32):
    header   0x0C bytes: record size (0x78), record count, data-present flag (1)
    records  count * 0x78 bytes, starting at 0x0C
    strings  string pool starting at 0x0C + count * 0x78. Every string field is a
             u32 offset relative to the pool start, pointing at a NUL-terminated
             UTF-8 string. The game's own pool has one separate copy per field
             (even for empty strings), laid out record by record in field order.

Record layout (0x78 bytes = 30 u32 fields, every byte accounted for):
    +00  id                       (equals the BGM number: 0x29 = BGM041)
    +04  str_04   string          \\  all "BGMxxx" in 44 of 45 records;
    +08  str_08   string           >  BGM100 has BGM100 / BGM006 / BGM100
    +0C  str_0c   string          /   (see the README for the cue-name hypothesis)
    +10  str_10   string          "BGMxxx_Select"
    +14..+30  chart_ids[8]        Rhythm.dat chart IDs: block 1-4 normal, then 1-4 Hard
                                  (song*100 + (10 if Hard) + block); 0 = no such chart
    +34  num_34                   Normal difficulty, stars 1-3 in the game's songs
    +38  num_38                   Hard difficulty, stars 2-5 in the game's songs (both shown as 1-5 stars)
    +3C  title[4]                 4 language slots
    +4C  composer[4] / +50 ...    interleaved: composer, composer2 for each language slot
    +6C  bpm                      100-180 (probably BPM)
    +70  selectable               1 = listed in the song selector
    +74  sort                     selector order, 1..N unique among selectable records

Commands:
    sounddat.py dump   Sound.dat                    readable table
    sounddat.py export Sound.dat songs.json         every record as JSON
    sounddat.py build  songs.json Sound_new.dat     JSON -> Sound.dat (rebuilds the string pool)
    sounddat.py clone  Sound.dat Out.dat --from 0x29 --id 0x2C --title "Name" --composer "Me" --bpm 140

clone options: --normal-diff N --hard-diff N (difficulty stars, num_34 / num_38),
               --keep-names --keep-charts (safe test record), --sort N, --insert-at INDEX,
               --set-sort ID=SORT (repeatable), --rhythm Rhythm.dat (chart ID check),
               --str04/--str08/--str0c/--str10 NAME (override one name field),
               --allow-duplicate-id (experiments only; the game looks songs up by ID)

Records must stay in ascending ID order: the game looks a song up by ID when it starts
it, and a clone that breaks the order hangs the game. `build` warns if the order is
broken; `clone` inserts at the ID position by default.
"""

import argparse
import json
import struct
import sys
from pathlib import Path

HEADER = 0x0C
RECORD = 0x78
LANGS = 4

# (json name, offset) for single string fields, in pool order
STR_HEAD = [("str_04", 0x04), ("str_08", 0x08), ("str_0c", 0x0C), ("str_10", 0x10)]
CHART_OFFS = [0x14 + 4 * i for i in range(8)]
TITLE_OFFS = [0x3C + 4 * i for i in range(LANGS)]
# composer / composer2 interleaved per language: +4C +50 | +54 +58 | +5C +60 | +64 +68
COMP_OFFS = [0x4C + 8 * i for i in range(LANGS)]
COMP2_OFFS = [0x50 + 8 * i for i in range(LANGS)]

# String fields in the order the game lays them out in the pool.
POOL_ORDER = [0x04, 0x08, 0x0C, 0x10] + list(range(0x3C, 0x6C, 4))


def _u32(buf, off):
    return struct.unpack_from("<I", buf, off)[0]


# --------------------------------------------------------------------------
# Parse
# --------------------------------------------------------------------------

def parse(data):
    if len(data) < HEADER:
        raise ValueError("file too small")

    rec_size, count, present = struct.unpack_from("<III", data, 0)

    if rec_size != RECORD:
        raise ValueError(f"unexpected record size 0x{rec_size:X}")

    base = HEADER + count * rec_size

    if base > len(data):
        raise ValueError("record table runs past end of file")

    def string(rel, what):
        pos = base + rel

        if pos >= len(data):
            raise ValueError(f"{what}: string pointer 0x{rel:X} outside the file")

        end = data.find(b"\0", pos)

        if end < 0:
            raise ValueError(f"{what}: unterminated string")

        return data[pos:end].decode("utf-8")

    records = []

    for i in range(count):
        o = HEADER + i * rec_size
        g = lambda off: _u32(data, o + off)
        w = f"record {i}"

        records.append({
            "id": g(0x00),
            **{name: string(g(off), f"{w} {name}") for name, off in STR_HEAD},
            "chart_ids": [g(off) for off in CHART_OFFS],
            "num_34": g(0x34),
            "num_38": g(0x38),
            "title": [string(g(off), f"{w} title") for off in TITLE_OFFS],
            "composer": [string(g(off), f"{w} composer") for off in COMP_OFFS],
            "composer2": [string(g(off), f"{w} composer2") for off in COMP2_OFFS],
            "bpm": g(0x6C),
            "selectable": g(0x70),
            "sort": g(0x74),
        })

    return {"flag": present, "records": records}


# --------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------

def _check(rec, index):
    w = f"record {index} (id {rec.get('id')})"

    for key in ("id", "num_34", "num_38", "bpm", "selectable", "sort"):
        v = rec[key]

        if not isinstance(v, int) or not 0 <= v <= 0xFFFFFFFF:
            raise ValueError(f"{w}: {key} must be an unsigned 32-bit integer")

    if len(rec["chart_ids"]) != 8:
        raise ValueError(f"{w}: chart_ids needs 8 entries")

    for v in rec["chart_ids"]:
        if not isinstance(v, int) or not 0 <= v <= 0xFFFFFFFF:
            raise ValueError(f"{w}: bad chart id {v!r}")

    for key in ("title", "composer", "composer2"):
        if len(rec[key]) != LANGS:
            raise ValueError(f"{w}: {key} needs {LANGS} entries")

    for key in ("str_04", "str_08", "str_0c", "str_10"):
        if not isinstance(rec[key], str):
            raise ValueError(f"{w}: {key} must be a string")

    for s in (rec["str_04"], rec["str_08"], rec["str_0c"], rec["str_10"],
              *rec["title"], *rec["composer"], *rec["composer2"]):
        if "\0" in s:
            raise ValueError(f"{w}: strings must not contain NUL")


def build(doc):
    records = doc["records"]

    for i, rec in enumerate(records):
        _check(rec, i)

    warnings = []
    ids = [r["id"] for r in records]

    if len(set(ids)) != len(ids):
        warnings.append("duplicate record IDs: " + ", ".join(
            f"0x{i:X}" for i in sorted({x for x in ids if ids.count(x) > 1})))

    if ids != sorted(ids):
        warnings.append(
            "records are NOT in ascending ID order: the game looks a song up by ID "
            "when it starts it, and out-of-order records make it hang (tested: the "
            "song with the out-of-order ID, and the IDs after it, hang on load)")

    sel = sorted(r["sort"] for r in records if r["selectable"] == 1)

    if sel != list(range(1, len(sel) + 1)):
        warnings.append(
            "sort keys of selectable records are not exactly 1..N "
            f"(N = {len(sel)}); the original file is a clean 1..42 permutation")

    out = bytearray(struct.pack("<III", RECORD, len(records), doc.get("flag", 1)))
    pool = bytearray()
    rec_bytes = bytearray()

    for rec in records:
        fields = [0] * (RECORD // 4)

        def put(off, value):
            fields[off // 4] = value

        def add_string(off, text):
            put(off, len(pool))
            pool.extend(text.encode("utf-8") + b"\0")

        put(0x00, rec["id"])
        by_off = {off: rec[name] for name, off in STR_HEAD}
        by_off.update(zip(TITLE_OFFS, rec["title"]))
        by_off.update(zip(COMP_OFFS, rec["composer"]))
        by_off.update(zip(COMP2_OFFS, rec["composer2"]))

        for off in POOL_ORDER:
            add_string(off, by_off[off])

        for off, v in zip(CHART_OFFS, rec["chart_ids"]):
            put(off, v)

        put(0x34, rec["num_34"])
        put(0x38, rec["num_38"])
        put(0x6C, rec["bpm"])
        put(0x70, rec["selectable"])
        put(0x74, rec["sort"])
        rec_bytes += struct.pack(f"<{RECORD // 4}I", *fields)

    return bytes(out + rec_bytes + pool), warnings


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------

def cmd_dump(args):
    doc = parse(Path(args.input).read_bytes())
    print(f"{len(doc['records'])} records, flag {doc['flag']}")
    print("idx id    sel sort bpm  n34 n38 | title (slot 0 / slot 1) | composer | str_04 str_08 str_0c str_10")

    for i, r in enumerate(doc["records"]):
        print(f"{i:2}  0x{r['id']:02X}  {r['selectable']}  {r['sort']:3}  {r['bpm']:3}  "
              f"{r['num_34']}   {r['num_38']}  | {r['title'][0]!r} / {r['title'][1]!r} | "
              f"{r['composer'][0]!r} / {r['composer'][1]!r} | "
              f"{r['str_04']} {r['str_08']} {r['str_0c']} {r['str_10']}")
        print(f"      charts {r['chart_ids']}")


def cmd_export(args):
    doc = parse(Path(args.input).read_bytes())
    Path(args.output).write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {args.output} ({len(doc['records'])} records)")


def rhythm_chart_ids(path):
    """Chart IDs present in a Rhythm.dat. Its header is the same container as
    Sound.dat (record size, count, flag) and each record starts with the chart ID
    (that is the field at table - 0x10 in the chart tools)."""
    data = Path(path).read_bytes()
    stride, count, _ = struct.unpack_from("<III", data, 0)
    return {_u32(data, HEADER + k * stride) for k in range(count)}


def _write_checked(doc, output, rhythm=None):
    data, warnings = build(doc)
    again = parse(data)                         # re-parse what we are about to write

    if again["records"] != doc["records"]:
        raise RuntimeError("internal error: rebuilt file does not match the input")

    if rhythm:
        have = rhythm_chart_ids(rhythm)

        for r in doc["records"]:
            missing = [c for c in r["chart_ids"] if c and c not in have]

            if missing:
                warnings.append(
                    f"record id 0x{r['id']:X}: chart IDs {missing} do not exist in "
                    f"{rhythm} (selecting this song would have no chart to load)")

    for w in warnings:
        print("WARNING:", w)

    Path(output).write_bytes(data)
    print(f"Wrote {output}: {len(data):,} bytes, {len(doc['records'])} records")


def cmd_build(args):
    doc = json.loads(Path(args.input).read_text(encoding="utf-8"))
    _write_checked(doc, args.output, args.rhythm)


def cmd_clone(args):
    doc = parse(Path(args.input).read_bytes())
    records = doc["records"]
    src = [r for r in records if r["id"] == args.source]

    if len(src) != 1:
        raise ValueError(f"expected exactly one record with id 0x{args.source:X}")

    if any(r["id"] == args.id for r in records) and not args.allow_duplicate_id:
        raise ValueError(
            f"id 0x{args.id:X} already exists (--allow-duplicate-id to override)")

    new = json.loads(json.dumps(src[0]))
    new["id"] = args.id
    name = f"BGM{args.id:03d}"

    if args.keep_names:
        pass                                    # reuse the source song's sheet / cue names
    else:
        new["str_04"] = new["str_08"] = new["str_0c"] = name
        new["str_10"] = f"{name}_Select"

    # By default the chart IDs follow the new song number (4401.. for id 44). Those
    # charts must then exist in Rhythm.dat. --keep-charts reuses the source's charts,
    # which always exist, and is the safe choice for a first test.
    if not args.keep_charts:
        new["chart_ids"] = [
            0 if old == 0 else args.id * 100 + (old % 100)
            for old in src[0]["chart_ids"]
        ]

    for field, value in (("str_04", args.str04), ("str_08", args.str08),
                         ("str_0c", args.str0c), ("str_10", args.str10)):
        if value is not None:
            new[field] = value

    if args.title:
        new["title"] = [args.title] * LANGS

    if args.composer:
        new["composer"] = [args.composer] * LANGS
        new["composer2"] = [""] * LANGS

    if args.bpm is not None:
        new["bpm"] = args.bpm

    # difficulty in stars (1-5): num_34 = Normal, num_38 = Hard (confirmed against the in-game stars)
    if args.normal_level is not None:
        new["num_34"] = args.normal_level

    if args.hard_level is not None:
        new["num_38"] = args.hard_level

    taken = [r["sort"] for r in records if r["selectable"] == 1]
    new["sort"] = args.sort if args.sort is not None else max(taken) + 1
    new["selectable"] = 1
    for spec in args.set_sort or []:
        rid, value = (int(x, 0) for x in spec.split("="))
        target = [r for r in records if r["id"] == rid]

        if len(target) != 1:
            raise ValueError(f"--set-sort: expected exactly one record with id 0x{rid:X}")

        target[0]["sort"] = value

    if args.insert_at is None:
        # keep the records in ascending ID order (the game looks songs up by ID)
        position = next((i for i, r in enumerate(records) if r["id"] > new["id"]),
                        len(records))
        records.insert(position, new)
        print(f"Inserted at record index {position} (ID order); that index's unlock "
              f"flag is {500 + position} (open) / {600 + position} (played)")
    else:
        if not 0 <= args.insert_at <= len(records):
            raise ValueError(f"--insert-at must be between 0 and {len(records)}")

        records.insert(args.insert_at, new)

    _write_checked(doc, args.output, args.rhythm)
    print("New record: id 0x%X, sort %d, sheet/cue names %r, charts %s"
          % (new["id"], new["sort"], new["str_08"], new["chart_ids"]))


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    for name, fn in (("dump", cmd_dump), ("export", cmd_export), ("build", cmd_build)):
        s = sub.add_parser(name)
        s.add_argument("input")

        if name != "dump":
            s.add_argument("output")

        s.set_defaults(fn=fn)

    c = sub.add_parser("clone")
    c.add_argument("input")
    c.add_argument("output")
    c.add_argument("--from", dest="source", type=lambda x: int(x, 0), required=True)
    c.add_argument("--id", type=lambda x: int(x, 0), required=True)
    c.add_argument("--title")
    c.add_argument("--composer")
    c.add_argument("--bpm", type=int)
    c.add_argument("--normal-diff", type=int, help="Normal difficulty stars (num_34, 1-5)")
    c.add_argument("--hard-diff", type=int, help="Hard difficulty stars (num_38, 1-5)")
    c.add_argument("--sort", type=lambda x: int(x, 0))
    c.add_argument("--keep-names", action="store_true",
                   help="keep the source song's BGMxxx / BGMxxx_Select names "
                        "(reuse its audio) instead of BGM<new id>")
    c.add_argument("--keep-charts", action="store_true",
                   help="keep the source song's chart IDs (reuse its charts)")
    c.add_argument("--rhythm", help="Rhythm.dat to check chart IDs against")
    for opt in ("--str04", "--str08", "--str0c", "--str10"):
        c.add_argument(opt, help="set this name field of the new record "
                                 "(applied after --keep-names)")

    c.add_argument("--allow-duplicate-id", action="store_true",
                   help="allow the new record to reuse an existing ID (for experiments)")
    c.add_argument("--insert-at", type=int,
                   help="insert the new record at this record index instead of the end "
                        "(later records shift up by one)")
    c.add_argument("--set-sort", action="append", metavar="ID=SORT",
                   help="also change another record's sort key, e.g. 0x2B=43 (repeatable)")
    c.set_defaults(fn=cmd_clone)
    sub.choices["build"].add_argument("--rhythm", help="Rhythm.dat to check chart IDs against")

    args = p.parse_args()

    if args.cmd in ("export", "build", "clone") and \
            Path(args.output).resolve() == Path(args.input).resolve():
        raise ValueError("output must not be the input file")

    args.fn(args)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ERROR: {error}")
        sys.exit(1)

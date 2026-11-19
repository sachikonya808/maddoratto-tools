# Add the charts of a NEW song to Rhythm.dat (new records, ID-ordered).
#
# Usage:
#   Copy an existing song's charts (normal + Hard) under a new song number:
#     python rhythm_addsong.py --target BGM044 --from-song BGM030
#
#   Build the charts from text files written by rhythm_export.py / by hand:
#     python rhythm_addsong.py --target BGM044 --normal n.txt --hard h.txt --bpm 140
#
# The new charts are called BGM044_1 .. BGM044_4 (normal) and BGM044_1H .. _4H
# (Hard) and get the chart IDs 4401..4404 and 4411..4414 that the matching
# Sound.dat record must list. Records are inserted in ascending chart-ID order
# (the game almost certainly looks charts up by ID, like it does for songs), the
# header count is updated and every pointer is recomputed.
#
# The "length field" of each new record is round(non-empty tokens * 720000 / BPM).
# --from-song copies the source charts' length fields unchanged unless --bpm is
# given; the text modes need --bpm.

from pathlib import Path
import argparse
import re
import sys

from rhythm_dat import (
    CHART_SIZE,
    NAME_FULL_RE,
    chart_id_from_name,
    build_file,
    decode_tokens,
    length_field,
    parse_directory,
    stored_length_field,
    symbols_to_tokens,
    verify,
)
from rhythm_import import read_text_charts


def main():
    parser = argparse.ArgumentParser(description="Add a new song's charts to Rhythm.dat")
    parser.add_argument("--target", required=True, help="new song, e.g. BGM044")
    parser.add_argument("--input", default="Rhythm.dat")
    parser.add_argument("--output", default="Rhythm_new.dat")
    parser.add_argument("--from-song", help="copy all charts of this existing song (e.g. BGM030)")
    parser.add_argument("--normal", help="text file with the normal charts (blocks 1-4)")
    parser.add_argument("--hard", help="text file with the Hard charts (blocks 1-4)")
    parser.add_argument("--bpm", type=float, help="BPM, used to compute the length field")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not re.fullmatch(r"BGM\d{3}", args.target):
        raise ValueError("--target must look like BGM044")

    if bool(args.from_song) == bool(args.normal or args.hard):
        raise ValueError("use either --from-song, or --normal / --hard")

    if Path(args.output).resolve() == Path(args.input).resolve():
        raise ValueError("output must not be the input file")

    data = Path(args.input).read_bytes()
    charts = parse_directory(data)
    existing = {c.name: c for c in charts}

    if any(n.startswith(args.target + "_") for n in existing):
        raise ValueError(f"{args.target} already has charts in this file")

    additions = {}

    if args.from_song:
        sources = [c for c in charts if c.name.startswith(args.from_song + "_")]

        if not sources:
            raise ValueError(f"no charts found for {args.from_song}")

        for c in sources:
            new_name = args.target + c.name[len(args.from_song):]
            tokens = decode_tokens(data, c)
            length = (length_field(tokens, args.bpm) if args.bpm
                      else stored_length_field(data, c))
            additions[new_name] = (tokens, length)
    else:
        if not args.bpm:
            raise ValueError("--bpm is required when building charts from text")

        for path, suffix in ((args.normal, ""), (args.hard, "H")):
            if not path:
                continue

            for number, symbols in sorted(read_text_charts(path).items()):
                tokens = symbols_to_tokens(symbols)
                additions[f"{args.target}_{number}{suffix}"] = (
                    tokens, length_field(tokens, args.bpm))

    result = build_file(data, charts, additions=additions)
    verify(data, charts, result, additions=additions)

    print(f"Input:   {args.input} ({len(charts)} charts, {len(data):,} bytes)")
    print(f"Adding:  {len(additions)} charts for {args.target}")

    for name, (tokens, length) in sorted(additions.items(), key=lambda kv: chart_id_from_name(kv[0])):
        used = sum(1 for t in tokens if t != b"")
        print(f"  {name:11} chart ID {chart_id_from_name(name):5}  non-empty tokens {used:4}  length field {length}")

    print(f"Result:  {len(parse_directory(result))} charts, {len(result):,} bytes "
          f"({len(result) - len(data):+,})")
    print("Verification passed: header, record order, pointers, offsets, tokens, untouched records.")

    if args.dry_run:
        print("Dry run: no file written.")
        return

    Path(args.output).write_bytes(result)
    print(f"\nSUCCESS! Output: {args.output}\nOriginal file was not modified.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"\nERROR: {error}")
        sys.exit(1)

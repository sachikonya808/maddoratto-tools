# Usage:  python rhythm_import.py chart.txt --target BGM039
#         python rhythm_import.py chart.txt --target BGM039 --hard
#         python rhythm_import.py chart.txt --target BGM039 --dry-run
#
# Replaces the charts found in chart.txt (blocks 1-4) inside Rhythm.dat.
# The new chart may have a different byte size than the old one: the string
# area is rebuilt and every name pointer / offset table is rewritten, the same
# way scan.py does when it implants BGM038_1 into BGM039_1.

from pathlib import Path
import re
import argparse
import sys

from rhythm_dat import (
    CHART_SIZE,
    SYMBOLS,
    UNKNOWN_SYMBOL,
    decode_tokens,
    find_chart,
    length_field,
    parse_directory,
    rebuild,
    stored_length_field,
    symbols_to_tokens,
    verify,
)


def read_text_charts(path):
    text = Path(path).read_text(encoding="utf-8")

    blocks = {}
    current_block = None

    for line_number, raw_line in enumerate(text.splitlines(), 1):
        line = raw_line.strip()

        if not line:
            continue

        heading = re.fullmatch(r"===\s*([1-4])\s*===", line)

        if heading:
            number = int(heading.group(1))

            if number in blocks:
                raise ValueError(f"Duplicate block {number}")

            blocks[number] = []
            current_block = number
            continue

        if current_block is None:
            raise ValueError(
                f"Unexpected text before first block at line {line_number}"
            )

        if len(line) != 4:
            raise ValueError(
                f"Line {line_number}: expected 4 characters, got {len(line)}"
            )

        for char in line:
            if char == UNKNOWN_SYMBOL:
                raise ValueError(
                    f"Line {line_number}: {UNKNOWN_SYMBOL!r} marks a token the "
                    "exporter did not recognise; replace it with a valid "
                    "symbol before importing"
                )

            if char not in SYMBOLS:
                raise ValueError(
                    f"Invalid character {char!r} at line {line_number}"
                )

        blocks[current_block].extend(line)

    if not blocks:
        raise ValueError("No chart blocks found")

    for number, symbols in blocks.items():
        if len(symbols) != CHART_SIZE:
            raise ValueError(
                f"Block {number}: expected {CHART_SIZE} symbols, "
                f"got {len(symbols)}"
            )

    return blocks


def main():
    parser = argparse.ArgumentParser(
        description="Replace charts inside Rhythm.dat"
    )

    parser.add_argument("chart_file")
    parser.add_argument("--target", required=True)
    parser.add_argument("--input", default="Rhythm.dat")
    parser.add_argument("--output", default="Rhythm_new.dat")
    parser.add_argument(
        "--hard",
        action="store_true",
        help="Replace Hard charts (with H suffix)"
    )
    parser.add_argument(
        "--bpm",
        type=float,
        help="song BPM: also rewrite each replaced chart's length field "
             "(non-empty tokens * 720000 / BPM). Without it the old value is kept"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build and verify everything but do not write the output file"
    )

    args = parser.parse_args()

    if not re.fullmatch(r"BGM\d{3}", args.target):
        raise ValueError("Target must look like BGM039")

    if Path(args.output).resolve() == Path(args.input).resolve():
        raise ValueError("Output must not be the same file as the input")

    original = Path(args.input).read_bytes()
    blocks = read_text_charts(args.chart_file)
    charts = parse_directory(original)

    suffix = "H" if args.hard else ""

    print(f"Input:  {args.input}")
    print(f"Target: {args.target}")
    print(f"Mode:   {'Hard' if args.hard else 'Normal'}")
    print(f"Blocks: {sorted(blocks)}")

    replacements = {}

    for number, symbols in sorted(blocks.items()):
        chart_name = f"{args.target}_{number}{suffix}"
        chart = find_chart(charts, chart_name)

        replacements[chart_name] = symbols_to_tokens(symbols)

        old_size = chart.boundary - chart.payload_start
        new_size = sum(len(t) + 1 for t in replacements[chart_name])

        print(
            f"{chart_name}: original={old_size} bytes, "
            f"new={new_size} bytes ({new_size - old_size:+d})"
        )

    lengths = {}

    for chart_name, tokens in replacements.items():
        chart = find_chart(charts, chart_name)
        used_new = sum(1 for t in tokens if t != b"")
        used_old = sum(1 for t in decode_tokens(original, chart) if t != b"")

        if args.bpm:
            lengths[chart_name] = length_field(tokens, args.bpm)
            print(f"{chart_name}: length field {stored_length_field(original, chart)} "
                  f"-> {lengths[chart_name]}")
        elif used_new != used_old:
            print(f"NOTE: {chart_name} has {used_new} non-empty tokens (was {used_old}) "
                  "but its length field is kept; pass --bpm to recompute it")

    result = rebuild(original, charts, replacements, lengths or None)
    verify(original, charts, result, replacements, lengths=lengths or None)

    print(f"\nFile size: {len(original):,} -> {len(result):,} "
          f"({len(result) - len(original):+d})")
    print("Verification passed: names, pointers, offset tables and tokens.")

    if args.dry_run:
        print("Dry run: no file written.")
        return

    Path(args.output).write_bytes(result)

    print("\nSUCCESS!")
    print(f"Output: {args.output}")
    print("Original file was not modified.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"\nERROR: {error}")
        sys.exit(1)

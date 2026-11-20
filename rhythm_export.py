# Usage: python rhythm_export.py --target BGM038
# Output: python rhythm_export.py --target BGM038 --output normal.txt
# Hard mode Charts: python rhythm_export.py --target BGM038 --output hard.txt --hard


from pathlib import Path
import argparse
import sys

from rhythm_dat import (
    CHART_SIZE,
    UNKNOWN_SYMBOL,
    decode_tokens,
    parse_directory,
    tokens_to_symbols,
)


def render_chart_ascii(data, chart, allow_unknown=False):
    symbols, unknown = tokens_to_symbols(decode_tokens(data, chart))

    if unknown:
        kinds = {}

        for index, token in unknown:
            kinds.setdefault(token.hex(" ").upper(), []).append(index)

        details = "; ".join(
            f"{hex_bytes} x{len(indexes)} (first at token {indexes[0]})"
            for hex_bytes, indexes in sorted(kinds.items())
        )

        message = (
            f"{chart.name} contains {len(unknown)} unrecognised token(s): "
            f"{details}"
        )

        if not allow_unknown:
            raise ValueError(
                message + ". Nothing was written. Add the missing form to "
                "SYMBOLS in rhythm_dat.py, or pass --allow-unknown to write "
                f"{UNKNOWN_SYMBOL!r} placeholders (those cannot be re-imported)."
            )

        print(f"WARNING: {message} -> written as {UNKNOWN_SYMBOL!r}")

    output_name = chart.name.split("_")[1].replace("H", "")
    output = [f"=== {output_name} ==="]

    for row in range(CHART_SIZE // 4):
        output.append(symbols[row * 4:(row + 1) * 4])

    return "\n".join(output)


def main():
    parser = argparse.ArgumentParser(
        description="Extract charts from Rhythm.dat"
    )

    parser.add_argument("--target", default="BGM038")
    parser.add_argument("--input", default="Rhythm.dat")
    parser.add_argument("--output", default=None)
    parser.add_argument(
        "--hard",
        action="store_true",
        help="Extract Hard charts (with H suffix)"
    )
    parser.add_argument(
        "--allow-unknown",
        action="store_true",
        help="Write '?' for unrecognised tokens instead of aborting"
    )

    args = parser.parse_args()

    data = Path(args.input).read_bytes()
    charts = {c.name: c for c in parse_directory(data)}

    suffix = "H" if args.hard else ""
    output_blocks = []

    for number in range(1, 5):
        name = f"{args.target}_{number}{suffix}"

        if name not in charts:
            print(f"Skipping missing chart: {name}")
            continue

        output_blocks.append(
            render_chart_ascii(data, charts[name], args.allow_unknown)
        )

    if not output_blocks:
        raise SystemExit("No matching charts found.")

    output_path = args.output or (
        f"{args.target}_{'Hard' if args.hard else 'Normal'}.txt"
    )

    Path(output_path).write_text(
        "\n\n".join(output_blocks) + "\n",
        encoding="utf-8"
    )

    print(f"\nExported {args.target} ({'Hard' if args.hard else 'Normal'})")
    print(f"Output: {output_path}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"\nERROR: {error}")
        sys.exit(1)

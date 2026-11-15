"""Shared helpers for the Rhythm.dat chart tools (rhythm_export.py / rhythm_import.py).

Layout of Rhythm.dat, as implied by scan.py:

  * A header area at the start of the file holds, for every chart, a small
    record:  [name pointer (u32)] [8 more bytes] [1600 x u32 token offsets].
    The offset table starts 12 bytes after the name pointer.
  * The string area starts at the first chart name. It is a sequence of
        NAME\\0  TOKEN0\\0 TOKEN1\\0 ... TOKEN1599\\0
    for every chart, back to back, up to the end of the file.
  * Pointers and offsets are stored relative to BASE (0x21E64C).

Because the string area sits at the end of the file and every pointer/offset
inside it is relative, a chart can change size as long as every later chart's
name pointer and offset table is shifted by the same amount.
"""

import re
import struct
from dataclasses import dataclass

BASE = 0x21E64C
CHART_SIZE = 1600
FIRST_CHART_NAME = "BGM001_1"
FIRST_TABLE = 0x1C        # table of the first chart (its name pointer is 0, not unique)
NAME_PTR_BACK = 12        # name pointer lives at table - 12

NAME_RE = re.compile(rb"BGM\d{3}_[1-4]H?\x00")

# One text symbol <-> one exact byte sequence (without the terminating null).
# The mapping is a bijection, so export -> import never alters a token.
# Meanings of the combined forms are not fully established; the labels below
# only describe the bytes (MOD = E2 96 B2 38 i.e. "▲8", short MOD = "▲").
SYMBOLS = {
    ".": b"",                                      # empty token
    "M": bytes.fromhex("E3 83 BB"),                # ・
    "O": bytes.fromhex("E2 97 8B"),                # ○
    "P": bytes.fromhex("E2 97 8F"),                # ●
    "X": bytes.fromhex("E2 97 8B E2 96 B2 38"),    # ○▲8  (older label "X")
    "Y": bytes.fromhex("E2 97 8F E2 96 B2 38"),    # ●▲8
    "Z": bytes.fromhex("E3 83 BB E2 96 B2 38"),    # ・▲8
    "S": bytes.fromhex("E2 97 8B E2 96 B2"),       # ○▲  (short modifier)
}
TOKEN_TO_SYMBOL = {token: symbol for symbol, token in SYMBOLS.items()}

UNKNOWN_SYMBOL = "?"   # exporter placeholder only; the importer rejects it

assert len(TOKEN_TO_SYMBOL) == len(SYMBOLS), "two symbols share the same bytes"
assert UNKNOWN_SYMBOL not in SYMBOLS


@dataclass
class Chart:
    name: str
    name_pos: int
    payload_start: int
    boundary: int
    table: int
    offsets: list

    @property
    def name_bytes(self):
        return self.name.encode("ascii") + b"\x00"


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------

def _find_table(data, name, name_pos):
    name_rel = name_pos - BASE

    if name == FIRST_CHART_NAME or name_rel == 0:
        return [FIRST_TABLE]

    if name_rel < 0:
        raise ValueError(f"{name}: name is located before BASE")

    packed = struct.pack("<I", name_rel)
    refs = []
    pos = 0

    while True:
        pos = data.find(packed, pos)
        if pos < 0:
            break
        refs.append(pos)
        pos += 1

    if not refs:
        raise ValueError(f"{name}: no name pointer found")

    return [ref + NAME_PTR_BACK for ref in refs]


def _choose_table(data, name, name_pos, payload_start, boundary):
    """The pointer bytes can occur more than once by coincidence (for example
    straddling two offset-table entries). Keep the candidate whose table
    actually matches the chart's payload."""
    candidates = _find_table(data, name, name_pos)
    valid = []

    for table in candidates:
        if table + 4 * CHART_SIZE > len(data):
            continue

        trial = Chart(
            name=name,
            name_pos=name_pos,
            payload_start=payload_start,
            boundary=boundary,
            table=table,
            offsets=list(struct.unpack_from(f"<{CHART_SIZE}I", data, table)),
        )

        try:
            _check_layout(data, trial)
        except ValueError:
            continue

        valid.append(table)

    if len(valid) == 1:
        return valid[0]

    if not valid and len(candidates) == 1:
        return candidates[0]      # let the caller report the specific problem

    raise ValueError(
        f"{name}: expected one matching name pointer, found {len(valid)} "
        f"valid of {len(candidates)} candidates"
    )


def _check_layout(data, chart):
    """Raise if the chart's payload is not 1600 contiguous null-terminated
    tokens that exactly match its offset table."""
    payload = data[chart.payload_start:chart.boundary]
    nulls = [m.start() for m in re.finditer(b"\x00", payload)]

    if len(nulls) != CHART_SIZE:
        raise ValueError(
            f"{chart.name}: expected {CHART_SIZE} tokens, "
            f"found {len(nulls)} terminators"
        )

    if nulls[-1] != len(payload) - 1:
        raise ValueError(f"{chart.name}: payload does not end with a terminator")

    starts = [0] + [n + 1 for n in nulls[:-1]]
    expected = [chart.payload_start + s - BASE for s in starts]

    if chart.offsets != expected:
        bad = next(
            i for i, (a, b) in enumerate(zip(chart.offsets, expected)) if a != b
        )
        raise ValueError(
            f"{chart.name}: offset table disagrees with payload at token {bad}"
        )


def parse_directory(data, tables=None):
    """Return every chart in the file, fully validated (like scan.py does).

    `tables` (optional) is a list of known offset-table positions, one per
    chart in file order. When given, tables are not searched for; instead each
    chart's stored name pointer is checked directly. verify() uses this so a
    coincidental repeat of a pointer value elsewhere in the file cannot cause
    a false error (the search used on an untouched file can be ambiguous)."""
    matches = list(NAME_RE.finditer(data))

    if not matches:
        raise ValueError("No chart names found")

    if tables is not None and len(tables) != len(matches):
        raise ValueError(
            f"Chart count changed: expected {len(tables)}, found {len(matches)}"
        )

    charts = []

    for i, match in enumerate(matches):
        name = match.group()[:-1].decode("ascii")
        boundary = matches[i + 1].start() if i + 1 < len(matches) else len(data)

        if tables is None:
            table = _choose_table(
                data, name, match.start(), match.end(), boundary
            )
        else:
            table = tables[i]
            name_rel = match.start() - BASE

            if not (name == FIRST_CHART_NAME or name_rel == 0):
                stored = struct.unpack_from(
                    "<I", data, table - NAME_PTR_BACK
                )[0]

                if stored != name_rel:
                    raise ValueError(f"{name}: name pointer mismatch")

        if table + 4 * CHART_SIZE > len(data):
            raise ValueError(f"{name}: offset table runs past end of file")

        offsets = list(struct.unpack_from(f"<{CHART_SIZE}I", data, table))

        chart = Chart(
            name=name,
            name_pos=match.start(),
            payload_start=match.end(),
            boundary=boundary,
            table=table,
            offsets=offsets,
        )
        _check_layout(data, chart)
        charts.append(chart)

    return charts


def find_chart(charts, name):
    found = [c for c in charts if c.name == name]

    if len(found) != 1:
        raise ValueError(
            f"{name}: expected exactly one occurrence, found {len(found)}"
        )

    return found[0]


# --------------------------------------------------------------------------
# Tokens <-> symbols
# --------------------------------------------------------------------------

def decode_tokens(data, chart):
    payload = data[chart.payload_start:chart.boundary]
    return payload[:-1].split(b"\x00")


def tokens_to_symbols(tokens):
    symbols = []
    unknown = []

    for index, token in enumerate(tokens):
        symbol = TOKEN_TO_SYMBOL.get(token)

        if symbol is None:
            symbols.append(UNKNOWN_SYMBOL)
            unknown.append((index, token))
        else:
            symbols.append(symbol)

    return "".join(symbols), unknown


def symbols_to_tokens(symbols):
    return [SYMBOLS[s] for s in symbols]


def encode_tokens(tokens):
    return b"".join(token + b"\x00" for token in tokens)


# --------------------------------------------------------------------------
# Rebuilding
# --------------------------------------------------------------------------

def rebuild(data, charts, replacements):
    """Return new file bytes with `replacements` ({chart name: [token bytes]})
    applied. Handles size changes: every chart's name pointer and offset table
    is recomputed, which is what scan.py does for the target and everything
    downstream of it."""
    names = {c.name for c in charts}
    missing = sorted(set(replacements) - names)

    if missing:
        raise ValueError(f"Charts not found in file: {', '.join(missing)}")

    for name, tokens in replacements.items():
        if len(tokens) != CHART_SIZE:
            raise ValueError(f"{name}: expected {CHART_SIZE} tokens")

    first = charts[0].name_pos

    for chart in charts:
        if (chart.table - NAME_PTR_BACK < 0
                or chart.table + 4 * CHART_SIZE > first):
            raise ValueError(
                f"{chart.name}: offset table is not located before the "
                "string area; relocation would corrupt it"
            )

    out = bytearray(data[:first])
    patches = []          # (position, packed bytes)
    pos = first

    for chart in charts:
        name_bytes = data[chart.name_pos:chart.payload_start]
        replaced = chart.name in replacements

        if replaced:
            tokens = replacements[chart.name]
            payload = encode_tokens(tokens)
        else:
            payload = data[chart.payload_start:chart.boundary]

        new_name_pos = pos
        new_payload_start = new_name_pos + len(name_bytes)
        shift = new_name_pos - chart.name_pos

        out += name_bytes
        out += payload
        pos += len(name_bytes) + len(payload)

        if shift:
            patches.append((
                chart.table - NAME_PTR_BACK,
                struct.pack("<I", new_name_pos - BASE),
            ))

        if replaced:
            offsets = []
            cursor = new_payload_start - BASE

            for token in tokens:
                offsets.append(cursor)
                cursor += len(token) + 1
        elif shift:
            offsets = [value + shift for value in chart.offsets]
        else:
            continue

        patches.append((chart.table, struct.pack(f"<{CHART_SIZE}I", *offsets)))

    for position, packed in patches:
        out[position:position + len(packed)] = packed

    return bytes(out)


def _outside_equal(a, b, ranges, limit):
    cursor = 0

    for start, end in sorted(ranges):
        if a[cursor:start] != b[cursor:start]:
            return False
        cursor = max(cursor, end)

    return a[cursor:limit] == b[cursor:limit]


def verify(original, old_charts, result, replacements):
    """Re-parse `result` and check it against `original`. Raises on problems."""
    # Full structural validation, using the known (unmoved) table positions.
    new_charts = parse_directory(result, tables=[c.table for c in old_charts])

    if [c.name for c in new_charts] != [c.name for c in old_charts]:
        raise ValueError("Chart list changed")

    ranges = []

    for old, new in zip(old_charts, new_charts):
        if old.table != new.table:
            raise ValueError(f"{old.name}: offset table moved")

        expected = replacements.get(old.name)

        if expected is None:
            expected = decode_tokens(original, old)

        if decode_tokens(result, new) != expected:
            raise ValueError(f"{old.name}: tokens differ from expectation")

        ranges.append((old.table - NAME_PTR_BACK, old.table - NAME_PTR_BACK + 4))
        ranges.append((old.table, old.table + 4 * CHART_SIZE))

    if not _outside_equal(original, result, ranges, old_charts[0].name_pos):
        raise ValueError("Header bytes changed outside pointers/offset tables")

"""Shared helpers for the Rhythm.dat chart tools (rhythm_export.py / rhythm_import.py).

Layout of Rhythm.dat, as implied by scan.py:

  * A header area at the start of the file holds, for every chart, a small
    record:  [name pointer (u32)] [8 more bytes] [1600 x u32 token offsets].
    The offset table starts 12 bytes after the name pointer.
  * The string area starts at the first chart name. It is a sequence of
        NAME\\0  TOKEN0\\0 TOKEN1\\0 ... TOKEN1599\\0
    for every chart, back to back, up to the end of the file.
  * Pointers and offsets are stored relative to the chart-region base, which is
    the end of the record table: base = 0x0C + count * stride (0x21E64C for the
    original file). The file header is the same container as Sound.dat:
    u32 stride (0x1960), u32 record count, u32 flag.

Because the string area sits at the end of the file and every pointer/offset
inside it is relative, a chart can change size as long as every later chart's
name pointer and offset table is shifted by the same amount, and charts can be
added by inserting records (the base moves with the record table, so existing
relative pointers stay valid).

Record (stride 0x1960 bytes, starting at 0x0C + k * stride):
    +0x00  chart ID  = song * 100 + (10 if Hard) + block
    +0x04  name pointer (relative to base)
    +0x08  0
    +0x0C  chart length field: round(non-empty tokens * 720000 / BPM)
           (+-1; identical for a chart and its Hard variant)
    +0x10  1600 token offsets (relative to base)
    +0x1910 80 zero bytes
Records are in ascending chart-ID order, like the chart region itself.
"""

import re
import struct
from dataclasses import dataclass

BASE = 0x21E64C           # value for the original file; derived from the header in general
HEADER = 0x0C
CHART_SIZE = 1600
FIRST_CHART_NAME = "BGM001_1"
FIRST_TABLE = 0x1C        # table of the first chart (its name pointer is 0, not unique)
RECORD_HEADER = 0x10      # bytes before the offset table inside a record
PAD = 80                  # zero bytes after the offset table
DURATION_BACK = 4         # chart length field lives at table - 4
ID_BACK = 16              # chart ID lives at table - 16
DURATION_FACTOR = 720000  # length field = non-empty tokens * 720000 / BPM
NAME_PTR_BACK = 12        # name pointer lives at table - 12

NAME_RE = re.compile(rb"BGM\d{3}_[1-4]H?\x00")
NAME_FULL_RE = re.compile(r"BGM(\d{3})_([1-4])(H?)")

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
    base: int = BASE

    @property
    def name_bytes(self):
        return self.name.encode("ascii") + b"\x00"


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------

def _find_table(data, name, name_pos, base):
    name_rel = name_pos - base

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


def _choose_table(data, name, name_pos, payload_start, boundary, base):
    """The pointer bytes can occur more than once by coincidence (for example
    straddling two offset-table entries). Keep the candidate whose table
    actually matches the chart's payload."""
    candidates = _find_table(data, name, name_pos, base)
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
            base=base,
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
    expected = [chart.payload_start + s - chart.base for s in starts]

    if chart.offsets != expected:
        bad = next(
            i for i, (a, b) in enumerate(zip(chart.offsets, expected)) if a != b
        )
        raise ValueError(
            f"{chart.name}: offset table disagrees with payload at token {bad}"
        )


def read_header(data):
    """(stride, count, flag, base) from the file header."""
    if len(data) < HEADER:
        raise ValueError("file too small for a Rhythm.dat header")

    stride, count, flag = struct.unpack_from("<III", data, 0)
    return stride, count, flag, HEADER + count * stride


def stride_tables(count, stride):
    """Offset-table positions implied by the header: one record per chart."""
    return [HEADER + k * stride + RECORD_HEADER for k in range(count)]


def parse_directory(data, tables=None):
    """Return every chart in the file, fully validated (like scan.py does).

    The chart-region base comes from the header (HEADER + count * stride), so
    files with added charts parse too.

    `tables` (optional) is a list of known offset-table positions, one per
    chart in file order. When given, tables are not searched for; instead each
    chart's stored name pointer is checked directly. verify() uses this so a
    coincidental repeat of a pointer value elsewhere in the file cannot cause
    a false error (the search used on an untouched file can be ambiguous)."""
    stride, count, _flag, base = read_header(data)
    matches = list(NAME_RE.finditer(data))

    if not matches:
        raise ValueError("No chart names found")

    if matches[0].start() != base:
        raise ValueError(
            f"first chart name at 0x{matches[0].start():X}, but the header "
            f"implies the chart region starts at 0x{base:X}"
        )

    if len(matches) != count:
        raise ValueError(
            f"header says {count} charts, found {len(matches)} names"
        )

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
                data, name, match.start(), match.end(), boundary, base
            )
        else:
            table = tables[i]
            name_rel = match.start() - base

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
            base=base,
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
# Chart IDs and the length field
# --------------------------------------------------------------------------

def chart_id_from_name(name):
    m = NAME_FULL_RE.fullmatch(name)

    if not m:
        raise ValueError(f"not a chart name: {name!r}")

    return int(m[1]) * 100 + (10 if m[3] else 0) + int(m[2])


def stored_chart_id(data, chart):
    return struct.unpack_from("<I", data, chart.table - ID_BACK)[0]


def stored_length_field(data, chart):
    return struct.unpack_from("<I", data, chart.table - DURATION_BACK)[0]


def length_field(tokens, bpm):
    """Chart length field: non-empty tokens * 720000 / BPM. In the original file
    302 of 342 charts match this exactly and the rest are off by one (rounding)."""
    if bpm <= 0:
        raise ValueError("BPM must be positive")

    used = sum(1 for t in tokens if t != b"")
    return round(used * DURATION_FACTOR / bpm)


def infer_bpm(data, chart):
    """BPM implied by an existing chart's length field (None if it has no notes)."""
    used = sum(1 for t in decode_tokens(data, chart) if t != b"")
    value = stored_length_field(data, chart)
    return used * DURATION_FACTOR / value if used and value else None


# --------------------------------------------------------------------------
# Rebuilding
# --------------------------------------------------------------------------

def build_file(data, charts, replacements=None, additions=None, lengths=None):
    """Return new file bytes.

    replacements: {chart name: [1600 token bytes]}    existing charts to rewrite
    additions:    {chart name: (tokens, length_field)} charts to insert
    lengths:      {chart name: length field}           new length field for replaced charts

    The whole file is regenerated: header (count updated), one record per
    chart in ascending chart-ID order, then the chart region. Name pointers and
    offset tables of every chart are recomputed relative to the new base, and
    every other record byte is copied unchanged from the original."""
    replacements = replacements or {}
    additions = additions or {}
    lengths = lengths or {}

    stride, count, flag, old_base = read_header(data)

    if stride != RECORD_HEADER + 4 * CHART_SIZE + PAD:
        raise ValueError(f"unexpected record stride 0x{stride:X}")

    if count != len(charts):
        raise ValueError("chart list does not match the header")

    names = {c.name for c in charts}
    missing = sorted(set(replacements) - names)

    if missing:
        raise ValueError(f"Charts not found in file: {', '.join(missing)}")

    clash = sorted(set(additions) & names)

    if clash:
        raise ValueError(f"Charts already exist: {', '.join(clash)}")

    bad_len = sorted(set(lengths) - set(replacements))

    if bad_len:
        raise ValueError(f"length given for charts that are not replaced: {bad_len}")

    for name, tokens in {**replacements, **{n: v[0] for n, v in additions.items()}}.items():
        if len(tokens) != CHART_SIZE:
            raise ValueError(f"{name}: expected {CHART_SIZE} tokens")

    # one entry per chart, existing or new
    entries = []

    for k, chart in enumerate(charts):
        record = data[HEADER + k * stride:HEADER + (k + 1) * stride]

        if chart.table != HEADER + k * stride + RECORD_HEADER:
            raise ValueError(f"{chart.name}: record is not where the header implies")

        cid = struct.unpack_from("<I", record, 0)[0]

        if cid != chart_id_from_name(chart.name):
            raise ValueError(f"{chart.name}: stored chart ID {cid} does not match its name")

        entries.append({
            "name": chart.name, "id": cid, "record": bytearray(record),
            "name_bytes": data[chart.name_pos:chart.payload_start],
            "tokens": replacements.get(chart.name),
            "payload": data[chart.payload_start:chart.boundary],
            "length": lengths.get(chart.name),
        })

    for name, (tokens, length) in additions.items():
        record = bytearray(stride)
        struct.pack_into("<I", record, 0, chart_id_from_name(name))
        struct.pack_into("<I", record, 12, length)
        entries.append({
            "name": name, "id": chart_id_from_name(name), "record": record,
            "name_bytes": name.encode("ascii") + b"\x00",
            "tokens": tokens, "payload": None, "length": None,
        })

    entries.sort(key=lambda e: e["id"])               # stable: existing order kept
    ids = [e["id"] for e in entries]

    if len(set(ids)) != len(ids):
        raise ValueError("duplicate chart IDs")

    new_count = len(entries)
    base = HEADER + new_count * stride
    region = bytearray()

    for e in entries:
        rec = e["record"]
        start = len(region)
        region += e["name_bytes"]
        payload_start = len(region)

        if e["tokens"] is not None:
            offsets = []
            cursor = payload_start

            for token in e["tokens"]:
                offsets.append(cursor)
                cursor += len(token) + 1

            region += encode_tokens(e["tokens"])
        else:
            region += e["payload"]
            offsets = None

        struct.pack_into("<I", rec, 4, start)                       # name pointer

        if offsets is None:
            # unchanged payload: shift the original offsets onto the new layout
            old_offsets = struct.unpack_from(f"<{CHART_SIZE}I", rec, RECORD_HEADER)
            offsets = [o - old_offsets[0] + payload_start for o in old_offsets]

        struct.pack_into(f"<{CHART_SIZE}I", rec, RECORD_HEADER, *offsets)

        if e["length"] is not None:
            struct.pack_into("<I", rec, 12, e["length"])

    out = bytearray(struct.pack("<III", stride, new_count, flag))

    for e in entries:
        out += e["record"]

    assert len(out) == base
    out += region
    return bytes(out)


def rebuild(data, charts, replacements, lengths=None):
    """Replace existing charts only (same chart list)."""
    return build_file(data, charts, replacements=replacements, lengths=lengths)


def _record_diff_ok(old, new, allowed):
    """Records must match except at the byte ranges in `allowed`."""
    if len(old) != len(new):
        return False

    mask = bytearray(len(old))

    for a, b in allowed:
        mask[a:b] = b"\x01" * (b - a)

    return all(mask[i] or old[i] == new[i] for i in range(len(old)))


def verify(original, old_charts, result, replacements=None, additions=None,
           lengths=None):
    """Re-parse `result` and check it against `original`. Raises on problems."""
    replacements = replacements or {}
    additions = additions or {}
    lengths = lengths or {}

    stride, old_count, flag, _ = read_header(original)
    new_stride, new_count, new_flag, new_base = read_header(result)

    if (new_stride, new_flag) != (stride, flag):
        raise ValueError("header stride/flag changed")

    if new_count != old_count + len(additions):
        raise ValueError("chart count is wrong")

    new_charts = parse_directory(result, tables=stride_tables(new_count, stride))
    by_old = {c.name: c for c in old_charts}
    old_index = {c.name: k for k, c in enumerate(old_charts)}
    new_names = [c.name for c in new_charts]
    expected_ids = sorted(
        [chart_id_from_name(n) for n in by_old] + [chart_id_from_name(n) for n in additions]
    )

    if [chart_id_from_name(n) for n in new_names] != expected_ids:
        raise ValueError("charts are not in ascending chart-ID order")

    if set(new_names) != set(by_old) | set(additions):
        raise ValueError("chart list is wrong")

    existing_order = [n for n in new_names if n in by_old]

    if existing_order != [c.name for c in old_charts]:
        raise ValueError("existing charts changed order")

    for k, new in enumerate(new_charts):
        rec = result[HEADER + k * stride:HEADER + (k + 1) * stride]

        if struct.unpack_from("<I", rec, 0)[0] != chart_id_from_name(new.name):
            raise ValueError(f"{new.name}: record chart ID wrong")

        if new.name in additions:
            tokens, length = additions[new.name]

            if decode_tokens(result, new) != tokens:
                raise ValueError(f"{new.name}: tokens differ from expectation")

            if stored_length_field(result, new) != length:
                raise ValueError(f"{new.name}: length field wrong")

            if rec[8:12] != bytes(4) or rec[RECORD_HEADER + 4 * CHART_SIZE:] != bytes(PAD):
                raise ValueError(f"{new.name}: record padding is not zero")

            continue

        old = by_old[new.name]
        expected = replacements.get(new.name)

        if expected is None:
            expected = decode_tokens(original, old)

        if decode_tokens(result, new) != expected:
            raise ValueError(f"{new.name}: tokens differ from expectation")

        k_old = old_index[old.name]
        old_rec = original[HEADER + k_old * stride:HEADER + (k_old + 1) * stride]
        allowed = [(4, 8), (RECORD_HEADER, RECORD_HEADER + 4 * CHART_SIZE)]

        if new.name in lengths:
            allowed.append((12, 16))

        if not _record_diff_ok(old_rec, rec, allowed):
            raise ValueError(f"{new.name}: record bytes changed outside pointers/offsets")

        if new.name in lengths and stored_length_field(result, new) != lengths[new.name]:
            raise ValueError(f"{new.name}: length field wrong")

    if len(result) != new_base + sum(
            c.boundary - c.name_pos for c in new_charts):
        raise ValueError("unaccounted bytes in the file")

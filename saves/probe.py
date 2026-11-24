#!/usr/bin/env python3
"""Unlock songs in a Mad Rat Dead save file ("System").

  python probe.py System 0x2D --sound Out.dat          # unlock the song with ID 0x2D
  python probe.py System 0x2C 0x2D 0x66 --sound Out.dat  # several IDs
  python probe.py System 43 44 --index                 # raw record indices, no Sound.dat needed
  python probe.py System 0x2D --sound Out.dat --inplace  # edit System itself (keeps System.bak)

Unlock flags are keyed by the song's RECORD INDEX in Sound.dat (position in the
file), not by its ID: index n -> flag 500+n (open) and 600+n (played). With IDs,
pass the Sound.dat you are actually using so the index can be looked up.
"""
import argparse
import shutil
import struct
import sys

MAFLAG_TAG = b"maFlag"
OPEN_BASE, PLAYED_BASE = 500, 600


def parse_num(text):
    return int(text, 0)


def sound_ids(path):
    data = open(path, "rb").read()
    stride, count, _flag = struct.unpack_from("<III", data, 0)
    return [struct.unpack_from("<I", data, 0x0C + i * stride)[0] for i in range(count)]


def payload_offset(data):
    tag = data.find(MAFLAG_TAG)
    if tag < 0:
        raise SystemExit("maFlag tag not found: is this the 'System' save file?")
    po = tag + len(MAFLAG_TAG)
    if data[po:po + 2] == b"\x01\x07":
        po += 2
    if data[po:po + 1] == b"\x00":
        po += 1
    return po + 8


def set_bit(buf, payload_off, flag_id):
    byte, bit = flag_id >> 3, flag_id & 7
    old = buf[payload_off + byte]
    buf[payload_off + byte] = old | (1 << bit)
    return old, buf[payload_off + byte]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("save", help="the 'System' save file")
    ap.add_argument("songs", nargs="+", type=parse_num, help="song IDs (default) or record indices (--index); decimal or 0x hex")
    ap.add_argument("--sound", help="Sound.dat in use (needed to turn IDs into record indices)")
    ap.add_argument("--index", action="store_true", help="arguments are record indices, not IDs")
    ap.add_argument("--inplace", action="store_true", help="modify the save itself (a .bak copy is kept)")
    ap.add_argument("--output", help="output file (default: <save>.probe)")
    args = ap.parse_args()

    if args.index:
        indices = list(args.songs)
    else:
        if not args.sound:
            sys.exit("IDs need --sound Sound.dat to find their record index (or use --index)")
        ids = sound_ids(args.sound)
        indices = []
        for song_id in args.songs:
            if song_id not in ids:
                sys.exit(f"ID 0x{song_id:X} is not in {args.sound}")
            indices.append(ids.index(song_id))

    data = bytearray(open(args.save, "rb").read())
    po = payload_offset(data)
    print(f"payload at 0x{po:X}")

    for song, idx in zip(args.songs, indices):
        label = f"index {idx}" if args.index else f"ID 0x{song:X} = index {idx}"
        for base in (OPEN_BASE, PLAYED_BASE):
            flag = base + idx
            if po + (flag >> 3) >= len(data):
                sys.exit(f"flag {flag} is outside the save file")
            old, new = set_bit(data, po, flag)
            print(f"  {label}: flag {flag} -> byte {flag >> 3} bit {flag & 7}: 0x{old:02X} -> 0x{new:02X}")

    if args.inplace:
        shutil.copyfile(args.save, args.save + ".bak")
        out = args.save
    else:
        out = args.output or args.save + ".probe"
    open(out, "wb").write(data)
    print(f"wrote {out}" + (f" (backup: {args.save}.bak)" if args.inplace else ""))


if __name__ == "__main__":
    main()

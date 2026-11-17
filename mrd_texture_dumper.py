# Mad Rat Dead texture dumper for Anime_EN.dat (PS4 and/or Switch).
#
#   PS4 only:      python mrd_textures.py ykcmp.exe --ps4 Anime_EN_PS4.dat --out out
#   Switch only:   python mrd_textures.py ykcmp.exe --switch Anime_EN_Switch.dat --out out
#   Both:          python mrd_textures.py ykcmp.exe --ps4 A.dat --switch B.dat --out out
#   Both + compare python mrd_textures.py ykcmp.exe --ps4 A.dat --switch B.dat --out out --compare
#
# Options:
#   --only-diff   with --compare (or both files): only textures whose stored size differs between builds
#   --indices 794,5,100-120   only these block indices
#   --swap-rb     force every RGBA8 texture to be read as BGRA
#   (RGBA8 textures whose record byte 0x54 is 2 are read as BGRA automatically; --no-auto-swap turns that off)
#   --as bc3|bc5|bc1|bc7  experimental: decode the selected textures as this format instead of the detected one
#   --mips        also write every mip level (NNNN_WxH_mipN.png) of the textures that have a chain
#   --swap-variant3  obsolete (variant 3 is BC3, now detected automatically); kept so old command lines still work
# The format comes from the record bytes (0x33, 0x54); unknown pairs are reported and skipped.
#
# Output (each folder only when that platform is dumped):
#   out/ps4/NNNN_WxH.png        PS4 textures (Morton 8x8 tiles)
#   out/switch/NNNN_WxH.png     Switch textures (block-linear), at their stored size
#   out/ps4_index.csv, out/switch_index.csv   per texture: size, kind, YKCMP bytes and ratio, notes
#   with --compare:
#     out/side/NNNN_*.png       PS4 | Switch at the same scale, for textures whose stored size differs
#     out/compare.csv           sizes, compression, PSNR of Switch vs PS4, identical flag
# Textures are identified by block index only. Names are not used.
import sys, os, struct, subprocess, csv, argparse
import numpy as np


def morton_xy(m):
    x = y = 0
    for k in range(3):
        x |= ((m >> (2 * k)) & 1) << k
        y |= ((m >> (2 * k + 1)) & 1) << k
    return x, y


MX = np.array([morton_xy(m)[0] for m in range(64)])
MY = np.array([morton_xy(m)[1] for m in range(64)])
pad8 = lambda v: -(-v // 8) * 8
ceil4 = lambda v: -(-v // 4)


def untile_ps4(data, ew, eh, B):
    """PS4 8x8-element Morton tiles -> (eh, ew, B) array, or None if the data is too short."""
    ewp, ehp = pad8(ew), pad8(eh)
    n = ewp * ehp
    if len(data) < n * B:
        return None
    arr = np.frombuffer(data, np.uint8, count=n * B).reshape(n, B)
    i = np.arange(n)
    t, m = i // 64, i % 64
    x = (t % (ewp // 8)) * 8 + MX[m]
    y = (t // (ewp // 8)) * 8 + MY[m]
    lin = np.empty_like(arr)
    lin[y * ewp + x] = arr
    return lin.reshape(ehp, ewp, B)[:eh, :ew]


def switch_units(ew, eh, B, bhg, wg):
    """For every element (y, x), the index (in elements) where Tegra block-linear stores it."""
    y, x = np.mgrid[0:eh, 0:ew].astype(np.int64)
    xb = x * B
    gob = ((y // (8 * bhg)) * 512 * bhg * wg + (xb // 64) * 512 * bhg + ((y % (8 * bhg)) // 8) * 512)
    xr, yr = xb % 64, y % 8
    off = gob + (xr // 32) * 256 + (yr // 2) * 64 + ((xr % 32) // 16) * 32 + (yr % 2) * 16 + (xr % 16)
    return off // B


def roundup(a, b):
    return -(-a // b) * b


def pow2ceil(n):
    p = 1
    while p < n:
        p *= 2
    return p


def level_dims(w, h, n, is_bc):
    lw, lh = max(w >> n, 1), max(h >> n, 1)
    return lw, lh, ((lw + 3) // 4, (lh + 3) // 4) if is_bc else (lw, lh)


def plan_switch(w, h, B, is_bc, b0, b1, levels):
    """Per level (ew, eh, pitch_in_gobs, block_height, size_bytes) for the Switch layout (see the format notes)."""
    out = []
    for n in range(levels):
        _, _, (ew, eh) = level_dims(w, h, n, is_bc)
        wmin = -(-ew * B // 64)
        if n == 0:
            bh, wg = 1 << b0, roundup(wmin, 1 << b1)
        else:
            bh, wg = min(1 << b0, pow2ceil(-(-eh // 8))), wmin
        out.append((ew, eh, wg, bh, wg * roundup(eh, 8 * bh) * 64))
    return out


def plan_ps4(w, h, B, is_bc, levels):
    """Per level (ew, eh, size_bytes): levels packed tightly, each rounded up to whole 8x8-element tiles."""
    out = []
    for n in range(levels):
        _, _, (ew, eh) = level_dims(w, h, n, is_bc)
        out.append((ew, eh, pad8(ew) * pad8(eh) * B))
    return out


def untile_switch_level(data, ew, eh, B, wg, bh):
    u = switch_units(ew, eh, B, bh, wg)
    if (u.max() + 1) * B > len(data):
        return None
    return np.frombuffer(data, np.uint8, count=len(data) // B * B).reshape(-1, B)[u]


def untile_switch(data, ew, eh, B, rec_bhg):
    """Block-linear -> (eh, ew, B) array. Tries the record's block height first, then smaller ones.
    The row pitch (in GOBs) is deduced from the data size when it fits exactly (padded sizes), else the minimum."""
    wg_min = -(-ew * B // 64)
    cands = [rec_bhg] + [b for b in (16, 8, 4, 2, 1) if b != rec_bhg]
    pick, note = None, ""
    for bhg in cands:
        rows = -(-eh // (8 * bhg)) * 8 * bhg
        if len(data) % (rows * 64) == 0 and len(data) // (rows * 64) >= wg_min:
            pick = (bhg, len(data) // (rows * 64))
            if bhg != rec_bhg:
                note = f"block height {bhg} fits the data size better than the record's {rec_bhg}"
            break
    if pick is None:
        pick, note = (rec_bhg, wg_min), "data size matched no layout exactly (mip chain?); used the minimum pitch"
    bhg, wg = pick
    u = switch_units(ew, eh, B, bhg, wg)
    if (u.max() + 1) * B > len(data):
        return None, "data too short for this layout"
    arr = np.frombuffer(data, np.uint8, count=len(data) // B * B).reshape(-1, B)
    return arr[u], note


def find_blocks(d):
    res, pos = [], 0
    while True:
        pos = d.find(b"YKCMP_V1", pos)
        if pos < 0:
            return res
        res.append(pos)
        pos += 8


def record(d, off):
    r = d[off - 192:off]
    w, h = struct.unpack_from("<HH", r, 0x34)
    return dict(w=w, h=h, fmt=r[0x33], dsize=struct.unpack_from("<I", r, 0x6c)[0],
                csize=struct.unpack_from("<I", r, 0x70)[0], f74=r[0x74], f75=r[0x75], v54=r[0x54], levels=max(r[0x65], 1))


# (record byte 0x33, record byte 0x54) -> (codec, bytes per element, red/blue swapped)
FORMATS = {(7, 6): ("bc7", 16, False), (0, 6): ("bc7", 16, False), (7, 3): ("bc3", 16, False),
           (3, 2): ("bc1", 8, False), (0, 1): ("rgba8", 4, False), (0, 2): ("rgba8", 4, True)}


def kind_of(rec):
    """-> (kind, bytes per element, stored as BGRA). Raises on a (0x33, 0x54) pair that has not been seen."""
    try:
        return FORMATS[(rec["fmt"], rec["v54"])]
    except KeyError:
        raise ValueError(f"unknown format pair (0x33={rec['fmt']:#04x}, 0x54={rec['v54']:#04x})")


def decode(lin, kind, w, h, swap_rb):
    from PIL import Image
    if kind == "rgba8":
        return Image.frombytes("RGBA", (w, h), lin.tobytes(), "raw", "BGRA" if swap_rb else "RGBA")
    import texture2ddecoder
    ew, eh = ceil4(w), ceil4(h)
    pw, ph = ew * 4, eh * 4
    fn = {"bc1": texture2ddecoder.decode_bc1, "bc3": texture2ddecoder.decode_bc3,
          "bc5": texture2ddecoder.decode_bc5, "bc7": texture2ddecoder.decode_bc7}[kind]
    img = Image.frombytes("RGBA", (pw, ph), fn(lin.tobytes(), pw, ph), "raw", "BGRA").crop((0, 0, w, h))
    if swap_rb:
        r, g, b, a = img.split()
        img = Image.merge("RGBA", (b, g, r, a))
    return img


def decompress(yk, dat, off, tmp):
    subprocess.run([yk, "-a", hex(off), dat, tmp], check=True, capture_output=True)
    with open(tmp, "rb") as f:
        return f.read()


def parse_indices(text, n):
    out = set()
    for part in text.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-")
            out.update(range(int(a), int(b) + 1))
        elif part:
            out.add(int(part))
    return sorted(i for i in out if 0 <= i < n)


def dump_one(plat, dat, d, off, rec, kind, B, yk, tmp, swap_rb, mips=False):
    """Returns (PIL image of the base level, note, list of (level, image) for levels 1.. when mips=True)."""
    data = decompress(yk, dat, off, tmp)
    w, h, levels, is_bc = rec["w"], rec["h"], rec["levels"], kind != "rgba8"
    ew, eh = level_dims(w, h, 0, is_bc)[2]
    extra, note = [], ""
    if plat == "ps4":
        plan = plan_ps4(w, h, B, is_bc, levels)
        if sum(p[2] for p in plan) > len(data):
            plan = plan_ps4(w, h, B, is_bc, 1)          # chain does not fit; base level only
            if levels > 1:
                note = "mip chain layout does not fit the data; base level only"
        off_ = 0
        for n, (lew, leh, size) in enumerate(plan):
            lin = untile_ps4(data[off_:off_ + size], lew, leh, B)
            off_ += size
            if lin is None:
                raise ValueError("ps4: data too short")
            lw, lh = level_dims(w, h, n, is_bc)[:2]
            if n == 0:
                base = decode(lin, kind, lw, lh, swap_rb)
            elif mips:
                extra.append((n, decode(lin, kind, lw, lh, swap_rb)))
        return base, note, extra
    plan = plan_switch(w, h, B, is_bc, min(rec["f74"], 4), rec["f75"], levels)
    if sum(p[4] for p in plan) == len(data):             # the record explains the whole data block
        off_ = 0
        for n, (lew, leh, wg, bh, size) in enumerate(plan):
            lin = untile_switch_level(data[off_:off_ + size], lew, leh, B, wg, bh)
            off_ += size
            if lin is None:
                raise ValueError("switch: data too short")
            lw, lh = level_dims(w, h, n, is_bc)[:2]
            if n == 0:
                base = decode(lin, kind, lw, lh, swap_rb)
            elif mips:
                extra.append((n, decode(lin, kind, lw, lh, swap_rb)))
        return base, note, extra
    # layout not explained by the record (blocks 139 and 294 are known cases): old search, base level only
    lin, note = untile_switch(data, ew, eh, B, 1 << min(rec["f74"], 4))
    if lin is None:
        raise ValueError(f"switch: {note}")
    note = (note + "; " if note else "") + "layout does not match the record; base level guessed" + ("" if levels == 1 else f" ({levels} levels not split)")
    return decode(lin, kind, w, h, swap_rb), note, []


def main(argv=None):
    from PIL import Image
    ap = argparse.ArgumentParser(description="Dump Mad Rat Dead textures from Anime_EN.dat (PS4 and/or Switch).")
    ap.add_argument("ykcmp", help="path to ykcmp.exe")
    ap.add_argument("--ps4", help="PS4 Anime_EN.dat")
    ap.add_argument("--switch", help="Switch Anime_EN.dat")
    ap.add_argument("--out", required=True, help="output folder")
    ap.add_argument("--compare", action="store_true", help="with both files: side-by-side images and compare.csv")
    ap.add_argument("--only-diff", action="store_true", help="only textures whose stored size differs (needs both files)")
    ap.add_argument("--indices", help="only these block indices, e.g. 794,5,100-120")
    ap.add_argument("--swap-rb", action="store_true", help="force RGBA8 textures to be read as BGRA (all of them)")
    ap.add_argument("--no-auto-swap", action="store_true", help="do not swap red/blue for RGBA8 textures whose record byte 0x54 is 2")
    ap.add_argument("--as", dest="force_kind", choices=["bc1", "bc3", "bc5", "bc7"],
                    help="experimental: decode every selected texture as this block format instead of the detected one")
    ap.add_argument("--mips", action="store_true", help="also write every mip level of textures that have a chain")
    ap.add_argument("--swap-variant3", action="store_true", help="obsolete, ignored (variant 3 is BC3 and is detected automatically)")
    a = ap.parse_args(argv)
    if not (a.ps4 or a.switch):
        ap.error("give --ps4 and/or --switch")
    both = bool(a.ps4 and a.switch)
    if (a.compare or a.only_diff) and not both:
        ap.error("--compare and --only-diff need both --ps4 and --switch")

    plats = {}
    for plat, path in (("ps4", a.ps4), ("switch", a.switch)):
        if path:
            d = open(path, "rb").read()
            plats[plat] = dict(path=path, d=d, blocks=find_blocks(d))
            os.makedirs(os.path.join(a.out, plat), exist_ok=True)
            print(f"{plat}: {len(plats[plat]['blocks'])} blocks")
    if both and len(plats["ps4"]["blocks"]) != len(plats["switch"]["blocks"]):
        print("block counts differ; pairing by index would be wrong, stopping")
        return 1
    if a.compare:
        os.makedirs(os.path.join(a.out, "side"), exist_ok=True)
    tmp = os.path.join(a.out, "_tmp.dec")
    n = len(next(iter(plats.values()))["blocks"])
    todo = parse_indices(a.indices, n) if a.indices else list(range(n))

    idx_rows = {p: [["idx", "kind", "width", "height", "ykcmp_bytes", "decompressed_bytes", "ratio", "note", "variant", "levels"]] for p in plats}
    cmp_rows = [["idx", "kind", "ps4_w", "ps4_h", "sw_w", "sw_h", "ps4_csize", "ps4_dsize", "ps4_ratio",
                 "sw_csize", "sw_dsize", "sw_ratio", "identical_to_ps4", "psnr_db", "alpha_psnr_db", "note"]]
    tot = {p: [0, 0] for p in plats}      # [compressed, decompressed]
    psnrs, same_total, same_ok = [], 0, 0

    for k, idx in enumerate(todo):
        recs = {p: record(v["d"], v["blocks"][idx]) for p, v in plats.items()}
        # the PS4 record decides the format when both builds are present
        try:
            kind, B, bgra = kind_of(recs["ps4"] if "ps4" in recs else recs["switch"])
        except ValueError as e:
            print(f"  block {idx}: FAILED: {e}", file=sys.stderr, flush=True)
            for p in plats:
                idx_rows[p].append([idx, "?", recs[p]["w"], recs[p]["h"], recs[p]["csize"], recs[p]["dsize"], "", f"FAILED: {e}", "", ""])
            continue
        if a.force_kind:
            kind, B = a.force_kind, {"bc1": 8, "bc3": 16, "bc5": 16, "bc7": 16}[a.force_kind]
        diff = both and (recs["ps4"]["w"], recs["ps4"]["h"]) != (recs["switch"]["w"], recs["switch"]["h"])
        if a.only_diff and not diff:
            continue
        imgs, notes = {}, []
        for p, v in plats.items():
            rec = recs[p]
            note = ""
            swap = kind == "rgba8" and (a.swap_rb or (not a.no_auto_swap and bgra))
            try:
                img, note, extra = dump_one(p, v["path"], v["d"], v["blocks"][idx], rec, kind, B, a.ykcmp, tmp, swap, a.mips)
                if swap:
                    note = (note + "; " if note else "") + f"red/blue swapped (record byte 0x54 = {rec['v54']})"
                img.save(os.path.join(a.out, p, f"{idx:04d}_{rec['w']}x{rec['h']}.png"))
                for n, mimg in extra:
                    mimg.save(os.path.join(a.out, p, f"{idx:04d}_{rec['w']}x{rec['h']}_mip{n}.png"))
                imgs[p] = img
            except Exception as e:
                note = f"FAILED: {type(e).__name__}: {e}"
                print(f"  {p} block {idx}: {note}", file=sys.stderr, flush=True)
            if note:
                notes.append(f"{p}: {note}")
            tot[p][0] += rec["csize"]; tot[p][1] += rec["dsize"]
            idx_rows[p].append([idx, kind, rec["w"], rec["h"], rec["csize"], rec["dsize"],
                                round(rec["csize"] / rec["dsize"], 3), note, rec["v54"], rec["levels"]])
        if a.compare:
            rp, rs = recs["ps4"], recs["switch"]
            ident, psnr, apsnr = "", "", ""
            if "ps4" in imgs and "switch" in imgs:
                ip, isw = imgs["ps4"], imgs["switch"]
                if not diff:
                    ident = bool(np.array_equal(np.asarray(ip), np.asarray(isw)))
                    same_total += 1; same_ok += ident
                else:
                    # compare over black, so the (meaningless) colour of fully transparent pixels does not count
                    black = Image.new("RGBA", ip.size, (0, 0, 0, 255))
                    pa = np.asarray(Image.alpha_composite(black, ip).convert("RGB"), dtype=np.float64)
                    sb = Image.alpha_composite(Image.new("RGBA", isw.size, (0, 0, 0, 255)), isw).convert("RGB").resize(ip.size, Image.BICUBIC)
                    mse = float(np.mean((pa - np.asarray(sb, dtype=np.float64)) ** 2))
                    psnr = round(10 * np.log10(255 ** 2 / mse), 2) if mse > 0 else "inf"
                    ma = float(np.mean((np.asarray(ip.getchannel("A"), dtype=np.float64) -
                                        np.asarray(isw.getchannel("A").resize(ip.size, Image.BICUBIC), dtype=np.float64)) ** 2))
                    apsnr = round(10 * np.log10(255 ** 2 / ma), 2) if ma > 0 else "inf"
                    if psnr != "inf":
                        psnrs.append(psnr)
                    canvas = Image.new("RGBA", (ip.width * 2 + 16, ip.height), (60, 60, 60, 255))
                    canvas.paste(ip, (0, 0))
                    canvas.paste(isw.resize(ip.size, Image.NEAREST), (ip.width + 16, 0))
                    canvas.save(os.path.join(a.out, "side", f"{idx:04d}_ps4_{ip.width}x{ip.height}_vs_switch_{isw.width}x{isw.height}.png"))
            cmp_rows.append([idx, kind, rp["w"], rp["h"], rs["w"], rs["h"], rp["csize"], rp["dsize"], round(rp["csize"] / rp["dsize"], 3),
                             rs["csize"], rs["dsize"], round(rs["csize"] / rs["dsize"], 3), ident, psnr, apsnr, "; ".join(notes)])
        if k % 50 == 0:
            print("done", k, "of", len(todo), flush=True)

    if os.path.exists(tmp):
        os.remove(tmp)
    for p, rows in idx_rows.items():
        with open(os.path.join(a.out, f"{p}_index.csv"), "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(rows)
        body = rows[1:]
        bad = sum(1 for r in body if "FAILED" in r[7])
        print(f"{p}: written {len(body) - bad}, failed {bad}; YKCMP {tot[p][1]} -> {tot[p][0]} bytes "
              f"({100 * tot[p][0] / max(tot[p][1], 1):.1f}% of decompressed size)")
    if a.compare:
        with open(os.path.join(a.out, "compare.csv"), "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(cmp_rows)
        print(f"same-size textures identical after decoding: {same_ok} of {same_total}")
        if psnrs:
            print("different-size textures: %d  PSNR over black of Switch (bicubic upscaled) vs PS4: min %.1f  median %.1f  max %.1f dB" % (
                len(psnrs), min(psnrs), float(np.median(psnrs)), max(psnrs)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

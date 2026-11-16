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
#   --swap-rb     treat RGBA8 textures as BGRA
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
                csize=struct.unpack_from("<I", r, 0x70)[0], f74=r[0x74])


def kind_of(rec):
    if rec["fmt"] == 3:
        return "bc1", 8
    if rec["fmt"] == 0 and rec["dsize"] / (rec["w"] * rec["h"]) >= 3.9:
        return "rgba8", 4
    return "bc7", 16          # format byte 07, and byte 00 with 1 byte/pixel, are both BC7


def decode(lin, kind, w, h, swap_rb):
    from PIL import Image
    import texture2ddecoder
    if kind == "rgba8":
        return Image.frombytes("RGBA", (w, h), lin.tobytes(), "raw", "BGRA" if swap_rb else "RGBA")
    ew, eh = ceil4(w), ceil4(h)
    pw, ph = ew * 4, eh * 4
    fn = texture2ddecoder.decode_bc1 if kind == "bc1" else texture2ddecoder.decode_bc7
    img = Image.frombytes("RGBA", (pw, ph), fn(lin.tobytes(), pw, ph), "raw", "BGRA")
    return img.crop((0, 0, w, h))


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


def dump_one(plat, dat, d, off, rec, kind, B, yk, tmp, swap_rb):
    """Returns (PIL image, note). Raises on failure."""
    data = decompress(yk, dat, off, tmp)
    w, h = rec["w"], rec["h"]
    ew, eh = (w, h) if kind == "rgba8" else (ceil4(w), ceil4(h))
    if plat == "ps4":
        lin = untile_ps4(data, ew, eh, B)
        note = "" if lin is not None else "data too short"
    else:
        lin, note = untile_switch(data, ew, eh, B, 1 << min(rec["f74"], 4))
    if lin is None:
        raise ValueError(f"{plat}: {note}")
    return decode(lin, kind, w, h, swap_rb), note


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
    ap.add_argument("--swap-rb", action="store_true", help="RGBA8 textures as BGRA")
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

    idx_rows = {p: [["idx", "kind", "width", "height", "ykcmp_bytes", "decompressed_bytes", "ratio", "note"]] for p in plats}
    cmp_rows = [["idx", "kind", "ps4_w", "ps4_h", "sw_w", "sw_h", "ps4_csize", "ps4_dsize", "ps4_ratio",
                 "sw_csize", "sw_dsize", "sw_ratio", "identical_to_ps4", "psnr_db", "alpha_psnr_db", "note"]]
    tot = {p: [0, 0] for p in plats}      # [compressed, decompressed]
    psnrs, same_total, same_ok = [], 0, 0

    for k, idx in enumerate(todo):
        recs = {p: record(v["d"], v["blocks"][idx]) for p, v in plats.items()}
        # the PS4 record decides the format when both builds are present; it has no padding
        kind, B = kind_of(recs["ps4"] if "ps4" in recs else recs["switch"])
        diff = both and (recs["ps4"]["w"], recs["ps4"]["h"]) != (recs["switch"]["w"], recs["switch"]["h"])
        if a.only_diff and not diff:
            continue
        imgs, notes = {}, []
        for p, v in plats.items():
            rec = recs[p]
            note = ""
            try:
                img, note = dump_one(p, v["path"], v["d"], v["blocks"][idx], rec, kind, B, a.ykcmp, tmp, a.swap_rb)
                img.save(os.path.join(a.out, p, f"{idx:04d}_{rec['w']}x{rec['h']}.png"))
                imgs[p] = img
            except Exception as e:
                note = f"FAILED: {e}"
            if note:
                notes.append(f"{p}: {note}")
            tot[p][0] += rec["csize"]; tot[p][1] += rec["dsize"]
            idx_rows[p].append([idx, kind, rec["w"], rec["h"], rec["csize"], rec["dsize"],
                                round(rec["csize"] / rec["dsize"], 3), note])
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

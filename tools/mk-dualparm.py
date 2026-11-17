#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RK3399-MID —— 把 armbian 标准 GPT 镜像转成「双 PARM」变体。

背景（实测，非推测）
--------------------
2026-11-11 22:0x 实测：本板 BootROM 的 boot0 硬件分区引导已失效，退回 user 区
LBA64 的 IDB；而该 IDB 报告给 rockusb 的 storage 起点是**物理 LBA8192**，于是

    逻辑 LBA x  ==  物理 LBA x + 8192

实证：当前逻辑 LBA0 的 8 扇区与全盘备份物理 LBA8192 逐字节相同（LOADER）；
      逻辑 LBA8192 与备份物理 LBA16384 相同（BL3X f8 00 04 00）。

后果有两条，必须同时解决：
  1. 这个 miniloader 在「自己的 LBA0」= 物理 8192 找 PARM，那里现在是 LOADER，
     所以它找不到 PARM -> 直接落 rockusb，永远不进系统。
  2. 原厂 mtdparts 的坐标是**相对 storage 起点**的：
        uboot@0x2000 -> 物理 8192+8192  = 16384
        trust@0x4000 -> 物理 8192+16384 = 24576
     而 armbian 标准镜像把 LOADER 放在物理 8192、BL3X 放在物理 16384 -> 全错位。

与此同时 U-Boot 与 Linux 内核走**物理坐标**：分区表固定看 LBA0/LBA1。
而本板原厂 PARM 占满 LBA0 并侵入 LBA1 前 386 B，与 MBR/GPT 正面冲突。

解法：一个镜像，两套视图
------------------------
    物理 LBA      内容                        给谁看
    -------------------------------------------------------------------
    0..1          压缩 PARM(446B) + MBR(p1)    U-Boot / 内核（物理视图）
    2..8191       全零
    8192..8193    原厂 PARM 全文(898B)         miniloader（偏移视图的 LBA0）
    8194..16383   全零
    16384..24575  LOADER  (uboot.img, 4MiB)    miniloader 的 uboot@0x2000
    24576..32767  BL3X    (trust.bin, 4MiB)    miniloader 的 trust@0x4000
    32768..       原样不动（ext4 rootfs = p1）  内核

两套视图互不干扰：
  * miniloader 只读物理 8192 的 PARM 与 16384/24576 的引导件，从不碰 LBA0；
  * U-Boot/内核 只读物理 LBA0 的 MBR 与 p1，从不碰 8192 起的这段「空洞」。

用法
----
    python3 mk-dualparm.py <in.img> <out.img> [--parm stock-parm.bin]
"""

import argparse
import os
import struct
import sys

SECTOR = 512
MBR_TABLE_OFF = 446
GUID_LINUX_FS = bytes.fromhex("af3dc60f838472478e793d69d8477de4")

# 偏移视图里各引导件相对 storage 起点（= 物理 8192）的位置，来自原厂 mtdparts
OFF_UBOOT = 0x2000      # -> 物理 16384
OFF_TRUST = 0x4000      # -> 物理 24576
SHIFT = 0x2000          # storage 起点相对物理 LBA0 的偏移（= 8192）


def read_gpt(f):
    f.seek(SECTOR)
    hdr = f.read(SECTOR)
    if hdr[:8] != b"EFI PART":
        return []
    entry_lba = struct.unpack_from("<Q", hdr, 72)[0]
    num = struct.unpack_from("<I", hdr, 80)[0]
    esz = struct.unpack_from("<I", hdr, 84)[0]
    f.seek(entry_lba * SECTOR)
    raw = f.read(num * esz)
    out = []
    for i in range(num):
        e = raw[i * esz:(i + 1) * esz]
        if len(e) < 128 or e[:16] == b"\x00" * 16:
            continue
        first = struct.unpack_from("<Q", e, 32)[0]
        last = struct.unpack_from("<Q", e, 40)[0]
        name = e[56:128].decode("utf-16-le", "replace").rstrip("\x00")
        out.append((i + 1, e[:16], first, last, name))
    return out


def build_mbr(parts):
    mbr = bytearray(SECTOR)
    for idx, (first, last, _n) in enumerate(parts[:4]):
        off = MBR_TABLE_OFF + idx * 16
        e = bytearray(16)
        e[0] = 0x00
        e[1:4] = bytes((0xFE, 0xFF, 0xFF))
        e[4] = 0x83
        e[5:8] = bytes((0xFE, 0xFF, 0xFF))
        struct.pack_into("<I", e, 8, first & 0xFFFFFFFF)
        struct.pack_into("<I", e, 12, (last - first + 1) & 0xFFFFFFFF)
        mbr[off:off + 16] = e
    mbr[510] = 0x55
    mbr[511] = 0xAA
    return bytes(mbr)


def build_compact_param(stock, keep=("uboot", "trust", "misc", "resource")):
    if stock[:4] != b"PARM":
        raise SystemExit("stock parameter 不是 PARM 头")
    size = struct.unpack_from("<I", stock, 4)[0]
    text = stock[8:size].decode("utf-8", "replace")
    lines = text.split("\r\n")

    head = [l for l in lines if l and not l.startswith("CMDLINE:")]
    src_mtd = ""
    for l in lines:
        if l.startswith("CMDLINE:") and "mtdparts=" in l:
            src_mtd = l.split("mtdparts=", 1)[1]
            break
    entries = []
    for item in src_mtd.split(","):
        name = item.split("(", 1)[1].rstrip(")") if "(" in item else ""
        if name in keep:
            entries.append(item)
    if len(entries) < 2:
        raise SystemExit(f"无法从原厂 mtdparts 提取 uboot/trust：{src_mtd[:80]}")

    cmdline = "CMDLINE: androidboot.hardware=rk30board init=/init mtdparts=" + ",".join(entries)

    dropped = []
    while True:
        body = "\r\n".join(head + [cmdline])
        blob = b"PARM" + struct.pack("<I", 8 + len(body)) + body.encode("utf-8")
        if len(blob) <= MBR_TABLE_OFF:
            break
        cands = [l for l in head if l.startswith("#")] or head
        if not cands:
            raise SystemExit(f"压缩后 parameter 仍超长：{len(blob)} > {MBR_TABLE_OFF}")
        v = max(cands, key=len)
        head.remove(v)
        dropped.append(v)
    return blob, entries, dropped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("in_img")
    ap.add_argument("out_img")
    ap.add_argument("--parm", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "armbian", "blobs", "stock-parm.bin"))
    args = ap.parse_args()

    stock = open(args.parm, "rb").read()
    param, kept, dropped = build_compact_param(stock)
    total = os.path.getsize(args.in_img)
    total_lba = total // SECTOR
    print(f"输入 {args.in_img}  {total} B / {total_lba} LBA")
    print(f"压缩 PARM {len(param)} B，mtdparts 保留: {', '.join(kept)}")
    if dropped:
        print(f"  丢弃注释行 {len(dropped)} 条")

    with open(args.in_img, "rb") as f:
        gpt = read_gpt(f)
        if not gpt:
            raise SystemExit("LBA1 无 'EFI PART'，不是 GPT 镜像")
        parts = [(first, last, name) for _i, _g, first, last, name in gpt]
        for i, _g, first, last, name in gpt:
            print(f"  p{i}: {name}  LBA {first}..{last}  ({last - first + 1} 扇区)")

        # 一次性把 8192..32767 的原始引导区读进内存（12 MiB）
        f.seek(SHIFT * SECTOR)
        boot_region = f.read(16384 * SECTOR)
        if len(boot_region) != 16384 * SECTOR:
            raise SystemExit("引导区读取不完整")

        uboot_img = boot_region[0:8192 * SECTOR]
        trust_bin = boot_region[8192 * SECTOR:16384 * SECTOR]
        if uboot_img[:8] != b"LOADER  ":
            raise SystemExit(f"物理 LBA8192 不是 LOADER：{uboot_img[:16]!r}")
        if trust_bin[:4] != b"BL3X":
            raise SystemExit(f"物理 LBA16384 不是 BL3X：{trust_bin[:16]!r}")
        print(f"  LOADER {len(uboot_img)} B, BL3X {len(trust_bin)} B  (校验通过)")

    out = args.out_img
    if os.path.abspath(out) != os.path.abspath(args.in_img) and not os.path.exists(out):
        raise SystemExit(f"先执行 cp -c {args.in_img} {out}")

    with open(out, "r+b") as f:
        # 1) 物理 16384 <- LOADER（偏移视图的 uboot@0x2000）
        f.seek((SHIFT + OFF_UBOOT) * SECTOR)
        f.write(uboot_img)
        # 2) 物理 24576 <- BL3X（偏移视图的 trust@0x4000）
        f.seek((SHIFT + OFF_TRUST) * SECTOR)
        f.write(trust_bin)
        # 3) 物理 8192..32767 里除上面两块以外全部清零
        f.seek(SHIFT * SECTOR)
        f.write(b"\x00" * 2 * SECTOR)                       # 8192..8193 稍后放 PARM
        f.write(b"\x00" * (OFF_UBOOT - 2) * SECTOR)         # 8194..16383
        # 4) 物理 8192 放原厂 PARM 全文（898 B，跨 2 扇区）
        f.seek(SHIFT * SECTOR)
        f.write(stock)
        # 5) 物理 0..1：压缩 PARM + MBR；2..8191 清零
        lba0 = bytearray(SECTOR)
        lba0[0:len(param)] = param
        mbr = build_mbr([(p[0], p[1], p[2]) for p in parts])
        lba0[MBR_TABLE_OFF:SECTOR] = mbr[MBR_TABLE_OFF:SECTOR]
        f.seek(0)
        f.write(bytes(lba0))
        f.write(b"\x00" * SECTOR)                            # LBA1
        f.write(b"\x00" * (SHIFT - 2) * SECTOR)              # LBA2..8191

    print(f"\n=== 已写出 {out} ===")
    print(f"  LBA0        = 压缩 PARM({len(param)}B) + MBR（p1 @ {parts[0][0]}）")
    print(f"  LBA1..8191  = 全零")
    print(f"  LBA8192     = 原厂 PARM 全文({len(stock)}B)   <- miniloader 的 LBA0")
    print(f"  LBA16384    = LOADER (uboot.img)             <- miniloader 的 uboot@0x2000")
    print(f"  LBA24576    = BL3X   (trust.bin)             <- miniloader 的 trust@0x4000")
    print(f"  LBA32768..  = 原样（ext4 rootfs）")
    return 0


if __name__ == "__main__":
    sys.exit(main())

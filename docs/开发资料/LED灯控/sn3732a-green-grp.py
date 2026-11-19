#!/usr/bin/env python3
# 绿灯分组逐颗"闪一次"（单颗亮 -> 灭 -> 下一颗），便于肉眼逐颗计数
# 用法: sn3732a-green-grp.py <组号1-6> [每颗亮秒=0.55] [间隔秒=0.35] [acc=0|1 累加模式]
#   组1 = 编号 1-12, 组2 = 13-24, 组3 = 25-36, 组4 = 37-48, 组5 = 49-60, 组6 = 61-72
import sys, time, ast
sys.path.insert(0, '/root')
import sn3732a as M

src = open('/root/sn3732a-green-seq.py', encoding='utf-8').read()
s = src.index('ORDER = ')
e = src.index(']', s)
ORDER = ast.literal_eval(src[s + len('ORDER = '):e + 1])
assert len(ORDER) == 73, len(ORDER)

grp  = int(sys.argv[1]) if len(sys.argv) > 1 else 1
on   = float(sys.argv[2]) if len(sys.argv) > 2 else 0.55
gap  = float(sys.argv[3]) if len(sys.argv) > 3 else 0.35
acc  = int(sys.argv[4]) if len(sys.argv) > 4 else 0

lo = 1 + (grp - 1) * 12
hi = lo + 11
assert 1 <= lo <= 72 and hi <= 72, (lo, hi)

def flush(active):
    m = {d: [0x00] * 18 for d in M.DEVS}
    for (c, g, b) in active:
        m[c][g] |= 1 << b
    for d in M.DEVS:
        M.write_frame(d, 0, m[d], [0xFF] * 144)

M.all_init(); time.sleep(0.15)
flush(set()); time.sleep(0.15)

mode = "累加" if acc else "单颗闪"
print("== 第 %d 组：编号 %d-%d（12 颗），%s，每颗亮 %.2fs / 灭 %.2fs ==" % (grp, lo, hi, mode, on, gap), flush=True)
keep = set()
for n in range(lo, hi + 1):
    c, g, b = ORDER[n]
    if acc:
        keep.add(ORDER[n]); flush(keep)
    else:
        flush({ORDER[n]})
    print("  No.%-2d  %02X:%d:%d" % (n, c, g, b), flush=True)
    time.sleep(on)
    if not acc:
        flush(set()); time.sleep(gap)

if acc:
    time.sleep(0.4)
    print("== 第 %d 组 12 颗保持常亮 ==" % grp, flush=True)
else:
    flush(set())
    print("== 第 %d 组 12 颗各闪一次完成，现全灭 ==" % grp, flush=True)

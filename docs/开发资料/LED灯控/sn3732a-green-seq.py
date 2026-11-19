#!/usr/bin/env python3
# 73 颗绿灯环形顺序表（编号 0..72）—— 按红灯规律推演版（G17→G15, G01→G03, G00→G02, G16→G14）
# 用法: sn3732a-green-seq.py [每步秒=0.5] [每步颗数=1] [mode=on|off] [order=asc|desc]
import sys, time
sys.path.insert(0, '/root')
import sn3732a as M

ORDER = [
 (83, 15, 5),
 (83, 15, 4),
 (83, 15, 3),
 (83, 15, 2),
 (83, 15, 1),
 (83, 15, 0),
 (83, 3, 7),
 (83, 3, 6),
 (83, 3, 5),
 (83, 3, 4),
 (83, 3, 3),
 (83, 3, 2),
 (83, 3, 1),
 (83, 3, 0),
 (83, 2, 7),
 (83, 2, 6),
 (83, 2, 5),
 (83, 2, 4),
 (83, 2, 3),
 (83, 2, 2),
 (83, 2, 1),
 (83, 2, 0),
 (83, 14, 0),
 (83, 14, 1),
 (83, 14, 2),
 (83, 14, 3),
 (83, 14, 4),
 (83, 14, 5),
 (83, 14, 6),
 (83, 14, 7),
 (80, 14, 7),
 (80, 14, 6),
 (80, 14, 5),
 (80, 14, 4),
 (80, 14, 3),
 (80, 14, 2),
 (80, 14, 1),
 (80, 14, 0),
 (80, 2, 7),
 (80, 2, 6),
 (80, 2, 5),
 (80, 2, 4),
 (80, 2, 3),
 (80, 2, 2),
 (80, 2, 1),
 (80, 2, 0),
 (80, 15, 7),
 (80, 15, 6),
 (80, 15, 5),
 (80, 15, 4),
 (80, 15, 3),
 (80, 15, 2),
 (80, 15, 1),
 (80, 15, 0),
 (80, 3, 7),
 (80, 3, 6),
 (80, 3, 5),
 (80, 3, 4),
 (80, 3, 3),
 (80, 3, 2),
 (80, 3, 1),
 (80, 3, 0),
 (82, 14, 7),
 (82, 14, 6),
 (82, 14, 5),
 (82, 14, 4),
 (82, 14, 3),
 (82, 14, 2),
 (82, 14, 1),
 (82, 14, 0),
 (82, 2, 0),
 (83, 15, 7),
 (83, 15, 6),
]
assert len(ORDER) == 73, len(ORDER)

def flush(active):
    m = {d: [0x00]*18 for d in M.DEVS}
    for (c, g, b) in active:
        m[c][g] |= 1 << b
    for d in M.DEVS:
        M.write_frame(d, 0, m[d], [0xFF]*144)

per   = float(sys.argv[1]) if len(sys.argv) > 1 else 0.5
step  = int(sys.argv[2])   if len(sys.argv) > 2 else 1
mode  = sys.argv[3]        if len(sys.argv) > 3 else "on"
order = sys.argv[4]        if len(sys.argv) > 4 else "asc"

seq = list(range(73)) if order == "asc" else list(range(72, -1, -1))

M.all_init(); time.sleep(0.15)
active = set() if mode == "on" else set(ORDER)
flush(active); time.sleep(0.1)

for i in range(0, len(seq), step):
    batch = seq[i:i+step]
    for n in batch:
        if mode == "on":
            active.add(ORDER[n])
        else:
            active.discard(ORDER[n])
    t0 = time.time(); flush(active)
    print("  %s No.%s" % ("ON " if mode == "on" else "OFF", "-".join(str(n) for n in batch)), flush=True)
    dt = per - (time.time() - t0)
    if dt > 0: time.sleep(dt)

print("== %s 完成，剩余点亮 %d 颗 ==" % (mode, len(active)), flush=True)

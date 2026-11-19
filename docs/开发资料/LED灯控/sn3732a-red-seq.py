#!/usr/bin/env python3
# 73 颗红灯环形顺序表（编号 0..72），支持整环依次点亮 / 依次熄灭
# 用法: sn3732a-red-seq.py [每步秒=0.5] [每步颗数=1] [mode=on|off] [order=asc|desc]
import sys, time
sys.path.insert(0, '/root')
import sn3732a as M

ORDER = [
 (83, 17, 5),
 (83, 17, 4),
 (83, 17, 3),
 (83, 17, 2),
 (83, 17, 1),
 (83, 17, 0),
 (83, 1, 7),
 (83, 1, 6),
 (83, 1, 5),
 (83, 1, 4),
 (83, 1, 3),
 (83, 1, 2),
 (83, 1, 1),
 (83, 1, 0),
 (83, 0, 7),
 (83, 0, 6),
 (83, 0, 5),
 (83, 0, 4),
 (83, 0, 3),
 (83, 0, 2),
 (83, 0, 1),
 (83, 0, 0),
 (83, 16, 0),
 (83, 16, 1),
 (83, 16, 2),
 (83, 16, 3),
 (83, 16, 4),
 (83, 16, 5),
 (83, 16, 6),
 (83, 16, 7),
 (80, 16, 7),
 (80, 16, 6),
 (80, 16, 5),
 (80, 16, 4),
 (80, 16, 3),
 (80, 16, 2),
 (80, 16, 1),
 (80, 16, 0),
 (80, 0, 7),
 (80, 0, 6),
 (80, 0, 5),
 (80, 0, 4),
 (80, 0, 3),
 (80, 0, 2),
 (80, 0, 1),
 (80, 0, 0),
 (80, 17, 7),
 (80, 17, 6),
 (80, 17, 5),
 (80, 17, 4),
 (80, 17, 3),
 (80, 17, 2),
 (80, 17, 1),
 (80, 17, 0),
 (80, 1, 7),
 (80, 1, 6),
 (80, 1, 5),
 (80, 1, 4),
 (80, 1, 3),
 (80, 1, 2),
 (80, 1, 1),
 (80, 1, 0),
 (82, 16, 7),
 (82, 16, 6),
 (82, 16, 5),
 (82, 16, 4),
 (82, 16, 3),
 (82, 16, 2),
 (82, 16, 1),
 (82, 16, 0),
 (82, 0, 0),
 (83, 17, 7),
 (83, 17, 6),
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

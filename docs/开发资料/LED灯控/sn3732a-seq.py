#!/usr/bin/env python3
# 73 颗蓝灯环形顺序表（编号 0..72），支持整环依次点亮 / 依次熄灭
# 用法: sn3732a-seq.py [每步秒=0.5] [每步颗数=1] [mode=on|off] [order=asc|desc]
import sys, time
sys.path.insert(0, '/root')
import sn3732a as M

ORDER = [
 (0x53,13,5),(0x53,13,4),(0x53,13,3),(0x53,13,2),(0x53,13,1),(0x53,13,0),
 (0x53,5,7),(0x53,5,6),(0x53,5,5),(0x53,5,4),(0x53,5,3),(0x53,5,2),
 (0x53,7,2),(0x53,7,1),
 (0x53,4,7),(0x53,4,6),(0x53,4,5),(0x53,4,4),(0x53,4,3),(0x53,4,2),
 (0x53,6,2),(0x53,6,1),
 (0x53,12,0),(0x53,12,1),(0x53,12,2),(0x53,12,3),(0x53,12,4),(0x53,12,5),
 (0x53,10,5),(0x53,10,6),
 (0x50,10,6),(0x50,10,5),
 (0x50,12,5),(0x50,12,4),(0x50,12,3),(0x50,12,2),(0x50,12,1),(0x50,12,0),
 (0x50,4,7),(0x50,4,6),(0x50,4,5),(0x50,4,4),(0x50,4,3),(0x50,4,2),
 (0x50,6,2),(0x50,6,1),
 (0x50,11,6),(0x50,11,5),
 (0x50,13,5),(0x50,13,4),(0x50,13,3),(0x50,13,2),(0x50,13,1),(0x50,13,0),
 (0x50,5,7),(0x50,5,6),(0x50,5,5),(0x50,5,4),(0x50,5,3),(0x50,5,2),
 (0x50,7,2),(0x50,7,1),
 (0x52,10,6),(0x52,10,5),
 (0x52,12,5),(0x52,12,4),(0x52,12,3),(0x52,12,2),(0x52,12,1),(0x52,12,0),
 (0x52,6,1),
 (0x53,11,6),(0x53,11,5),
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

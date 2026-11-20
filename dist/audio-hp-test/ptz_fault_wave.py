#!/usr/bin/env python3
"""HR8833 nFAULT 波形采样：区分 OCP(1.35ms 周期重启) / UVLO(持续拉低+VM 塌陷) / 未触发
依据 HR8833 datasheet V2.1：
  - IOCP = 2.5A，tOCP = 1.35ms（过流保护周期：关断 tOCP 后重新使能，nFAULT 回高，故障仍在则循环）
  - nFAULT 为开漏，OCP / TSD / UVLO 三种情况均拉低
  - xISEN 与 OCP 无关（过流保护不使用 PWM 电流检测电路）
用法: python3 ptz_fault_wave.py <dir: fwd|rev> <ms>
"""
import os, sys, time, fcntl, struct

IOEN_STOP = 0x40046d18   # Ioenable / stop
FWD       = 0x40046d19   # Ioforward
REV       = 0x40046d1a   # Ioreverse

OCP_PATH  = "/sys/devices/platform/motor/ocp"
ADC_PATH  = "/sys/bus/iio/devices/iio:device0/in_voltage1_raw"

def ioctl(fd, cmd):
    fcntl.ioctl(fd, cmd, struct.pack("i", 0))

def pread1(fd, path):
    return os.pread(fd, 16, 0)

def main():
    if len(sys.argv) < 3:
        print("usage: ptz_fault_wave.py <fwd|rev> <ms>")
        return 2
    direction = sys.argv[1].lower()
    dur_ms = float(sys.argv[2])
    cmd = FWD if direction == "fwd" else REV

    motor = open("/dev/hr8833", "rb+", buffering=0)
    ocp_fd = os.open(OCP_PATH, os.O_RDONLY)
    try:
        adc_fd = os.open(ADC_PATH, os.O_RDONLY)
    except OSError:
        adc_fd = None

    # 静止基线 100ms
    base_ts = []
    t0 = time.perf_counter()
    while (time.perf_counter() - t0) * 1000 < 100:
        v = pread1(ocp_fd, OCP_PATH)
        base_ts.append((time.perf_counter(), v[:1]))

    # 脉冲期采样
    ioctl(motor, cmd)
    ts = []
    adc = []
    t_start = time.perf_counter()
    n = 0
    while (time.perf_counter() - t_start) * 1000 < dur_ms:
        v = pread1(ocp_fd, OCP_PATH)
        t = time.perf_counter()
        ts.append((t, v[:1]))
        n += 1
        if adc_fd is not None and n % 20 == 0:
            try:
                adc.append((time.perf_counter(), int(os.pread(adc_fd, 16, 0) or b"0")))
            except Exception:
                pass
    t_stop = time.perf_counter()
    ioctl(motor, IOEN_STOP)

    # 停后观察 30ms
    post = []
    t1 = time.perf_counter()
    while (time.perf_counter() - t1) * 1000 < 30:
        v = pread1(ocp_fd, OCP_PATH)
        post.append((time.perf_counter(), v[:1]))

    # ---- 统计 ----
    def stat(seq, label):
        if not seq:
            return
        vals = [x[1] for x in seq]
        low = sum(1 for v in vals if v == b"0")
        print("  %-8s n=%d  low=%d (%.1f%%)  high=%d" % (label, len(vals), low, 100.0 * low / len(vals), len(vals) - low))
        # 跳变与状态时长
        trans = []
        prev = vals[0]
        tprev = seq[0][0]
        for t, v in seq[1:]:
            if v != prev:
                trans.append((tprev, t, prev))
                prev = v
                tprev = t
        trans.append((tprev, seq[-1][0], prev))
        edges = len(trans) - 1
        print("  %-8s transitions=%d" % (label, edges))
        if 1 <= len(trans) <= 40:
            segs = ["%s:%.2fms" % ("LOW" if s[2] == b"0" else "HIGH", (s[1] - s[0]) * 1000) for s in trans]
            print("  %-8s segs: %s" % (label, " ".join(segs)))
        elif len(trans) > 40:
            lows = [(s[1] - s[0]) * 1000 for s in trans if s[2] == b"0"][1:-1]
            highs = [(s[1] - s[0]) * 1000 for s in trans if s[2] == b"1"][1:-1]
            if lows:
                print("  %-8s LOW  ms min/avg/max = %.2f/%.2f/%.2f" % (label, min(lows), sum(lows) / len(lows), max(lows)))
            if highs:
                print("  %-8s HIGH ms min/avg/max = %.3f/%.3f/%.3f" % (label, min(highs), sum(highs) / len(highs), max(highs)))

    print("== %s %sms ==" % (direction.upper(), dur_ms))
    print("  pulse wall = %.2f ms, sample rate = %.0f/s (%.0f us/call)" % (
        (t_stop - t_start) * 1000, len(ts) / (t_stop - t_start), (t_stop - t_start) / max(1, len(ts)) * 1e6))
    stat(base_ts, "baseline")
    stat(ts, "during")
    stat(post, "after")
    if adc:
        vals = [a[1] for a in adc]
        print("  saradc ch1 raw: n=%d min=%d max=%d first=%d last=%d" % (len(vals), min(vals), max(vals), vals[0], vals[-1]))
        step = max(1, len(adc) // 12)
        print("  saradc ch1 trace: %s" % " ".join(str(a[1]) for a in adc[::step]))
    return 0

if __name__ == "__main__":
    sys.exit(main())

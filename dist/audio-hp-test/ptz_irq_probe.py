#!/usr/bin/env python3
"""
ptz_irq_probe.py —— AT8833 云台 nFAULT 精确边沿统计（用户态，无驱动）

为什么不用 gpioset + gpiomon：
  每次 gpioset 都会重新 request line，request 的默认输出电平会造出
  nSLEEP/AIN 的额外跳变，导致实验之间互相污染（实测 REV/brake 结果
  自相矛盾）。本脚本用 libgpiod 的 C API（ctypes），**一次 request
  全部四个 line 并全程持有**，只在受控时刻改电平，事件由 libgpiod
  的事件队列直接记录（不受轮询采样率限制）。

判读：
  hiccup OCP（手册 tOCP=1.9ms 自动重试）
      fall ≈ 157（300ms/1.9ms）、gap_avg ≈ 1900 µs、rise 也接近 fall
  锁存故障（拉低后不释放）
      fall = 1、rise = 0
  完全正常
      fall = 0、rise = 0
"""
import ctypes, ctypes.util, sys, time, os

CHIP = "gpiochip2"
L_AIN1, L_AIN2, L_SLEEP, L_FAULT = 2, 3, 4, 5

RISING, FALLING = 1, 2
FLAG_BIAS_PULL_UP = 1 << 4


class Timespec(ctypes.Structure):
    _fields_ = [("tv_sec", ctypes.c_long), ("tv_nsec", ctypes.c_long)]


class LineEvent(ctypes.Structure):
    _fields_ = [("ts", Timespec), ("event_type", ctypes.c_int)]


def load():
    for name in ("libgpiod.so.2", "libgpiod.so"):
        try:
            return ctypes.CDLL(name)
        except OSError:
            continue
    raise RuntimeError("libgpiod not found")


lib = load()
lib.gpiod_chip_open_by_name.restype = ctypes.c_void_p
lib.gpiod_chip_open_by_name.argtypes = [ctypes.c_char_p]
lib.gpiod_chip_get_line.restype = ctypes.c_void_p
lib.gpiod_chip_get_line.argtypes = [ctypes.c_void_p, ctypes.c_uint]
lib.gpiod_line_request_output.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                          ctypes.c_int]
lib.gpiod_line_request_both_edges_events_flags.restype = ctypes.c_int
lib.gpiod_line_request_both_edges_events_flags.argtypes = [
    ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
lib.gpiod_line_set_value.argtypes = [ctypes.c_void_p, ctypes.c_int]
lib.gpiod_line_get_value.argtypes = [ctypes.c_void_p]
lib.gpiod_line_event_wait.argtypes = [ctypes.c_void_p,
                                      ctypes.POINTER(Timespec)]
lib.gpiod_line_event_read.argtypes = [ctypes.c_void_p,
                                      ctypes.POINTER(LineEvent)]


def main():
    chip = lib.gpiod_chip_open_by_name(CHIP.encode())
    if not chip:
        print("open chip failed")
        return 1

    lines = {}
    for off in (L_AIN1, L_AIN2, L_SLEEP):
        ln = lib.gpiod_chip_get_line(chip, off)
        if not ln:
            print("get line %d failed" % off)
            return 1
        # request 输出，默认 0（nSLEEP 物理低 = 休眠，安全）
        if lib.gpiod_line_request_output(ln, b"ptz-probe", 0) < 0:
            print("request output line %d failed" % off)
            return 1
        lines[off] = ln

    flt = lib.gpiod_chip_get_line(chip, L_FAULT)
    if not flt:
        print("get fault line failed")
        return 1
    if lib.gpiod_line_request_both_edges_events_flags(
            flt, b"ptz-probe", FLAG_BIAS_PULL_UP) < 0:
        print("request events on nFAULT failed")
        return 1

    def setv(off, v):
        lib.gpiod_line_set_value(lines[off], v)

    def drain(ms=5):
        """丢弃残余事件"""
        end = time.monotonic() + ms / 1000.0
        n = 0
        ev = LineEvent()
        while time.monotonic() < end:
            ts = Timespec(0, 2_000_000)
            if lib.gpiod_line_event_wait(flt, ctypes.byref(ts)) != 1:
                continue
            lib.gpiod_line_event_read(flt, ctypes.byref(ev))
            n += 1
        return n

    def run(name, ain1, ain2, hold_ms, wake_first=True, do_reset=False):
        """返回 (fall, rise, gaps_us, first_level)"""
        if do_reset:
            setv(L_SLEEP, 0)      # 睡眠
            time.sleep(0.05)
        if wake_first:
            setv(L_SLEEP, 1)      # nSLEEP 物理高 = 工作
            time.sleep(0.003)     # > tWAKE(1ms)
        drain(3)                  # 清掉唤醒瞬态

        t0 = time.monotonic()
        setv(L_AIN1, ain1)
        setv(L_AIN2, ain2)

        falls, rises, fall_ts = [], [], []
        ev = LineEvent()
        end = t0 + hold_ms / 1000.0
        while True:
            remain = end - time.monotonic()
            if remain <= 0:
                break
            ts = Timespec(int(remain), int((remain % 1) * 1e9))
            r = lib.gpiod_line_event_wait(flt, ctypes.byref(ts))
            if r == 1:
                lib.gpiod_line_event_read(flt, ctypes.byref(ev))
                t = ev.ts.tv_sec + ev.ts.tv_nsec / 1e9
                if ev.event_type == FALLING:
                    falls.append(t)
                else:
                    rises.append(t)
            elif r < 0:
                break

        level = lib.gpiod_line_get_value(flt)
        # 收尾：先停方向，再休眠
        setv(L_AIN1, 0)
        setv(L_AIN2, 0)
        time.sleep(0.002)
        setv(L_SLEEP, 0)

        gaps = [(falls[i + 1] - falls[i]) * 1e6 for i in range(len(falls) - 1)]
        gavg = sum(gaps) / len(gaps) if gaps else 0
        gmin = min(gaps) if gaps else 0
        gmax = max(gaps) if gaps else 0
        print("  %-14s fall=%-4d rise=%-4d end_level=%d  gap_avg=%.0fus "
              "min=%.0f max=%.0f" %
              (name, len(falls), len(rises), level, gavg, gmin, gmax))
        return len(falls), len(rises), gaps

    print("=== AT8833 nFAULT 边沿统计（一次 request，全程持有）===")
    print("line: AIN1=%d AIN2=%d nSLEEP=%d nFAULT=%d (%s)" %
          (L_AIN1, L_AIN2, L_SLEEP, L_FAULT, CHIP))

    # 先确保休眠态基线
    setv(L_AIN1, 0); setv(L_AIN2, 0); setv(L_SLEEP, 0)
    time.sleep(0.05)
    print("  idle(sleep)    nFAULT level=%d" % lib.gpiod_line_get_value(flt))

    run("coast(ZZ)",      0, 0, 300)
    run("brake(LL)",      1, 1, 300)
    run("fwd(HL) 300ms",  1, 0, 300)
    run("rev(LH) 300ms",  0, 1, 300)
    run("fwd 1000ms",     1, 0, 1000)
    # 复位后立刻 fwd，验证是否为锁存故障
    print("  --- 复位(nSLEEP 切)后再 fwd，验证锁存性 ---")
    run("fwd after reset", 1, 0, 300, do_reset=True)

    # 收尾
    setv(L_AIN1, 0); setv(L_AIN2, 0); setv(L_SLEEP, 0)
    return 0


if __name__ == "__main__":
    sys.exit(main())

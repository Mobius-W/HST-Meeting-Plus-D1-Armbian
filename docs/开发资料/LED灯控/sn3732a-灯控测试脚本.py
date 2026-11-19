#!/usr/bin/env python3
"""
SN3732A (= IS31FL3732A register-compatible) LED driver over i2c6.
Bare-metal register control, bypassing the missing mainline vendor driver.

Usage:
  sn3732a.py scan                 # scan each LED-control byte group, print mapping
  sn3732a.py solid <color>        # color = red|green|blue|yellow|white|off
  sn3732a.py chase <sec>          # running-light across all 18 LED-control bytes
  sn3732a.py breathe <sec>        # breathing via Config/Auto-play + Breath registers
  sn3732a.py demo                 # full 3-round test: solid/chase/breathe
  sn3732a.py init                 # init all 3 chips to Picture mode, normal op
"""
import subprocess, sys, time, threading

BUS = 6
DEVS = [0x50, 0x52, 0x53]

# ---- Page codes (write to FDh Command Register) ----
PAGE_FRAME_BASE = 0x00   # 0..7 = Frame1..Frame8
PAGE_FUNC       = 0x0B   # Function register page

# ---- Function register addresses ----
F_CONFIG   = 0x00   # D7:D6 SYNC, D5 -, D4:D3 MODE, D2:D0 FS
F_PICTURE  = 0x01   # D2:D0 PFS
F_AUTO1    = 0x02   # D6:D4 CNS, D2:D0 FNS
F_AUTO2    = 0x03   # D5:D0 A (frame delay)
F_GCC      = 0x04   # global current 0..255
F_DISPLAY  = 0x05   # D5 IC, D3 BE, D2:D0 BPT
F_BREATH1  = 0x08   # D6:D4 FOT, D2:D0 FIT
F_BREATH2  = 0x09   # D4 B_EN, D2:D0 ET
F_SHUTDOWN = 0x0A   # SSD: 00=SW-shutdown1, 01=normal, 1x=SW-shutdown2

# mode bits for CONFIG
MODE_PICTURE = 0x00 << 3
MODE_AUTO    = 0x01 << 3
MODE_AUDIO   = 0x02 << 3


def tx(args):
    """raw i2ctransfer, args are hex tokens after address"""
    cmd = ["i2ctransfer", "-y", "-f", str(BUS)] + args
    r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return r.returncode


def setpage(dev, page):
    return tx(["w2@0x%02x" % dev, "0xfd", "0x%02x" % page])


def wreg(dev, reg, val):
    return tx(["w2@0x%02x" % dev, "0x%02x" % reg, "0x%02x" % val])


def rreg(dev, reg):
    r = subprocess.run(["i2ctransfer", "-y", "-f", str(BUS), "w1@0x%02x" % dev,
                        "0x%02x" % reg, "r1"], capture_output=True, text=True)
    try:
        return int(r.stdout.split()[-1], 16)
    except Exception:
        return None


def wburst(dev, start, vals):
    """write consecutive registers starting at start"""
    toks = ["w%d@0x%02x" % (len(vals) + 1, dev), "0x%02x" % start]
    toks += ["0x%02x" % v for v in vals]
    return tx(toks)


def func_set(dev, **regs):
    setpage(dev, PAGE_FUNC)
    for k, v in regs.items():
        addr = globals().get("F_" + k.upper())
        if addr is None:
            continue
        wreg(dev, addr, v)


def write_frame(dev, frame, led_on, pwm=None):
    """write one frame's LED-control + PWM. led_on: 18 bytes bitmask. pwm: 144 bytes."""
    setpage(dev, PAGE_FRAME_BASE + frame)
    wburst(dev, 0x00, led_on)              # LED control 00h..11h
    wburst(dev, 0x12, [0x00] * 18)         # blink control off
    wburst(dev, 0x24, pwm if pwm else [0xFF] * 144)


def init_chip(dev):
    func_set(dev, SHUTDOWN=0x01,      # normal operation
             CONFIG=MODE_PICTURE,     # picture mode
             PICTURE=0x00,            # display frame 1
             GCC=0xFF,                # max current
             DISPLAY=0x00)            # no blink, independent intensity


def all_off():
    for d in DEVS:
        func_set(d, SHUTDOWN=0x00)    # SW shutdown 1 blanks matrix
    time.sleep(0.1)


def all_init():
    for d in DEVS:
        init_chip(d)


# ---- color groups: IS31FL3732A RGB matrix - we discover mapping via scan ----
# Each chip drives a 9(C)x16(R) matrix. LEDs on the board use a subset.
# We treat the 18 LED-control bytes as 18 groups; color depends on wiring.
def solid_group(byte_idx, val=0xFF, pwm=0xFF):
    """light only one LED-control byte group on all chips"""
    for d in DEVS:
        on = [0x00] * 18
        on[byte_idx] = val
        write_frame(d, 0, on, [pwm] * 144)
        func_set(d, CONFIG=MODE_PICTURE, PICTURE=0x00, SHUTDOWN=0x01, GCC=0xFF)


def solid_all(color="white"):
    """all 144 channels on; color depends on physical wiring (observed: pink)"""
    for d in DEVS:
        write_frame(d, 0, [0xFF] * 18, [0xFF] * 144)
        func_set(d, CONFIG=MODE_PICTURE, PICTURE=0x00, SHUTDOWN=0x01, GCC=0xFF)


def scan():
    all_init()
    print("scan: lighting one LED-control byte group at a time (0..17), 0.8s each")
    for i in range(18):
        solid_group(i)
        sys.stdout.write("byte %02d (0x%02x) ON  <- tell me the color/position\n" % (i, i))
        sys.stdout.flush()
        time.sleep(0.8)
    all_off()
    print("scan done")


def chase(duration=6.0, step_delay=0.03):
    """running light: walk a single LED (bit) across all 144 channels, fine-grained.
    init frame once, then only rewrite the 18-byte LED-control map each step."""
    all_init()
    for d in DEVS:
        setpage(d, PAGE_FRAME_BASE)
        wburst(d, 0x12, [0x00] * 18)      # blink off
        wburst(d, 0x24, [0xFF] * 144)     # PWM full
    t0 = time.time()
    idx = 0
    while time.time() - t0 < duration:
        byte_i, bit_j = divmod(idx, 8)
        on = [0x00] * 18
        on[byte_i] = 1 << bit_j
        for d in DEVS:
            setpage(d, PAGE_FRAME_BASE)
            wburst(d, 0x00, on)           # only rewrite LED-control map
        idx = (idx + 1) % 144
        time.sleep(step_delay)


def breathe(duration=6.0):
    """breathing: ramp GCC from 0..255..0 while all LEDs on"""
    all_init()
    for d in DEVS:
        write_frame(d, 0, [0xFF] * 18, [0xFF] * 144)
    t0 = time.time()
    while time.time() - t0 < duration:
        phase = (time.time() - t0) % 2.0
        gcc = int(255 * (1 - abs(phase - 1.0))) if phase < 2.0 else 0
        for d in DEVS:
            func_set(d, GCC=gcc, SHUTDOWN=0x01, CONFIG=MODE_PICTURE, PICTURE=0x00)
        time.sleep(0.05)
    for d in DEVS:
        func_set(d, GCC=0xFF)


def demo():
    """3 rounds of solid / chase / breathe"""
    print("=== SN3732A LED demo: 3 rounds ===")
    for rnd in range(1, 4):
        print("--- Round %d/3: SOLID (pink/all-on) 2s ---" % rnd, flush=True)
        solid_all("white")
        time.sleep(2.0)
        print("--- Round %d/3: CHASE (running light) 4s ---" % rnd, flush=True)
        chase(4.0)
        print("--- Round %d/3: BREATHE 4s ---" % rnd, flush=True)
        breathe(4.0)
    all_off()
    print("=== demo done, LEDs off ===")


def workqueue_effect(rounds=3, hold=0.45, hold_init=1.0):
    """Replicate the vendor kernel driver's async LED strategy:
       - probe: turn on all LEDs (boot pink) -> hold_init
       - workqueue (sn3732a-leds-wq): cycle whole-chip single colors 红/绿/蓝/黄/全开
       - shutdown: all off
       Runs the light sequence in a BACKGROUND THREAD while the main thread
       keeps printing a heartbeat, to demonstrate it is truly asynchronous.
       NOTE: per-color channel mapping is unknown, so each 'color' step lights
       a distinct LED-control byte group; user reports the real color seen.
    """
    # 5 patterns: probe-all-on + 4 groups (stand-in for 红/绿/蓝/黄)
    patterns = [
        ("ALL/probe", [0xFF] * 18),
        ("GRP-A",     [0xFF if i in range(0, 6) else 0x00 for i in range(18)]),
        ("GRP-B",     [0xFF if i in range(6, 12) else 0x00 for i in range(18)]),
        ("GRP-C",     [0xFF if i in range(12, 18) else 0x00 for i in range(18)]),
        ("GRP-ALT",   [0xFF if i % 2 == 0 else 0x00 for i in range(18)]),
    ]
    stop = threading.Event()

    def apply(on_bytes):
        for d in DEVS:
            write_frame(d, 0, on_bytes, [0xFF] * 144)
            func_set(d, CONFIG=MODE_PICTURE, PICTURE=0x00, SHUTDOWN=0x01, GCC=0xFF)

    def wq_worker():
        # probe stage: all on
        apply([0xFF] * 18)
        print("[WQ][probe] all LEDs ON (boot state), hold %.1fs" % hold_init, flush=True)
        time.sleep(hold_init)
        for rnd in range(1, rounds + 1):
            for name, on in patterns:
                if stop.is_set():
                    break
                apply(on)
                print("[WQ] round %d/%d  %-10s  <- tell me the color" % (rnd, rounds, name), flush=True)
                time.sleep(hold)
        # shutdown stage
        all_off()
        print("[WQ][shutdown] all LEDs OFF", flush=True)
        stop.set()

    all_init()
    t = threading.Thread(target=wq_worker, daemon=True)
    t.start()
    # main thread keeps running => proves the LED workqueue is asynchronous
    hb = 0
    while not stop.is_set():
        print("[main] heartbeat %03d (LED loop runs in bg thread)" % hb, flush=True)
        hb += 1
        time.sleep(0.5)
    t.join()
    print("=== workqueue_effect done (%d rounds) ===" % rounds, flush=True)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "scan":
        scan()
    elif cmd == "init":
        all_init()
        print("init done")
    elif cmd == "solid":
        all_init(); solid_all(sys.argv[2] if len(sys.argv) > 2 else "white")
    elif cmd == "chase":
        chase(float(sys.argv[2]) if len(sys.argv) > 2 else 6.0)
        all_off()
    elif cmd == "breathe":
        breathe(float(sys.argv[2]) if len(sys.argv) > 2 else 6.0)
    elif cmd == "demo":
        demo()
    elif cmd == "workqueue":
        workqueue_effect(rounds=int(sys.argv[2]) if len(sys.argv) > 2 else 3)
    elif cmd == "calib":
        # light each of the 18 LED-control byte groups one at a time
        all_init()
        for d in DEVS:
            setpage(d, PAGE_FRAME_BASE)
            wburst(d, 0x24, [0xFF] * 144)   # PWM full
        for i in range(18):
            on = [0x00] * 18
            on[i] = 0xFF
            for d in DEVS:
                setpage(d, PAGE_FRAME_BASE)
                wburst(d, 0x00, on)
            print("GROUP %02d ON (bit %d..%d)" % (i, i * 8, i * 8 + 7), flush=True)
            time.sleep(1.0)
            for d in DEVS:
                setpage(d, PAGE_FRAME_BASE)
                wburst(d, 0x00, [0x00] * 18)
            time.sleep(0.25)
        print("calib done")
    elif cmd == "off":
        all_off()
        print("off")
    else:
        print("unknown cmd:", cmd)

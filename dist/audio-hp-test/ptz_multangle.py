import fcntl, struct, time, subprocess, os, sys

fd = open('/dev/hr8833', 'rb+', buffering=0)
OCP = '/sys/devices/platform/motor/ocp'
FWD = 0x40046d19; REV = 0x40046d1a; STOP = 0x40046d18
def ocp(): return open(OCP).read().strip()
def io(c): return fcntl.ioctl(fd, c, struct.pack('i', 0))

# 时间轴（秒）：(时刻, 方向, 脉冲ms, 标签)
events = [
    (3.0, FWD, 240, 'FWD240ms_6deg'),
    (6.0, FWD, 480, 'FWD480ms_12deg'),
    (9.0, FWD, 800, 'FWD800ms_20deg'),
    (12.0, REV, 800, 'REV800ms_20deg'),
]
TOTAL = 16
YUV = '/tmp/ptz_multi.yuv'
log = open('/tmp/ptz_multi.log', 'w', buffering=1)
def L(s): log.write(s + '\n'); print(s, flush=True)

try:
    os.remove(YUV)
except OSError:
    pass
io(STOP); time.sleep(0.2)
L(f'ocp_before={ocp()}')

# 后台启动持续录制：16s @30fps ≈ 480 帧
cap = subprocess.Popen(
    ['v4l2-ctl', '-d', '/dev/video5', '--stream-mmap',
     '--stream-count=' + str(TOTAL * 30), '--stream-to=' + YUV],
    stdout=open('/tmp/ptz_multi_cap.log', 'w'), stderr=subprocess.STDOUT)
t0 = time.time()
L(f'capture started t0={t0:.2f}')

idx = 0
next_t = TOTAL + 100  # 默认不再打脉冲
for t_evt, direction, dur_ms, label in events:
    # 等到该时刻
    while time.time() - t0 < t_evt:
        time.sleep(0.02)
    t_actual = time.time() - t0
    io(direction)
    time.sleep(dur_ms / 1000.0)
    io(STOP)
    o = ocp()
    L(f'event{idx+1} {label} @t={t_actual:.2f}s dur={dur_ms}ms ocp_after={o}')
    idx += 1

# 等录制完成
cap.wait()
L(f'capture done wall={time.time()-t0:.2f}s size={os.path.getsize(YUV) if os.path.exists(YUV) else 0}')
io(STOP)
L(f'ocp_final={ocp()}')
fd.close(); log.close()

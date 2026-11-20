import fcntl, struct, time, sys
fd = open('/dev/hr8833', 'rb+', buffering=0)
OCP='/sys/devices/platform/motor/ocp'
FWD=0x40046d19; REV=0x40046d1a; STOP=0x40046d18
def ocp(): return open(OCP).read().strip()
def io(c): return fcntl.ioctl(fd, c, struct.pack('i',0))
mode = sys.argv[1] if len(sys.argv)>1 else 'pulse'
print(f'mode={mode} ocp_before={ocp()}')
io(STOP); time.sleep(0.1)
if mode=='cont':
    io(FWD); time.sleep(3.0)
    print(f'  持续FWD 3s: ocp={ocp()}')
    io(STOP); time.sleep(0.3)
    print(f'  stop后: ocp={ocp()}')
elif mode=='pulse':
    for i in range(5):
        io(FWD); time.sleep(0.24); io(STOP); time.sleep(0.36)
        print(f'  脉冲{i+1} (FWD240ms+stop): ocp={ocp()}')
    time.sleep(0.5)
    print(f'  全部停止后: ocp={ocp()}')
elif mode=='pulse_rev':
    for i in range(5):
        io(REV); time.sleep(0.24); io(STOP); time.sleep(0.36)
        print(f'  脉冲REV{i+1}: ocp={ocp()}')
    io(STOP)
fd.close()

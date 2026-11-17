import fcntl, struct, os
fd=os.open('/dev/input/event2', os.O_RDONLY|os.O_NONBLOCK)
def cmd(nr): return (2<<30)|(24<<16)|(ord('E')<<8)|nr
names={0x00:'ABS_X',0x01:'ABS_Y',0x2f:'ABS_MT_SLOT',0x35:'ABS_MT_POSITION_X',0x36:'ABS_MT_POSITION_Y',0x39:'ABS_MT_TRACKING_ID',0x3a:'ABS_MT_PRESSURE',0x30:'ABS_MT_TOUCH_MAJOR',0x31:'ABS_MT_TOUCH_MINOR',0x37:'ABS_MT_TOOL_TYPE'}
for a,n in names.items():
    try:
        buf=fcntl.ioctl(fd, cmd(0x40+a), bytes(24))
        v,mn,mx,fz,fl,res=struct.unpack('6i',buf)
        print(f"{n:22s} min={mn:5d} max={mx:5d} res={res}")
    except Exception as e: print(n,'ERR',e)
os.close(fd)

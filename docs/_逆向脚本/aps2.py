import struct

D = open('/tmp/hw-hunt/audio.primary.rk30board.so', 'rb').read()
BASE_RO = 0x5000   # .rodata / earlier sections: VMA = file + 0x5000
BASE_DR = 0x6000   # .data.rel.ro and later: VMA = file + 0x6000

SYM_OFF, SYM_SZ = 0x1a0, 0x2180
STR_OFF = 0x2320
REL_OFF, REL_SZ = 0x6944, 0x1808


def sleb(buf, p):
    result = 0
    shift = 0
    while p < len(buf):
        b = buf[p]
        p += 1
        result |= (b & 0x7f) << shift
        shift += 7
        if not (b & 0x80):
            if b & 0x40:
                result -= 1 << shift
            return result, p
    raise ValueError('EOF')


def cstr(vma):
    if 0x157f0 <= vma < 0x157f0 + 0x2de1 or 0x7320 <= vma < 0x7320 + 0x3404:
        o = vma - BASE_RO
        e = D.find(b'\x00', o)
        if e > o and e - o < 120:
            s = D[o:e]
            if all(32 <= c < 127 for c in s):
                return s.decode()
    return None


def sym(si):
    o = SYM_OFF + si * 16
    name, val, sz, info, other, shndx = struct.unpack_from('<IIIBBH', D, o)
    e = D.find(b'\x00', STR_OFF + name)
    nm = D[STR_OFF + name:e].decode('utf8', 'replace')
    return val, nm


def decode_aps2():
    sect = D[REL_OFF:REL_OFF + REL_SZ]
    assert sect[:4] == b'APS2'
    p = 4
    n, p = sleb(sect, p)
    r_offset, p = sleb(sect, p)
    out = []
    GROUPED_BY_INFO = 1
    GROUPED_BY_OFFSET_DELTA = 2
    GROUPED_BY_ADDEND = 4
    HAS_ADDEND = 8
    while len(out) < n:
        gs, p = sleb(sect, p)
        flags, p = sleb(sect, p)
        shared_off = shared_info = shared_add = None
        if flags & GROUPED_BY_OFFSET_DELTA:
            shared_off, p = sleb(sect, p)
        if flags & GROUPED_BY_INFO:
            shared_info, p = sleb(sect, p)
        if (flags & HAS_ADDEND) and (flags & GROUPED_BY_ADDEND):
            shared_add, p = sleb(sect, p)
        addend = 0
        for _ in range(gs):
            od = shared_off
            inf = shared_info
            ad = shared_add
            if od is None:
                od, p = sleb(sect, p)
            if inf is None:
                inf, p = sleb(sect, p)
            if (flags & HAS_ADDEND) and not (flags & GROUPED_BY_ADDEND):
                add, p = sleb(sect, p)
                addend = add
            elif shared_add is not None:
                addend = shared_add
            r_offset += od
            out.append((r_offset, inf & 0xffffffff, addend, flags))
    return out


RELOCS = decode_aps2()

if __name__ == '__main__':
    from collections import Counter
    print('total relocs decoded:', len(RELOCS))
    print('types:', Counter(i & 0xff for _, i, _, _ in RELOCS))
    for ro, info, add, fl in RELOCS[:12]:
        print('r_offset=0x%x info=0x%x sym=%d type=%d addend=%d flags=%d' %
              (ro, info, info >> 8, info & 0xff, add, fl))

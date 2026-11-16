# Device-only fast path for sound.accumulate_ref. Keep the two in sync.
import micropython


@micropython.viper
def accumulate(buf: ptr32, n: int, st: ptr32):
    dc = int(st[0])
    hh = 0
    hl = 0
    ll = 0
    peak = 0
    i = 0
    while i < n:
        x = int(buf[i]) >> 14
        dc += x - (dc >> 8)
        y = x - (dc >> 8)
        h = y >> 9
        l = y & 0x1FF
        hh += h * h
        hl += h * l
        ll += l * l
        if y < 0:
            y = 0 - y
        if y > peak:
            peak = y
        i += 1
    st[0] = dc
    st[1] = hh
    st[2] = hl
    st[3] = ll
    st[4] = peak

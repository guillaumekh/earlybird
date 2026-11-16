# BH1750 ambient light sensor, continuous high-resolution mode 2.

_POWER_ON = 0x01
_CONT_HIRES2 = 0x11
_DEFAULT_MTREG = 69


def raw_to_lux(raw, mtreg):
    return raw / 1.2 * _DEFAULT_MTREG / mtreg / 2


class BH1750:
    def __init__(self, i2c, addr=0x23, mtreg=_DEFAULT_MTREG):
        self.i2c = i2c
        self.addr = addr
        self.mtreg = min(254, max(31, mtreg))
        i2c.writeto(addr, bytes((_POWER_ON,)))
        i2c.writeto(addr, bytes((0x40 | (self.mtreg >> 5),)))
        i2c.writeto(addr, bytes((0x60 | (self.mtreg & 0x1F),)))
        i2c.writeto(addr, bytes((_CONT_HIRES2,)))

    def lux(self):
        d = self.i2c.readfrom(self.addr, 2)
        return raw_to_lux((d[0] << 8) | d[1], self.mtreg)

# Sound level measurement from 32-bit I2S words of an SPH0645LM4H microphone.
#
# Only levels are computed; audio never leaves this module. Levels are in dB
# relative to digital full scale (an 18-bit sample amplitude of 2**17), stored
# as integer tenths of a dB.
import math
import struct
from array import array

MAX_BLOCK = 4096  # samples per accumulate() call, bounded by 32-bit sums
FLOOR_DB10 = -1200
_FULL_SCALE_DB = 10 * math.log10(2**34)


def accumulate_ref(buf, n, st):
    """Process n samples of buf, updating st = [dc, hh, hl, ll, peak].

    A one-pole high-pass (about 20 Hz at 32 kHz) removes the microphone's DC
    offset. The sum of squares of the filtered samples is returned split in
    three 32-bit parts: (hh << 18) + (hl << 10) + ll.
    """
    dc = st[0]
    hh = hl = ll = peak = 0
    for i in range(n):
        x = struct.unpack_from("<i", buf, 4 * i)[0] >> 14
        dc += x - (dc >> 8)
        y = x - (dc >> 8)
        h = y >> 9
        l = y & 0x1FF
        hh += h * h
        hl += h * l
        ll += l * l
        if y < 0:
            y = -y
        if y > peak:
            peak = y
    st[0] = dc
    st[1] = hh
    st[2] = hl
    st[3] = ll
    st[4] = peak


try:
    from sound_viper import accumulate
except ImportError:  # CPython, for tests
    accumulate = accumulate_ref


def to_db10(mean_square):
    if mean_square <= 0:
        return FLOOR_DB10
    db10 = round((10 * math.log10(mean_square) - _FULL_SCALE_DB) * 10)
    return max(FLOOR_DB10, db10)


class Meter:
    """Aggregates blocks of samples into per-interval level statistics."""

    def __init__(self, warmup_blocks=10):
        self.st = array("i", [0, 0, 0, 0, 0])
        self.warmup = warmup_blocks  # lets the DC filter settle after power-up
        self._reset()

    def _reset(self):
        self.total_sq = 0
        self.total_n = 0
        self.max_ms = -1.0
        self.min_ms = -1.0
        self.peak = 0

    def process(self, buf, n):
        st = self.st
        accumulate(buf, n, st)
        if self.warmup > 0:
            self.warmup -= 1
            return
        sq = (st[1] << 18) + (st[2] << 10) + st[3]
        ms = sq / n
        self.total_sq += sq
        self.total_n += n
        if ms > self.max_ms:
            self.max_ms = ms
        if self.min_ms < 0 or ms < self.min_ms:
            self.min_ms = ms
        if st[4] > self.peak:
            self.peak = st[4]

    def snapshot(self):
        """Return (rms, loudest block, quietest block, peak sample) and reset.

        Returns None if no block was processed since the last snapshot.
        """
        if self.total_n == 0:
            return None
        res = (
            to_db10(self.total_sq / self.total_n),
            to_db10(self.max_ms),
            to_db10(self.min_ms),
            to_db10(self.peak * self.peak),
        )
        self._reset()
        return res

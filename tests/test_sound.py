import random
import unittest
from array import array

import support
import sound


class AccumulateTest(unittest.TestCase):
    def test_split_sums_equal_exact_sum_of_squares(self):
        rng = random.Random(1)
        samples = [rng.randint(-(2**17), 2**17 - 1) for _ in range(sound.MAX_BLOCK)]
        st = array("i", [0, 0, 0, 0, 0])
        sound.accumulate_ref(support.words(samples), len(samples), st)

        dc = 0
        expected = 0
        peak = 0
        for x in samples:
            dc += x - (dc >> 8)
            y = x - (dc >> 8)
            expected += y * y
            peak = max(peak, abs(y))
        self.assertEqual((st[1] << 18) + (st[2] << 10) + st[3], expected)
        self.assertEqual(st[4], peak)
        self.assertEqual(st[0], dc)

    def test_low_bits_of_the_word_are_ignored(self):
        st = array("i", [0, 0, 0, 0, 0])
        buf = support.words([5, -5])
        buf[0] |= 0xFF
        sound.accumulate_ref(buf, 2, st)
        self.assertEqual(st[4], 5)


class MeterTest(unittest.TestCase):
    def meter(self, blocks, warmup=10):
        m = sound.Meter(warmup_blocks=warmup)
        for b in blocks:
            m.process(support.words(b), len(b))
        return m

    def test_sine_level(self):
        levels = self.meter([support.sine(1000)] * 15).snapshot()
        expected = support.sine_db(1000)
        self.assertAlmostEqual(levels[0] / 10, expected, delta=0.2)
        self.assertAlmostEqual(levels[1] / 10, expected, delta=0.2)
        self.assertAlmostEqual(levels[2] / 10, expected, delta=0.2)
        self.assertAlmostEqual(levels[3] / 10, expected + 3.01, delta=0.2)

    def test_dc_offset_is_removed(self):
        levels = self.meter([support.sine(1000, offset=20000)] * 30).snapshot()
        self.assertAlmostEqual(levels[0] / 10, support.sine_db(1000), delta=0.2)

    def test_min_and_max_follow_blocks(self):
        quiet, loud = support.sine(100), support.sine(10000)
        rms, mx, mn, peak = self.meter([quiet] * 12 + [loud] + [quiet] * 4).snapshot()
        self.assertAlmostEqual(mx / 10, support.sine_db(10000), delta=0.3)
        self.assertAlmostEqual(mn / 10, support.sine_db(100), delta=0.3)
        self.assertTrue(mn < rms < mx)
        self.assertAlmostEqual(peak / 10, support.sine_db(10000) + 3.01, delta=0.3)

    def test_silence_hits_the_floor(self):
        self.assertEqual(self.meter([[0] * 3200] * 12).snapshot(), (-1200,) * 4)

    def test_snapshot_resets_and_warmup_is_skipped(self):
        m = self.meter([support.sine(1000)] * 10)
        self.assertIsNone(m.snapshot())
        m.process(support.words(support.sine(1000)), 3200)
        self.assertIsNotNone(m.snapshot())
        self.assertIsNone(m.snapshot())


if __name__ == "__main__":
    unittest.main()

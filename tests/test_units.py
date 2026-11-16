import struct
import unittest

import support
import bh1750
import httpc
import otlp
import sntp


class FakeI2C:
    def __init__(self, reading=b"\x00\x00"):
        self.writes = []
        self.reading = reading

    def writeto(self, addr, data):
        self.writes.append((addr, bytes(data)))

    def readfrom(self, addr, n):
        return self.reading


class BH1750Test(unittest.TestCase):
    def test_default_sensitivity(self):
        self.assertAlmostEqual(bh1750.raw_to_lux(120, 69), 50.0)

    def test_setup_commands_and_reading(self):
        i2c = FakeI2C(b"\xff\xff")
        sensor = bh1750.BH1750(i2c, 0x23, 254)
        self.assertEqual([w[1] for w in i2c.writes], [b"\x01", b"\x47", b"\x7e", b"\x11"])
        self.assertAlmostEqual(sensor.lux(), 7417.8, delta=0.1)

    def test_sensitivity_is_clamped(self):
        self.assertEqual(bh1750.BH1750(FakeI2C(), mtreg=1000).mtreg, 254)
        self.assertEqual(bh1750.BH1750(FakeI2C(), mtreg=1).mtreg, 31)


def ntp_packet(secs, first=0x24, stratum=2):
    pkt = bytearray(48)
    pkt[0] = first
    pkt[1] = stratum
    pkt[40:44] = struct.pack("!I", secs)
    return bytes(pkt)


class SntpTest(unittest.TestCase):
    def test_request(self):
        pkt = sntp.request_packet()
        self.assertEqual((len(pkt), pkt[0]), (48, 0x23))

    def test_parse(self):
        # 2026-11-14 00:00:00 UTC
        self.assertEqual(sntp.parse_response(ntp_packet(1794614400 + 2208988800)), 1794614400)

    def test_parse_after_2036_rollover(self):
        self.assertEqual(sntp.parse_response(ntp_packet(1000)), 1000 + 2**32 - 2208988800)

    def test_rejects_bad_responses(self):
        good = 1794614400 + 2208988800
        for pkt in (
            b"\x24" * 10,
            ntp_packet(good, first=0x23),
            ntp_packet(good, stratum=0),
            ntp_packet(0),
        ):
            with self.assertRaises(ValueError):
                sntp.parse_response(pkt)


class HttpTest(unittest.TestCase):
    def test_parse_url(self):
        self.assertEqual(
            httpc.parse_url("http://collector.example:4318/v1/metrics"),
            ("collector.example", 4318, "/v1/metrics"),
        )
        self.assertEqual(httpc.parse_url("http://host"), ("host", 80, "/"))
        for bad in ("https://host/x", "host/x", "http:///x"):
            with self.assertRaises(ValueError):
                httpc.parse_url(bad)

    def test_parse_status(self):
        self.assertEqual(httpc.parse_status(b"HTTP/1.1 401 Unauthorized\r\n"), 401)
        with self.assertRaises(ValueError):
            httpc.parse_status(b"")

    def test_post(self):
        for status in (200, 401):
            collector = support.Collector(status)
            try:
                feeds = []
                got = httpc.post(
                    ("127.0.0.1", collector.port, "/v1/metrics"),
                    b'{"a": 1}',
                    "s3cret",
                    feed=lambda: feeds.append(1),
                )
            finally:
                collector.close()
            self.assertEqual(got, status)
            path, headers, body = collector.requests[0]
            self.assertEqual(path, "/v1/metrics")
            self.assertEqual(headers["Authorization"], "Bearer s3cret")
            self.assertEqual(headers["Content-Type"], "application/json")
            self.assertEqual(body, {"a": 1})
            self.assertEqual(len(feeds), 3)


class OtlpTest(unittest.TestCase):
    def test_encode(self):
        points = [
            (1794614400, 1234, -453, -401, -520, -350, -61, 10),
            (1794614405, None, -460, -410, -530, -360, None, 15),
        ]
        doc = otlp.encode(points, (("service.name", "early-bird"),), "early-bird", "0.1.0")
        rm = doc["resourceMetrics"][0]
        self.assertEqual(
            rm["resource"]["attributes"],
            [{"key": "service.name", "value": {"stringValue": "early-bird"}}],
        )
        scope = rm["scopeMetrics"][0]
        self.assertEqual(scope["scope"], {"name": "early-bird", "version": "0.1.0"})
        metrics = {m["name"]: m for m in scope["metrics"]}
        self.assertEqual(len(metrics), 7)

        light = metrics["light.illuminance"]
        self.assertEqual(light["unit"], "lx")
        self.assertEqual(
            light["gauge"]["dataPoints"],
            [{"timeUnixNano": "1794614400000000000", "asDouble": 12.34}],
        )
        rms = metrics["sound.level.rms"]["gauge"]["dataPoints"]
        self.assertEqual([dp["asDouble"] for dp in rms], [-45.3, -46.0])
        self.assertEqual(rms[1]["timeUnixNano"], "1794614405000000000")
        self.assertEqual(len(metrics["wifi.rssi"]["gauge"]["dataPoints"]), 1)
        self.assertEqual(metrics["wifi.rssi"]["gauge"]["dataPoints"][0]["asInt"], "-61")
        self.assertEqual(
            [dp["asInt"] for dp in metrics["system.uptime"]["gauge"]["dataPoints"]], ["10", "15"]
        )

    def test_metric_without_values_is_omitted(self):
        points = [(1794614400, None, -453, -401, -520, -350, None, 10)]
        doc = otlp.encode(points, (), "s", "v")
        names = [m["name"] for m in doc["resourceMetrics"][0]["scopeMetrics"][0]["metrics"]]
        self.assertNotIn("light.illuminance", names)
        self.assertNotIn("wifi.rssi", names)
        self.assertEqual(len(names), 5)

    def test_payload_is_json_bytes(self):
        import json

        body = otlp.payload([(1, 2, 3, 4, 5, 6, 7, 8)], (), "s", "v")
        self.assertIsInstance(body, bytes)
        self.assertIn("resourceMetrics", json.loads(body))


if __name__ == "__main__":
    unittest.main()

"""Runs the main loop on the host against fake hardware and a local collector."""
import sys
import types
import unittest

import support
import bh1750

BLOCK = support.words(support.sine(1000))


class Clock:
    ms = 0


class Pin:
    OUT = 1

    def __init__(self, *args, **kwargs):
        self.state = 0

    def value(self, v=None):
        if v is not None:
            self.state = v
        return self.state


class I2C:
    fail = False

    def __init__(self, *args, **kwargs):
        pass

    def writeto(self, addr, data):
        if I2C.fail:
            raise OSError(5)

    def readfrom(self, addr, n):
        if I2C.fail:
            raise OSError(5)
        return b"\x12\x34"


class I2S:
    RX = 0
    MONO = 0

    def __init__(self, *args, **kwargs):
        pass

    def readinto(self, buf):
        buf[:] = BLOCK
        Clock.ms += 100
        return len(buf)


class WDT:
    feeds = 0

    def __init__(self, timeout):
        pass

    def feed(self):
        WDT.feeds += 1


class RTC:
    last = None

    def datetime(self, t):
        RTC.last = t


class WLAN:
    reachable = True

    def __init__(self, iface):
        self.connected = False
        self.connects = 0

    def active(self, on):
        pass

    def config(self, **kwargs):
        pass

    def isconnected(self):
        return self.connected and WLAN.reachable

    def disconnect(self):
        self.connected = False

    def connect(self, ssid, password):
        self.connects += 1
        self.credentials = (ssid, password)
        self.connected = True

    def status(self, what=None):
        return -55


def install_fakes():
    machine = types.ModuleType("machine")
    machine.Pin, machine.I2C, machine.I2S, machine.WDT, machine.RTC = Pin, I2C, I2S, WDT, RTC
    machine.unique_id = lambda: b"\x01\xab"
    machine.mem32 = {}
    network = types.ModuleType("network")
    network.STA_IF = 0
    network.WLAN = WLAN
    network.hostname = lambda name: None
    rp2 = types.ModuleType("rp2")
    rp2.country = lambda code: None
    secrets = types.ModuleType("device_secrets")
    secrets.WIFI_SSID = "ssid"
    secrets.WIFI_PASSWORD = "pw"
    secrets.OTLP_BEARER_TOKEN = "tok"
    secrets.OTLP_URL = "http://collector.example:4318/v1/metrics"
    sys.modules.update(machine=machine, network=network, rp2=rp2, device_secrets=secrets)


install_fakes()
import app
import config
import sntp

app.ticks_ms = lambda: Clock.ms


class AppTest(unittest.TestCase):
    def setUp(self):
        Clock.ms = 0
        I2C.fail = False
        WLAN.reachable = True
        self.ntp_hosts = []
        self.ntp_fail = set()

        def query(host, timeout=2, feed=None):
            self.ntp_hosts.append(host)
            if host in self.ntp_fail:
                raise OSError("timeout")
            return 1794614400

        self.addCleanup(setattr, sntp, "query", sntp.query)
        sntp.query = query

    def start(self, status=200):
        self.collector = support.Collector(status)
        self.addCleanup(self.collector.close)
        sys.modules["device_secrets"].OTLP_URL = "http://127.0.0.1:%d/v1/metrics" % self.collector.port
        return app.App()

    def run_seconds(self, a, seconds):
        for _ in range(seconds * 10):
            a.step()

    def metrics(self, request):
        scope = request[2]["resourceMetrics"][0]["scopeMetrics"][0]
        return {m["name"]: m["gauge"]["dataPoints"] for m in scope["metrics"]}

    def test_reports_to_collector(self):
        a = self.start()
        self.run_seconds(a, 40)

        self.assertEqual(a.wlan.credentials, ("ssid", "pw"))
        self.assertEqual(self.ntp_hosts, ["time.cloudflare.com"])
        self.assertEqual(RTC.last[:3], (2026, 11, 14))
        self.assertTrue(WDT.feeds > 0)
        self.assertEqual(a.led.state, 0)

        # First point goes out as soon as it exists, then one batch per 30 s.
        self.assertEqual(len(self.collector.requests), 2)
        path, headers, body = self.collector.requests[1]
        self.assertEqual(path, "/v1/metrics")
        self.assertEqual(headers["Authorization"], "Bearer tok")
        attrs = {
            kv["key"]: kv["value"]["stringValue"]
            for kv in body["resourceMetrics"][0]["resource"]["attributes"]
        }
        self.assertEqual(attrs["service.name"], "early-bird")
        self.assertEqual(attrs["device.id"], "01ab")

        m = self.metrics(self.collector.requests[1])
        self.assertEqual(len(m), 7)
        self.assertEqual(len(m["sound.level.rms"]), 6)
        self.assertAlmostEqual(m["sound.level.rms"][0]["asDouble"], support.sine_db(1000), delta=0.2)
        self.assertAlmostEqual(
            m["light.illuminance"][0]["asDouble"], bh1750.raw_to_lux(0x1234, 254), delta=0.01
        )
        self.assertEqual(m["wifi.rssi"][0]["asInt"], "-55")
        uptimes = [int(dp["asInt"]) for dp in m["system.uptime"]]
        self.assertEqual(uptimes, [10, 15, 20, 25, 30, 35])
        # The point taken at 40 s waits for the next batch.
        self.assertEqual(len(a.queue), 1)
        self.assertIsInstance(a.queue[0][0], int)

    def test_ntp_falls_back_to_next_server(self):
        self.ntp_fail = {"time.cloudflare.com"}
        a = self.start()
        self.run_seconds(a, 9)
        self.assertFalse(a.clock_set)
        self.assertEqual(a.queue, [])
        self.run_seconds(a, 3)
        self.assertTrue(a.clock_set)
        self.assertEqual(self.ntp_hosts, ["time.cloudflare.com", "time.google.com"])

    def test_points_are_kept_while_collector_rejects_then_drained(self):
        a = self.start(status=503)
        self.run_seconds(a, 121)
        self.assertEqual(len(a.queue), 24)
        self.collector.status = 200
        self.collector.requests.clear()
        self.run_seconds(a, 30)
        sizes = [len(self.metrics(r)["sound.level.rms"]) for r in self.collector.requests]
        self.assertEqual(sizes[:2], [12, 12])
        self.assertTrue(len(a.queue) < 12)

    def test_queue_is_bounded_while_offline(self):
        a = self.start()
        self.run_seconds(a, 6)
        WLAN.reachable = False
        self.addCleanup(setattr, config, "QUEUE_MAX_POINTS", config.QUEUE_MAX_POINTS)
        config.QUEUE_MAX_POINTS = 5
        self.run_seconds(a, 60)
        self.assertEqual(len(a.queue), 5)
        self.assertTrue(a.wlan.connects >= 3)
        self.assertTrue(a.queue[0][0] <= a.queue[-1][0])

    def test_rejected_batch_is_dropped(self):
        a = self.start(status=400)
        self.run_seconds(a, 6)
        self.assertEqual(len(self.collector.requests), 1)
        self.assertEqual(a.queue, [])

    def test_missing_light_sensor_still_reports_sound(self):
        I2C.fail = True
        a = self.start()
        self.run_seconds(a, 6)
        m = self.metrics(self.collector.requests[0])
        self.assertNotIn("light.illuminance", m)
        self.assertIn("sound.level.rms", m)


if __name__ == "__main__":
    unittest.main()

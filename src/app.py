# early-bird: reports light and sound levels to an OpenTelemetry Collector.
import gc
import time

import machine
import network
import rp2

import bh1750
import config
import device_secrets
import httpc
import otlp
import sntp
import sound

try:
    from time import ticks_ms, ticks_diff, ticks_add
except ImportError:  # CPython, for tests

    def ticks_ms():
        return int(time.monotonic() * 1000)

    def ticks_diff(a, b):
        return a - b

    def ticks_add(a, b):
        return a + b


VERSION = "0.1.0"

# time.time() counts from 2000 on some MicroPython ports, from 1970 on others.
_EPOCH_OFFSET = 946684800 if time.gmtime(0)[0] == 2000 else 0
_WIFI_RETRY_MS = 20000
_WDT_TIMEOUT_MS = 8000
_WDT_CTRL_CLR = 0x400D8000 + 0x3000  # RP2350 watchdog CTRL, atomic-clear alias
_WDT_ENABLE = 1 << 30


def stop_watchdog():
    """Let the board sit at the REPL after Ctrl-C without being reset."""
    machine.mem32[_WDT_CTRL_CLR] = _WDT_ENABLE


def unix_time():
    return int(time.time()) + _EPOCH_OFFSET


def set_clock(unix_s):
    t = time.gmtime(unix_s - _EPOCH_OFFSET)
    machine.RTC().datetime((t[0], t[1], t[2], t[6], t[3], t[4], t[5], 0))


class App:
    def __init__(self):
        self.led = machine.Pin("LED", machine.Pin.OUT)
        self.led.value(0)

        self.i2c = machine.I2C(
            config.I2C_ID,
            sda=machine.Pin(config.I2C_SDA),
            scl=machine.Pin(config.I2C_SCL),
            freq=100000,
        )
        self.light = None
        self.lux_sum = 0.0
        self.lux_n = 0

        block = config.AUDIO_RATE // 10
        if block > sound.MAX_BLOCK:
            raise ValueError("AUDIO_RATE too high")
        self.buf = bytearray(block * 4)
        self.meter = sound.Meter()
        self.i2s = machine.I2S(
            config.I2S_ID,
            sck=machine.Pin(config.I2S_SCK),
            ws=machine.Pin(config.I2S_WS),
            sd=machine.Pin(config.I2S_SD),
            mode=machine.I2S.RX,
            bits=32,
            format=machine.I2S.MONO,
            rate=config.AUDIO_RATE,
            ibuf=len(self.buf) * 5,
        )

        rp2.country(config.WIFI_COUNTRY)
        network.hostname(config.DEVICE_NAME)
        self.wlan = network.WLAN(network.STA_IF)
        self.wlan.active(True)
        self.wlan.config(pm=0xA11140)  # no power saving: steadier link

        self.target = httpc.parse_url(device_secrets.OTLP_URL)
        uid = "".join("%02x" % b for b in machine.unique_id())
        self.resource = (
            ("service.name", config.DEVICE_NAME),
            ("service.version", VERSION),
            ("host.name", config.DEVICE_NAME),
            ("device.id", uid),
        )

        self.queue = []
        self.clock_set = False
        self.ntp_index = 0
        self.uptime_ms = 0

        now = ticks_ms()
        self.last_ms = now
        self.t_lux = now
        self.t_sample = ticks_add(now, config.SAMPLE_INTERVAL_S * 1000)
        self.t_wifi = now
        self.t_ntp = now
        self.t_export = now

        self.wdt = machine.WDT(timeout=_WDT_TIMEOUT_MS) if config.WATCHDOG else None

    def feed(self):
        if self.wdt:
            self.wdt.feed()

    def read_light(self):
        try:
            if self.light is None:
                self.light = bh1750.BH1750(self.i2c, config.BH1750_ADDR, config.BH1750_MTREG)
                return  # first measurement is not ready yet
            self.lux_sum += self.light.lux()
            self.lux_n += 1
        except OSError as e:
            if self.light is not None:
                print("light sensor error:", e)
            self.light = None

    def sample(self):
        levels = self.meter.snapshot()
        lux = round(self.lux_sum / self.lux_n * 100) if self.lux_n else None
        self.lux_sum = 0.0
        self.lux_n = 0
        if not self.clock_set or levels is None:
            return
        rssi = self.wlan.status("rssi") if self.wlan.isconnected() else None
        point = (unix_time(), lux) + levels + (rssi, self.uptime_ms // 1000)
        if len(self.queue) >= config.QUEUE_MAX_POINTS:
            del self.queue[0]
        self.queue.append(point)

    def connect_wifi(self):
        print("wifi: connecting")
        try:
            self.wlan.disconnect()
        except OSError:
            pass
        self.wlan.connect(device_secrets.WIFI_SSID, device_secrets.WIFI_PASSWORD)

    def sync_clock(self):
        servers = config.NTP_SERVERS
        host = servers[self.ntp_index % len(servers)]
        try:
            set_clock(sntp.query(host, config.NTP_TIMEOUT_S, self.feed))
        except Exception as e:
            print("ntp:", host, "failed:", repr(e))
            self.ntp_index += 1
            self.t_ntp = ticks_add(ticks_ms(), config.NTP_RETRY_S * 1000)
            return
        print("ntp: clock set from", host)
        self.clock_set = True
        self.t_ntp = ticks_add(ticks_ms(), config.NTP_RESYNC_S * 1000)

    def export(self):
        batch = self.queue[: config.EXPORT_MAX_POINTS]
        body = otlp.payload(batch, self.resource, config.DEVICE_NAME, VERSION)
        try:
            status = httpc.post(
                self.target, body, device_secrets.OTLP_BEARER_TOKEN, config.HTTP_TIMEOUT_S, self.feed
            )
        except Exception as e:
            print("export failed:", repr(e))
            status = 0
        delay_s = config.EXPORT_INTERVAL_S
        if 200 <= status < 300 or status == 400:
            # A 400 means the collector will never accept this batch: drop it.
            if status == 400:
                print("export: batch rejected, dropped")
            del self.queue[: len(batch)]
            if len(self.queue) >= config.EXPORT_MAX_POINTS:
                delay_s = 0  # drain the backlog
        elif status:
            print("export: HTTP", status)
        self.t_export = ticks_add(ticks_ms(), delay_s * 1000)
        del body
        gc.collect()

    def network(self, now):
        if not self.wlan.isconnected():
            if ticks_diff(now, self.t_wifi) >= 0:
                self.t_wifi = ticks_add(now, _WIFI_RETRY_MS)
                self.connect_wifi()
            return
        if ticks_diff(now, self.t_ntp) >= 0:
            self.sync_clock()
        elif self.clock_set and self.queue and ticks_diff(now, self.t_export) >= 0:
            self.export()

    def step(self):
        # Blocks until a 100 ms block of audio is available: this paces the loop.
        n = self.i2s.readinto(self.buf)
        if n:
            self.meter.process(self.buf, n // 4)
        self.feed()

        now = ticks_ms()
        self.uptime_ms += ticks_diff(now, self.last_ms)
        self.last_ms = now

        if ticks_diff(now, self.t_lux) >= 0:
            self.t_lux = ticks_add(now, 1000)
            self.read_light()
        if ticks_diff(now, self.t_sample) >= 0:
            self.t_sample = ticks_add(now, config.SAMPLE_INTERVAL_S * 1000)
            self.sample()
        self.network(now)
        if config.STATUS_LED:
            self.led.value(0 if self.clock_set and self.wlan.isconnected() else 1)

    def run(self):
        print("early-bird", VERSION)
        while True:
            self.step()


def main():
    App().run()

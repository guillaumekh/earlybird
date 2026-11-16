# Hardware bring-up checks. Run with: make diag
# Needs the firmware modules on the device (make deploy) and main.py stopped,
# which mpremote does by itself.
import struct
import time
from array import array

import machine
import network

import bh1750
import config
import httpc
import sntp
import sound


def check_light():
    print("== light sensor")
    i2c = machine.I2C(
        config.I2C_ID, sda=machine.Pin(config.I2C_SDA), scl=machine.Pin(config.I2C_SCL), freq=100000
    )
    found = i2c.scan()
    print("I2C devices:", [hex(a) for a in found])
    if config.BH1750_ADDR not in found:
        print("FAIL: BH1750 not found at", hex(config.BH1750_ADDR))
        return
    sensor = bh1750.BH1750(i2c, config.BH1750_ADDR, config.BH1750_MTREG)
    for _ in range(3):
        time.sleep(1)
        print("lux: %.2f" % sensor.lux())


def check_viper():
    print("== sound maths, fast path against reference")
    n = 512
    buf = bytearray(n * 4)
    seed = 12345
    for i in range(len(buf)):
        seed = (seed * 1103515245 + 12345) & 0x7FFFFFFF
        buf[i] = (seed >> 16) & 0xFF
    a = array("i", [777, 0, 0, 0, 0])
    b = array("i", [777, 0, 0, 0, 0])
    sound.accumulate(buf, n, a)
    sound.accumulate_ref(buf, n, b)
    print("OK" if list(a) == list(b) else "FAIL: %s != %s" % (list(a), list(b)))


def check_mic():
    print("== microphone, 5 s. Stay quiet, then clap.")
    block = config.AUDIO_RATE // 10
    buf = bytearray(block * 4)
    i2s = machine.I2S(
        config.I2S_ID,
        sck=machine.Pin(config.I2S_SCK),
        ws=machine.Pin(config.I2S_WS),
        sd=machine.Pin(config.I2S_SD),
        mode=machine.I2S.RX,
        bits=32,
        format=machine.I2S.MONO,
        rate=config.AUDIO_RATE,
        ibuf=len(buf) * 5,
    )
    meter = sound.Meter()
    try:
        for i in range(50):
            n = i2s.readinto(buf)
            meter.process(buf, n // 4)
            if i % 10 == 9:
                print("first words:", [hex(w) for w in struct.unpack("<4I", buf[:16])])
                levels = meter.snapshot()
                if levels:
                    print("dBFS rms %.1f  max %.1f  min %.1f  peak %.1f" % tuple(v / 10 for v in levels))
    finally:
        i2s.deinit()
    print("Expect about -90 to -70 dBFS rms in a quiet room, well above that on a clap.")
    print("All-zero or all-ff words mean the microphone is not wired or not powered.")


def check_network():
    print("== network")
    try:
        import device_secrets
    except ImportError:
        print("skipped: no secrets on the device, run make build and make deploy first")
        return
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        wlan.connect(device_secrets.WIFI_SSID, device_secrets.WIFI_PASSWORD)
        for _ in range(20):
            if wlan.isconnected():
                break
            time.sleep(1)
    if not wlan.isconnected():
        print("FAIL: Wi-Fi not connected, status", wlan.status())
        return
    print("Wi-Fi:", wlan.ifconfig()[0], "rssi", wlan.status("rssi"))
    for host in config.NTP_SERVERS:
        try:
            print("NTP", host, "->", sntp.query(host, config.NTP_TIMEOUT_S))
        except Exception as e:
            print("FAIL: NTP", host, repr(e))
    target = httpc.parse_url(device_secrets.OTLP_URL)
    try:
        status = httpc.post(target, b'{"resourceMetrics":[]}', device_secrets.OTLP_BEARER_TOKEN)
        print("collector", target[0], "-> HTTP", status)
    except Exception as e:
        print("FAIL: collector", target[0], repr(e))


check_light()
check_viper()
check_mic()
check_network()

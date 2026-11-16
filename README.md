# early-bird

A Raspberry Pi Pico 2 W that sits in a child's bedroom and reports light and
sound levels, so that morning wake-ups can be seen in the data. It sends
measurements only: no audio leaves the device, and nothing is detected or
alerted on the device itself.

- Light: BH1750 over I2C
- Sound: SPH0645LM4H microphone over I2S, reduced to levels on the device
- Output: OTLP/HTTP (JSON) to an OpenTelemetry Collector, with a bearer token
- Time: NTP from Cloudflare, falling back to Google

Wiring and assembly are in [hardware/](hardware/README.md).

## Layout

| Path | Contents |
|---|---|
| `src/` | MicroPython firmware |
| `src/config.py` | Settings that are fine to publish: intervals, pins, NTP servers |
| `src/diag.py` | Hardware bring-up checks, run from the computer |
| `tools/build.py` | Generates the application, with secrets, into `build/` |
| `local.env` | Build settings, git-ignored: Wi-Fi credentials, collector URL |
| `local.env.example` | Template for `local.env` |
| `tests/` | Host tests, plain `unittest` |
| `hardware/` | Schematic and assembly instructions |

## Requirements

On the computer: Python 3, `mpremote`, `make`, and a micro-USB data cable.
A secrets manager such as the 1Password CLI is optional.

## Wi-Fi

The Pico joins a dedicated 2.4 GHz network. The setup known to work:

- WPA2-PSK only, with 802.11r fast transition off.
- A channel from 1 to 11: the Pico did not see the access point on channel
  13, even with the country set.
- A hidden network name is fine.

Bring-up notes, for the next time it refuses to connect:

- Status -3 from `wlan.status()` means the access point refused the join.
  A wrong passphrase and other handshake failures look identical.
- Status 1 that never changes means no matching network was found, for
  example when the network had lost its authentication setting and was open.
- Several refusals during bring-up came from the router rather than the
  Pico: after security settings were edited, the passphrase in effect was
  out of step with the configured one.
- Joining a WPA2+WPA3 network was refused most of the time and accepted at
  least once; that was never fully explained. WPA3 on this board is the
  subject of
  [micropython#18597](https://github.com/micropython/micropython/issues/18597).

## First-time setup

1. Download the MicroPython firmware for the **Pico 2 W** from
   <https://micropython.org/download/RPI_PICO2_W/>.
2. Hold the BOOTSEL button while plugging the Pico into the computer. It
   appears as a USB drive.
3. Copy the `.uf2` file onto that drive. The Pico reboots into MicroPython.

## Build and deploy

```sh
make test     # host tests, no hardware needed
make build    # generate build/ from the settings in the environment
make deploy   # copy build/ to the Pico and reboot it
make diag     # check both sensors, Wi-Fi, NTP and the collector
make repl     # watch the device's log output
```

### Build settings

`make build` reads its settings from environment variables. Copy
`local.env.example` to `local.env`, which is git-ignored, and fill it in:

| Variable | Value |
|---|---|
| `WIFI_SSID`, `WIFI_PASSWORD` | The Wi-Fi network the Pico joins |
| `OTLP_URL` | The collector's OTLP/HTTP metrics endpoint, plain `http://` |
| `OTLP_BEARER_TOKEN` | The collector's bearer token. Optional: if unset, the build asks for it |

Then load the file into the environment for the build, in whichever way
suits you:

```sh
# Plain values in local.env
(set -a; . ./local.env; set +a; make build)

# 1Password references (op://...) in local.env
op run --env-file=local.env -- make build
```

The values end up in `build/device_secrets.py`, which is git-ignored, and in
plain text on the Pico's flash.

## Metrics

One data point per metric every 5 seconds, sent in one request every 30
seconds. All are gauges.

| Metric | Unit | Meaning |
|---|---|---|
| `light.illuminance` | lx | Mean of the readings taken each second |
| `sound.level.rms` | dB | RMS level over the 5 seconds |
| `sound.level.max` | dB | Loudest 100 ms of the 5 seconds |
| `sound.level.min` | dB | Quietest 100 ms, in practice the noise floor |
| `sound.level.peak` | dB | Highest single sample |
| `wifi.rssi` | dBm | Wi-Fi signal strength |
| `system.uptime` | s | Time since boot |

Sound levels are in dB relative to digital full scale, so they are negative
and uncalibrated: about -90 is silence and 0 is the loudest the microphone
can report. The resource attributes are `service.name`, `service.version`,
`host.name` and `device.id`.

## Behaviour

- Nothing is recorded until the clock has been set by NTP, so every data
  point has a valid timestamp. The clock is set again every 6 hours.
- If the collector or Wi-Fi is down, up to an hour of data points is kept in
  RAM and sent on recovery with the original timestamps. Beyond that the
  oldest points are dropped. A reboot loses the backlog.
- A batch answered with HTTP 400 is dropped; any other failure is retried.
- A watchdog reboots the device if the main loop stalls for 8 seconds.
- The onboard LED stays off. Set `STATUS_LED = True` in `src/config.py` to
  have it lit while Wi-Fi or the clock is down.
- The collector URL must be plain `http://`.

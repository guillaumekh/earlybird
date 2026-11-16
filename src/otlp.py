# OTLP/HTTP JSON encoding of queued data points.
#
# A point is a tuple of integers (or None where a reading is missing):
#   (unix_time_s, lux x100, rms dB x10, max dB x10, min dB x10, peak dB x10,
#    rssi dBm, uptime_s)
import json

# (index in point, name, unit, description, divisor or None for integers)
METRICS = (
    (1, "light.illuminance", "lx", "Ambient light, mean over the interval", 100),
    (2, "sound.level.rms", "dB", "RMS sound level over the interval, dB full scale", 10),
    (3, "sound.level.max", "dB", "Loudest 100 ms of the interval, dB full scale", 10),
    (4, "sound.level.min", "dB", "Quietest 100 ms of the interval, dB full scale", 10),
    (5, "sound.level.peak", "dB", "Highest sample of the interval, dB full scale", 10),
    (6, "wifi.rssi", "dBm", "Wi-Fi signal strength", None),
    (7, "system.uptime", "s", "Time since boot", None),
)


def _data_point(t, value, divisor):
    dp = {"timeUnixNano": str(t) + "000000000"}
    if divisor is None:
        dp["asInt"] = str(value)
    else:
        dp["asDouble"] = value / divisor
    return dp


def encode(points, resource, scope_name, scope_version):
    metrics = []
    for idx, name, unit, description, divisor in METRICS:
        dps = [_data_point(p[0], p[idx], divisor) for p in points if p[idx] is not None]
        if dps:
            metrics.append(
                {"name": name, "unit": unit, "description": description, "gauge": {"dataPoints": dps}}
            )
    attributes = [{"key": k, "value": {"stringValue": v}} for k, v in resource]
    return {
        "resourceMetrics": [
            {
                "resource": {"attributes": attributes},
                "scopeMetrics": [
                    {"scope": {"name": scope_name, "version": scope_version}, "metrics": metrics}
                ],
            }
        ]
    }


def payload(points, resource, scope_name, scope_version):
    return json.dumps(encode(points, resource, scope_name, scope_version)).encode()

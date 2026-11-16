# Minimal SNTP client, one-second precision.
import socket
import struct

_NTP_TO_UNIX = 2208988800


def request_packet():
    pkt = bytearray(48)
    pkt[0] = 0x23  # no leap warning, version 4, client mode
    return pkt


def parse_response(data):
    """Return the server's transmit time as Unix seconds."""
    if len(data) < 48:
        raise ValueError("short NTP response")
    if data[0] & 0x07 != 4:
        raise ValueError("not an NTP server response")
    if not 1 <= data[1] <= 15:
        raise ValueError("NTP server not synchronised")
    secs = struct.unpack("!I", data[40:44])[0]
    if secs == 0:
        raise ValueError("empty NTP timestamp")
    if secs < 0x80000000:  # NTP era 1, from 2036
        secs += 0x100000000
    return secs - _NTP_TO_UNIX


def query(host, timeout=2, feed=None):
    addr = socket.getaddrinfo(host, 123)[0][-1]
    if feed:
        feed()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.settimeout(timeout)
        s.sendto(request_packet(), addr)
        data = s.recv(48)
    finally:
        s.close()
    return parse_response(data)

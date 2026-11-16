# Minimal HTTP POST client with a bearer token. Plain http only.
import socket


def parse_url(url):
    """Split an http URL into (host, port, path)."""
    if not url.startswith("http://"):
        raise ValueError("only http:// URLs are supported")
    rest = url[7:]
    slash = rest.find("/")
    if slash < 0:
        hostport, path = rest, "/"
    else:
        hostport, path = rest[:slash], rest[slash:]
    if ":" in hostport:
        host, port = hostport.split(":")
        port = int(port)
    else:
        host, port = hostport, 80
    if not host:
        raise ValueError("no host in URL")
    return host, port, path


def build_head(host, port, path, length, token):
    return (
        "POST %s HTTP/1.1\r\n"
        "Host: %s:%d\r\n"
        "Authorization: Bearer %s\r\n"
        "Content-Type: application/json\r\n"
        "Content-Length: %d\r\n"
        "Connection: close\r\n\r\n" % (path, host, port, token, length)
    ).encode()


def parse_status(data):
    """Return the status code of a response starting with b'HTTP/1.1 200 ...'."""
    parts = data.split(b" ", 2)
    if len(parts) < 2 or not parts[0].startswith(b"HTTP/"):
        raise ValueError("bad HTTP response")
    return int(parts[1][:3])


def post(target, body, token, timeout=5, feed=None):
    """POST body to target = (host, port, path) and return the status code."""
    host, port, path = target
    addr = socket.getaddrinfo(host, port)[0][-1]
    if feed:
        feed()
    s = socket.socket()
    try:
        s.settimeout(timeout)
        s.connect(addr)
        if feed:
            feed()
        s.sendall(build_head(host, port, path, len(body), token))
        s.sendall(body)
        if feed:
            feed()
        data = b""
        while len(data) < 12:
            chunk = s.recv(64)
            if not chunk:
                break
            data += chunk
    finally:
        s.close()
    return parse_status(data)

"""IPP client for Epson printer monitoring."""

import logging
import socket
import ssl
import struct

from .const import IPP_PATHS

_LOGGER = logging.getLogger(__name__)

# IPP Tags
TAG_OPERATION = 0x01
TAG_PRINTER = 0x04
TAG_UNSUPPORTED = 0x10
TAG_INTEGER = 0x21
TAG_BOOLEAN = 0x22
TAG_ENUM = 0x23
TAG_KEYWORD = 0x44
TAG_URI = 0x45
TAG_CHARSET = 0x47
TAG_LANGUAGE = 0x48
TAG_NAME_WITHOUT_LANG = 0x42
TAG_TEXT_WITHOUT_LANG = 0x41
TAG_END = 0x03


class EpsonIppClient:
    """Low-level IPP client for Epson printers."""

    def __init__(self, host: str, port: int = 631, use_ssl: bool = True):
        self.host = host
        self.port = port
        self.use_ssl = use_ssl
        self._printer_uri = None
        self._path = None

    def _build_request(self, operation_id: int, printer_uri: str = None) -> bytes:
        """Build an IPP request binary body."""
        parts = []
        # Version 2.0
        parts.append(struct.pack(">H", 0x0200))
        # Operation ID
        parts.append(struct.pack(">H", operation_id))
        # Request ID
        parts.append(struct.pack(">I", 1))
        # Operation attributes group
        parts.append(bytes([TAG_OPERATION]))
        # charset = utf-8
        name = b"attributes-charset"
        val = b"utf-8"
        parts.append(bytes([TAG_CHARSET]))
        parts.append(struct.pack(">H", len(name)))
        parts.append(name)
        parts.append(struct.pack(">H", len(val)))
        parts.append(val)
        # natural-language = en-us
        name = b"attributes-natural-language"
        val = b"en-us"
        parts.append(bytes([TAG_LANGUAGE]))
        parts.append(struct.pack(">H", len(name)))
        parts.append(name)
        parts.append(struct.pack(">H", len(val)))
        parts.append(val)
        # printer-uri (optional for discovery)
        if printer_uri:
            name = b"printer-uri"
            val = printer_uri.encode("ascii")
            parts.append(bytes([TAG_URI]))
            parts.append(struct.pack(">H", len(name)))
            parts.append(name)
            parts.append(struct.pack(">H", len(val)))
            parts.append(val)
        # requested-attributes = all
        name = b"requested-attributes"
        val = b"all"
        parts.append(bytes([TAG_KEYWORD]))
        parts.append(struct.pack(">H", len(name)))
        parts.append(name)
        parts.append(struct.pack(">H", len(val)))
        parts.append(val)
        # End
        parts.append(bytes([TAG_END]))
        return b"".join(parts)

    def _send_request(self, path: str, body: bytes) -> bytes | None:
        """Send IPP request via HTTP and return response body."""
        http_req = (
            f"POST {path} HTTP/1.1\r\n"
            f"Host: {self.host}:{self.port}\r\n"
            f"Content-Type: application/ipp\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Connection: close\r\n\r\n"
        ).encode() + body

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)

            if self.use_ssl:
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                sock = ctx.wrap_socket(sock, server_hostname=self.host)

            sock.connect((self.host, self.port))
            sock.sendall(http_req)

            data = b""
            while True:
                try:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    data += chunk
                except socket.timeout:
                    break
            sock.close()
        except (OSError, ssl.SSLError) as err:
            _LOGGER.debug("IPP request failed: %s", err)
            return None

        # Find body after HTTP headers
        parts = data.split(b"\r\n\r\n", 1)
        if len(parts) < 2:
            return None
        return parts[1]

    def _parse_attributes(self, data: bytes, offset: int) -> tuple[dict, int]:
        """Parse IPP attributes from binary data."""
        attrs = {}
        while offset < len(data):
            if offset >= len(data):
                break
            tag = data[offset]
            if tag == TAG_END:
                offset += 1
                # May be followed by more attribute groups
                if offset < len(data) and data[offset] != TAG_END:
                    continue
                break
            if tag <= 0x0F:
                # Attribute group delimiter (0x00-0x0F), skip to next byte
                offset += 1
                continue
            # Any tag >= 0x10 is a value tag — parse it (even unknown ones)
            offset += 1
            if offset + 2 > len(data):
                break
            name_len = struct.unpack(">H", data[offset : offset + 2])[0]
            offset += 2
            if offset + name_len > len(data):
                break
            name = data[offset : offset + name_len].decode("ascii", errors="replace")
            offset += name_len
            if offset + 2 > len(data):
                break
            val_len = struct.unpack(">H", data[offset : offset + 2])[0]
            offset += 2
            if offset + val_len > len(data):
                break
            val_raw = data[offset : offset + val_len]
            offset += val_len

            # Decode value based on tag type
            value = self._decode_value(tag, val_raw, name)
            attrs[name] = value
        return attrs, offset

    @staticmethod
    def _decode_value(tag: int, val_raw: bytes, attr_name: str):
        """Decode an IPP attribute value."""
        # Out-of-band values (0x10-0x1F)
        if tag == 0x10:
            return None  # unsupported
        if tag == 0x12:
            return None  # no-value
        if tag == 0x13:
            return None  # unknown

        # Integer / Enum (4-byte signed)
        if tag in (0x21, 0x23):
            if len(val_raw) >= 4:
                return struct.unpack(">i", val_raw[:4])[0]
            return int.from_bytes(val_raw, "big", signed=True)

        # Boolean (1 byte)
        if tag == 0x22:
            return bool(val_raw[0]) if val_raw else False

        # Range of Integer (min + max, 8 bytes)
        if tag == 0x33:
            if len(val_raw) >= 8:
                lo = struct.unpack(">i", val_raw[0:4])[0]
                hi = struct.unpack(">i", val_raw[4:8])[0]
                return (lo, hi)
            return None

        # Resolution (cross-feed + feed, 8 bytes + units)
        if tag == 0x32:
            if len(val_raw) >= 9:
                x = struct.unpack(">i", val_raw[0:4])[0]
                y = struct.unpack(">i", val_raw[4:8])[0]
                unit = {3: "dpi", 4: "dpcm"}.get(val_raw[8], "unknown")
                return f"{x}x{y} {unit}"
            return None

        # Text / Name / Keyword / URI / Charset / Language (UTF-8 string)
        if tag in (0x41, 0x42, 0x44, 0x45, 0x47, 0x48):
            return val_raw.decode("utf-8", errors="replace")

        # Text/Name with language (tag 0x35-0x36 range)
        if tag in (0x35, 0x36):
            return val_raw.decode("utf-8", errors="replace")

        # Date/Time (tag 0x31) - 11 bytes
        if tag == 0x31:
            return val_raw

        # 1setOf values (tag 0x34) - beginning of a collection
        if tag == 0x34:
            return val_raw

        # Unknown - try as string
        try:
            return val_raw.decode("utf-8", errors="replace")
        except Exception:
            return val_raw

    def discover(self) -> str | None:
        """Discover printer URI and path by trying common IPP paths."""
        # Epson printers typically support IPPS on port 631 (self-signed cert)
        # Try IPPS first, then plain IPP as fallback
        saved_port = self.port

        for path in IPP_PATHS:
            for port, use_ssl, scheme in [
                (saved_port, True, "ipps"),   # IPPS on configured port
                (saved_port, False, "ipp"),   # IPP on configured port
                (443, True, "ipps"),          # IPPS on 443
            ]:
                self.port = port
                self.use_ssl = use_ssl

                uri = f"{scheme}://{self.host}:{port}{path}"

                body = self._build_request(0x000B, uri)
                resp = self._send_request(path, body)

                if resp and len(resp) > 8:
                    status = struct.unpack(">H", resp[2:4])[0]
                    # 0x0000 = success, 0x0001-0x00FF = successful range
                    if status <= 0x00FF:
                        self._printer_uri = uri
                        self._path = path
                        _LOGGER.info(
                            "Discovered Epson printer at %s (port %d, SSL=%s)",
                            uri, port, use_ssl
                        )
                        return uri

        # Restore original settings
        self.port = saved_port
        return None

    def get_printer_attributes(self) -> dict:
        """Get printer attributes via Get-Printer-Attributes."""
        if not self._printer_uri:
            self.discover()
        if not self._printer_uri:
            return {}

        body = self._build_request(0x000B, self._printer_uri)
        resp = self._send_request(self._path or "/ipp/print", body)

        if not resp or len(resp) < 8:
            return {}

        status = struct.unpack(">H", resp[2:4])[0]
        if status > 0x00FF:  # error
            _LOGGER.debug("IPP status error: 0x%04X", status)
            return {}

        attrs, _ = self._parse_attributes(resp, 8)
        return attrs

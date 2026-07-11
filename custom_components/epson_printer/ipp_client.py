"""IPP client for Epson printer monitoring."""

import io
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
TAG_MIME = 0x49  # mimeMediaType


def _image_to_pwg_raster(
    image_bytes: bytes,
    width: int,
    height: int,
    color_mode: str = "srgb_8",
) -> bytes:
    """Convert a PIL-loaded image to PWG-Raster format.

    PWG Raster (PWG 5102.4) is the standard IPP Everywhere raster format
    used by AirPrint and most modern printers.
    """
    try:
        from PIL import Image
        import io

        img = Image.open(io.BytesIO(image_bytes))

        # Ensure correct mode
        if color_mode == "srgb_8":
            if img.mode != "RGB":
                img = img.convert("RGB")
            num_colors = 3
            bpp = 8
            color_space = 2  # sRGB
            pixel_stride = 3
        elif color_mode == "sgray_8":
            if img.mode != "L":
                img = img.convert("L")
            num_colors = 1
            bpp = 8
            color_space = 1  # sGray
            pixel_stride = 1
        else:
            raise ValueError(f"Unsupported color mode: {color_mode}")

        # Resize to requested dimensions if specified
        if width and height:
            img = img.resize((width, height), Image.LANCZOS)

        actual_width, actual_height = img.size
        bytes_per_line = actual_width * pixel_stride

        # Pad to 4-byte boundary (CUPS/linux convention)
        bytes_per_line_padded = (bytes_per_line + 3) & ~3

        # ── Build PWG-Raster header (512 bytes) ──
        header = bytearray(512)

        # Magic
        header[0:8] = b"PwgRast"

        def _le32(offset: int, val: int):
            header[offset:offset+4] = struct.pack("<I", val)

        _le32(8, 512)           # hdrlen
        _le32(12, actual_height)  # height
        _le32(16, actual_width)   # width
        _le32(20, bpp)           # bpp (bits per pixel per plane)
        _le32(24, color_space)   # colorSpace (1=sGray, 2=sRGB)
        _le32(28, bpp)           # bitsPerColor
        _le32(32, num_colors)    # numColors
        _le32(36, 0)             # reserved
        _le32(40, 0)             # device color space
        _le32(44, 0)             # reserved
        _le32(48, 0)             # reserved
        _le32(52, 0)             # reserved
        _le32(56, 0)             # reserved
        _le32(60, 0)             # reserved
        _le32(64, 0)             # reserved
        _le32(68, 0)             # reserved
        _le32(72, bytes_per_line_padded)  # bytesPerLine (padded)
        _le32(76, 0)             # reserved
        _le32(80, 0)             # renderingIntent
        # Rest of header stays zeroed

        # ── Raster data ──
        raster = bytearray()
        pixels = list(img.getdata())  # flat list of tuples

        for y in range(actual_height):
            row_start = y * actual_width
            row_bytes = bytearray(bytes_per_line_padded)
            for x in range(actual_width):
                pixel = pixels[row_start + x]
                if color_mode == "srgb_8":
                    row_bytes[x * 3] = pixel[0]     # R
                    row_bytes[x * 3 + 1] = pixel[1]  # G
                    row_bytes[x * 3 + 2] = pixel[2]  # B
                else:
                    row_bytes[x] = pixel  # single channel (L mode gives int)
            raster.extend(row_bytes)

        return bytes(header) + bytes(raster)

    except ImportError:
        _LOGGER.error(
            "Pillow (PIL) not available - cannot convert images to PWG-Raster. "
            "Install with: pip install Pillow"
        )
        return b""


class EpsonIppClient:

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

    def _send_request(
        self, path: str, body: bytes, timeout: int = 5
    ) -> bytes | None:
        """Send IPP request via HTTP and return response body.

        Args:
            path: URL path (e.g. "/ipp/print").
            body: Full IPP binary body (without HTTP headers).
            timeout: Socket timeout in seconds. Default 5s for queries,
                use 120s+ for large print jobs.
        """
        http_req = (
            f"POST {path} HTTP/1.1\r\n"
            f"Host: {self.host}:{self.port}\r\n"
            f"Content-Type: application/ipp\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Connection: close\r\n\r\n"
        ).encode() + body

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)

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
        _existing = {}  # track keys that have been seen (for 1setOf promotion)

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

            if value is None:
                continue

            # Handle 1setOf: if key already exists, promote to list
            if name in _existing:
                if not isinstance(attrs[name], list):
                    attrs[name] = [attrs[name]]
                attrs[name].append(value)
            else:
                attrs[name] = value
                _existing[name] = True

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

        # Text / Name / Keyword / URI / Charset / Language / MIME (UTF-8 string)
        if tag in (0x41, 0x42, 0x44, 0x45, 0x47, 0x48, 0x49):
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

    @staticmethod
    def _resolve_format_and_data(
        document_data: bytes, document_format: str
    ) -> tuple[bytes, str]:
        """Auto-convert image data to PWG-Raster if needed.

        Returns (converted_data, effective_format).
        """
        # Check file signatures for known image formats
        is_jpeg = document_data[:3] == b"\xff\xd8\xff"
        is_png = document_data[:8] == b"\x89PNG\r\n\x1a\n"
        is_bmp = document_data[:2] == b"BM"

        if document_format in ("image/jpeg", "image/png", "image/bmp") or (
            document_format == "application/octet-stream"
            and (is_jpeg or is_png or is_bmp)
        ):
            _LOGGER.info(
                "Auto-converting %s to image/pwg-raster",
                "JPEG" if is_jpeg else "PNG" if is_png else "BMP" if is_bmp else document_format
            )
            converted = _image_to_pwg_raster(document_data, 0, 0)
            if converted:
                return converted, "image/pwg-raster"
            _LOGGER.warning("PWG-Raster conversion failed, falling back to raw")

        return document_data, document_format

    def print_job(
        self,
        document_data: bytes,
        document_format: str = "application/octet-stream",
        job_name: str | None = None,
        user_name: str = "homeassistant",
    ) -> dict:
        """Submit a Print-Job request via IPP.

        Args:
            document_data: Raw file bytes to print.
                JPEG, PNG, and BMP images are auto-converted to PWG-Raster.
                Other formats (ESC/P commands, raw data) sent as-is.
            document_format: MIME type hint (e.g. "image/jpeg",
                "application/pdf", "image/pwg-raster").
                Auto-detected for JPEG/PNG/BMP; otherwise use this value.
            job_name: Optional human-readable job name.
            user_name: Requesting user name (default "homeassistant").

        Returns:
            dict with "job_id" (int) and "job_state" (str) on success,
            or empty dict on failure.
        """
        if not self._printer_uri:
            self.discover()
        if not self._printer_uri:
            return {}

        parts = []
        # IPP version 2.0
        parts.append(struct.pack(">H", 0x0200))
        # Operation: Print-Job (0x0002)
        parts.append(struct.pack(">H", 0x0002))
        # Request ID
        parts.append(struct.pack(">I", 1))

        # ── Operation attributes group ──
        parts.append(bytes([TAG_OPERATION]))

        # attributes-charset = utf-8
        name = b"attributes-charset"
        val = b"utf-8"
        parts.append(bytes([TAG_CHARSET]))
        parts.append(struct.pack(">H", len(name)))
        parts.append(name)
        parts.append(struct.pack(">H", len(val)))
        parts.append(val)

        # attributes-natural-language = en
        name = b"attributes-natural-language"
        val = b"en"
        parts.append(bytes([TAG_LANGUAGE]))
        parts.append(struct.pack(">H", len(name)))
        parts.append(name)
        parts.append(struct.pack(">H", len(val)))
        parts.append(val)

        # printer-uri
        name = b"printer-uri"
        val = self._printer_uri.encode("ascii")
        parts.append(bytes([TAG_URI]))
        parts.append(struct.pack(">H", len(name)))
        parts.append(name)
        parts.append(struct.pack(">H", len(val)))
        parts.append(val)

        # requesting-user-name
        name = b"requesting-user-name"
        val = user_name.encode("utf-8")
        parts.append(bytes([TAG_NAME_WITHOUT_LANG]))
        parts.append(struct.pack(">H", len(name)))
        parts.append(name)
        parts.append(struct.pack(">H", len(val)))
        parts.append(val)

        # job-name (optional)
        if job_name:
            name = b"job-name"
            val = job_name.encode("utf-8")
            parts.append(bytes([TAG_NAME_WITHOUT_LANG]))
            parts.append(struct.pack(">H", len(name)))
            parts.append(name)
            parts.append(struct.pack(">H", len(val)))
            parts.append(val)

        # Auto-convert images to PWG-Raster
        resolved_data, resolved_format = self._resolve_format_and_data(
            document_data, document_format
        )

        # document-format
        name = b"document-format"
        val = resolved_format.encode("ascii")
        parts.append(bytes([TAG_KEYWORD]))
        parts.append(struct.pack(">H", len(name)))
        parts.append(name)
        parts.append(struct.pack(">H", len(val)))
        parts.append(val)

        # End of attributes
        parts.append(bytes([TAG_END]))

        # ── Document data (appended after IPP header) ──
        ipp_header = b"".join(parts)
        body = ipp_header + resolved_data

        resp = self._send_request(
            self._path or "/ipp/print", body, timeout=120
        )

        # ── Parse response ──
        if not resp or len(resp) < 8:
            _LOGGER.error("IPP Print-Job: empty response")
            return {}

        status = struct.unpack(">H", resp[2:4])[0]
        if status > 0x00FF:
            _LOGGER.error("IPP Print-Job failed: status=0x%04X", status)
            return {}

        attrs, _ = self._parse_attributes(resp, 8)

        job_id = attrs.get("job-id", None)
        job_state = attrs.get("job-state", None)
        state_map = {
            3: "pending",
            4: "pending-held",
            5: "processing",
            6: "stopped",
            7: "cancelled",
            8: "aborted",
            9: "completed",
        }
        result = {"job_id": job_id}
        if job_state is not None:
            result["job_state"] = state_map.get(job_state, f"unknown ({job_state})")
        _LOGGER.info(
            "IPP Print-Job submitted: job_id=%s, state=%s, format=%s",
            result.get("job_id"),
            result.get("job_state", "?"),
            document_format,
        )
        return result

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

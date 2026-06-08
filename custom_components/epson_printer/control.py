"""Raw printer control via JetDirect port 9100."""

import logging
import socket
import os

from .const import ESC_COMMANDS

_LOGGER = logging.getLogger(__name__)


class EpsonPrinterControl:
    """Control Epson printer via raw TCP port 9100."""

    def __init__(self, host: str, port: int = 9100):
        self.host = host
        self.port = port

    def _send_raw(self, data: bytes) -> bool:
        """Send raw bytes to printer and return success."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect((self.host, self.port))
            sock.sendall(data)
            sock.close()
            _LOGGER.debug("Sent %d bytes to printer", len(data))
            return True
        except OSError as err:
            _LOGGER.error("Failed to send to printer: %s", err)
            return False

    def print_text(self, text: str) -> bool:
        """Print plain text.
        
        Sends text with a form feed to eject the page.
        """
        data = text.encode("utf-8", errors="replace")
        data += b"\r\n\x0c"  # CR+LF + Form Feed
        return self._send_raw(data)

    def print_file(self, filepath: str) -> bool:
        """Print a file (PDF, image, etc.).
        
        The printer must support the file format natively.
        For best results, use printer-native formats.
        """
        if not os.path.exists(filepath):
            _LOGGER.error("File not found: %s", filepath)
            return False

        try:
            with open(filepath, "rb") as f:
                data = f.read()
            return self._send_raw(data)
        except OSError as err:
            _LOGGER.error("Failed to read file: %s", err)
            return False

    def clean_printhead(self, deep: bool = False) -> bool:
        """Run print head cleaning."""
        cmd = ESC_COMMANDS["printhead_clean_deep" if deep else "printhead_clean"]
        return self._send_raw(cmd)

    def nozzle_check(self) -> bool:
        """Print nozzle check pattern."""
        return self._send_raw(ESC_COMMANDS["nozzle_check"])

    def initialize(self) -> bool:
        """Reset printer to initial state."""
        return self._send_raw(ESC_COMMANDS["initialize"])

    def send_esc_command(self, command: bytes) -> bool:
        """Send arbitrary ESC/P command."""
        return self._send_raw(command)

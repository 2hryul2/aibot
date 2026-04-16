"""Divoom Ditoo Pro connection module for Claude Code integration.

DitooPro uses command 0x8b (file transfer) for animations instead of 0x49.
The divoom16 file format is used: frames with 0xAA header + palette + pixels.
"""

import sys
import os
import json
import logging
import math
import itertools
import socket
import select
import time
from PIL import Image, ImageDraw, ImageFont

_config_cache = None

SCREEN_SIZE = 16
COMMANDS = {
    "set brightness": 0x74,
    "set datetime": 0x18,
    "animation": 0x8b,
    "set keyboard": 0x23,
}


def load_config():
    """Load config.json from the same directory as this script."""
    global _config_cache
    if _config_cache is not None:
        return _config_cache
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    with open(config_path, encoding="utf-8") as f:
        _config_cache = json.load(f)
    return _config_cache


class DitooProDevice:
    """Direct Bluetooth connection to a Divoom Ditoo Pro."""

    def __init__(self, mac, port=2):
        self.mac = mac
        self.port = port
        self.sock = None

    def connect(self):
        self.sock = socket.socket(
            socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM
        )
        self.sock.settimeout(10)
        self.sock.connect((self.mac, self.port))
        self.sock.setblocking(False)
        self.sock.settimeout(3)
        time.sleep(0.5)

    def disconnect(self):
        if self.sock:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            self.sock.close()
            self.sock = None

    def _make_packet(self, command, payload):
        """Build a Divoom protocol packet: 0x01 + length + cmd + payload + checksum + 0x02"""
        length = len(payload) + 3
        msg_payload = list(length.to_bytes(2, "little")) + [command] + payload
        checksum = sum(msg_payload) & 0xFFFF
        return bytes([0x01] + msg_payload + list(checksum.to_bytes(2, "little")) + [0x02])

    def _send(self, data):
        ready = select.select([], [self.sock], [], 1.0)
        if ready[1]:
            self.sock.send(data)
        time.sleep(0.05)

    def send_brightness(self, value):
        pkt = self._make_packet(COMMANDS["set brightness"], [value & 0xFF])
        self._send(pkt)

    def send_keyboard(self, value):
        """Control keyboard LED backlight.
        value=0: toggle on/off, value>=1: next effect, value<=-1: prev effect
        """
        if value == 0:
            arg = 0x02  # toggle
        elif value >= 1:
            arg = 0x01  # next effect
        else:
            arg = 0x00  # prev effect
        pkt = self._make_packet(COMMANDS["set keyboard"], [arg])
        self._send(pkt)

    def send_animation_file(self, file_data):
        """Send a divoom16 animation file via command 0x8b chunked transfer."""
        file_size = len(file_data)

        # StartSeeding: control_word=0, file_size(4 LE)
        start_payload = [0x00] + list(file_size.to_bytes(4, "little"))
        pkt = self._make_packet(COMMANDS["animation"], start_payload)
        self._send(pkt)
        time.sleep(0.2)

        # SendingData: control_word=1, file_size(4 LE), offset_id(2 LE), chunk data
        chunk_size = 256
        for i, offset in enumerate(range(0, file_size, chunk_size)):
            chunk = file_data[offset : offset + chunk_size]
            data_payload = (
                [0x01]
                + list(file_size.to_bytes(4, "little"))
                + list(i.to_bytes(2, "little"))
                + list(chunk)
            )
            pkt = self._make_packet(COMMANDS["animation"], data_payload)
            self._send(pkt)
            time.sleep(0.2)

    def show_text(self, text, font_path, color_fg=None, color_bg=None):
        """Render scrolling text and send as divoom16 animation."""
        if color_fg is None:
            color_fg = [255, 255, 255]
        if color_bg is None:
            color_bg = [0, 0, 0]

        file_data = render_text_to_divoom16(text, font_path, color_fg, color_bg)
        self.send_animation_file(file_data)


def _bits_per_pixel(color_count):
    if color_count <= 1:
        return 1
    return math.ceil(math.log2(color_count))


def _encode_pixels(pixels, palette_size):
    """Encode pixel indices into bit-packed bytes (little-endian bit order)."""
    bpp = _bits_per_pixel(palette_size)
    bit_string = ""
    for px in pixels:
        bits = format(px, "b").zfill(8)
        bit_string += bits[::-1][:bpp]

    result = []
    for i in range(0, len(bit_string), 8):
        chunk = bit_string[i : i + 8]
        if len(chunk) < 8:
            chunk = chunk.ljust(8, "0")
        result.append(int(chunk[::-1], 2))
    return bytes(result)


def render_text_to_divoom16(text, font_path, color_fg, color_bg):
    """Render scrolling text into divoom16 binary file format."""
    screen = SCREEN_SIZE
    frame_time = 50  # ms per frame

    # Load font
    fnt = ImageFont.load_default(screen)
    try:
        fnt = ImageFont.truetype(font_path, screen)
    except OSError:
        pass

    # Measure text width
    with Image.new("RGBA", (screen * 100, screen)) as tmp:
        drw = ImageDraw.Draw(tmp)
        drw.fontmode = "1"
        bbox = drw.textbbox((0, 0), text, font=fnt)
        text_width = bbox[2]

    # Create wide canvas with scrolling text
    # Text starts at x=0, with padding on right so last character isn't cut off
    img_width = text_width + screen * 2
    img = Image.new("RGBA", (img_width, screen), tuple(color_bg + [0xFF]))
    drw = ImageDraw.Draw(img)
    drw.fontmode = "1"
    drw.text((0, 0), text, font=fnt, fill=tuple(color_fg + [0xFF]))

    # Calculate scroll speed and frame count
    scroll_distance = text_width + screen
    text_speed = max(1, screen // 8)  # medium speed
    frame_count = scroll_distance // text_speed
    if frame_count > 60:
        text_speed = max(1, screen // 4)  # fast
        frame_time = 100
        frame_count = scroll_distance // text_speed
    if frame_count > 60:
        text_speed = max(1, screen // 2)  # very fast
        frame_time = 150
        frame_count = scroll_distance // text_speed
    if frame_count > 60:
        frame_count = 60

    # Build global palette from all frames
    all_colors = set()
    for offset in range(frame_count):
        for y in range(screen):
            for x in range(screen):
                r, g, b, a = img.getpixel((x + offset * text_speed, y))
                color = (r, g, b) if a > 32 else (0, 0, 0)
                all_colors.add(color)

    palette = sorted(all_colors)
    if len(palette) > 255:
        palette = palette[:255]
    color_to_idx = {c: i for i, c in enumerate(palette)}

    # Generate divoom16 file data
    file_data = bytearray()

    for frame_idx in range(frame_count):
        pixels = []
        for y in range(screen):
            for x in range(screen):
                r, g, b, a = img.getpixel((x + frame_idx * text_speed, y))
                color = (r, g, b) if a > 32 else (0, 0, 0)
                pixels.append(color_to_idx.get(color, 0))

        pixel_data = _encode_pixels(pixels, len(palette))

        # Frame header
        is_first = frame_idx == 0
        local_palette_size = len(palette) if is_first else 0
        frame_payload_len = 7 + local_palette_size * 3 + len(pixel_data)

        file_data.append(0xAA)  # magic
        file_data += frame_payload_len.to_bytes(2, "little")  # length
        file_data += frame_time.to_bytes(2, "little")  # duration
        file_data.append(0x00 if is_first else 0x01)  # reuse_palette
        file_data.append(local_palette_size & 0xFF)  # color_count

        if is_first:
            for r, g, b in palette:
                file_data += bytes([r, g, b])

        file_data += pixel_data

    img.close()
    return bytes(file_data)


def image_to_divoom16(image_path, frame_time=0):
    """Convert an image file (PNG/GIF/JPG/BMP) to divoom16 binary format.

    Supports single images and animated GIFs (multi-frame).
    Images are resized to 16x16 with NEAREST neighbor interpolation.
    """
    screen = SCREEN_SIZE

    picture_frames = []
    with Image.open(image_path) as img:
        try:
            while True:
                frame = Image.new("RGBA", img.size)
                frame.paste(img, (0, 0), img.convert("RGBA"))
                if frame.size != (screen, screen):
                    frame = frame.resize((screen, screen), Image.Resampling.NEAREST)
                duration = img.info.get("duration", frame_time) if frame_time == 0 else frame_time
                picture_frames.append((frame, duration))
                img.seek(img.tell() + 1)
        except EOFError:
            pass

    # Build global palette from all frames
    all_colors = set()
    for frame, _ in picture_frames:
        for y in range(screen):
            for x in range(screen):
                r, g, b, a = frame.getpixel((x, y))
                all_colors.add((r, g, b) if a > 32 else (0, 0, 0))

    palette = sorted(all_colors)
    if len(palette) > 255:
        palette = palette[:255]
    color_to_idx = {c: i for i, c in enumerate(palette)}

    # Generate divoom16 file data
    file_data = bytearray()
    for frame_idx, (frame, duration) in enumerate(picture_frames):
        pixels = []
        for y in range(screen):
            for x in range(screen):
                r, g, b, a = frame.getpixel((x, y))
                color = (r, g, b) if a > 32 else (0, 0, 0)
                pixels.append(color_to_idx.get(color, 0))

        pixel_data = _encode_pixels(pixels, len(palette))

        is_first = frame_idx == 0
        local_palette_size = len(palette) if is_first else 0
        frame_payload_len = 7 + local_palette_size * 3 + len(pixel_data)
        ft = duration if duration else 0

        file_data.append(0xAA)
        file_data += frame_payload_len.to_bytes(2, "little")
        file_data += ft.to_bytes(2, "little")
        file_data.append(0x00 if is_first else 0x01)
        file_data.append(local_palette_size & 0xFF)

        if is_first:
            for r, g, b in palette:
                file_data += bytes([r, g, b])

        file_data += pixel_data

    for frame, _ in picture_frames:
        frame.close()

    return bytes(file_data)


def get_device(config=None):
    """Create and connect a DitooProDevice."""
    if config is None:
        config = load_config()
    device = DitooProDevice(
        mac=config["mac"],
        port=config.get("port", 2),
    )
    device.connect()
    return device


def send_text(device, text, config=None):
    """Send scrolling text to the Ditoo Pro display."""
    if config is None:
        config = load_config()
    font_path = os.path.join(config["font_dir"], config["font"])
    max_len = config.get("max_text_length", 80)
    if len(text) > max_len:
        text = text[: max_len - 3] + "..."
    device.show_text(
        text,
        font_path,
        color_fg=config.get("color_fg", [255, 255, 255]),
        color_bg=config.get("color_bg", [0, 0, 0]),
    )


def send_brightness(device, value, config=None):
    """Set display brightness (0-100)."""
    device.send_brightness(value)


def send_clock(device, style=0):
    """Show clock on the Ditoo Pro display."""
    # 0x45 set view: channel=0, 24h=1, style, on=1, weather=0, temp=0, calendar=0, R, G, B
    device._send(device._make_packet(0x45, [0x00, 0x01, style, 0x01, 0x00, 0x00, 0x00, 0xFF, 0xFF, 0xFF]))


def send_image(device, image_path, config=None):
    """Send an image file to the Ditoo Pro display."""
    file_data = image_to_divoom16(image_path)
    device.send_animation_file(file_data)


def send_icon(device, icon_name, config=None):
    """Send a pre-made icon to the Ditoo Pro display."""
    if config is None:
        config = load_config()
    script_dir = os.path.dirname(os.path.abspath(__file__))
    icon_path = os.path.join(script_dir, f"{icon_name}.divoom16")
    with open(icon_path, "rb") as f:
        file_data = f.read()
    device.send_animation_file(file_data)

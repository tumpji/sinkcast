#!/usr/bin/env python3
"""Stream PC audio (PipeWire/PulseAudio) to a Chromecast / Google Cast device.

Usage:  sinkcast.py --list
        sinkcast.py [-d DEVICE] [-c flac|wav|mp3] [-p PORT] [--keep-default]
Needs:  pychromecast, pulseaudio-utils (pactl, parec), flac, lame
Stop:   Ctrl+C  (restores your original audio output)

DEVICE is a name (case/accent-insensitive, any unique part of it is enough),
a UUID or an IP address. It can be omitted when there is only one device.

Codecs:
  flac (default) - lossless, ~1 Mbit/s, best quality
  wav            - lossless uncompressed, ~1.5 Mbit/s, zero encoding CPU
  mp3            - 320 kbps, highest-quality LAME settings, lowest bandwidth
"""
import argparse
import ipaddress
import socket
import struct
import subprocess
import sys
import threading
import unicodedata
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pychromecast
from pychromecast.discovery import discover_chromecasts

SINK = "sinkcast"
RATE = 48000      # PipeWire's native rate -> no resampling anywhere
CHANNELS = 2
BITS = 16
DISCOVERY_TIMEOUT = 5

CODECS = {
    "flac": ("audio/flac", "stream.flac",
             ["flac", "--silent", "--force-raw-format", "--endian=little", "--sign=signed",
              f"--channels={CHANNELS}", f"--bps={BITS}", f"--sample-rate={RATE}",
              "-1", "--blocksize=1152", "--stdout", "-"]),
    "wav": ("audio/wav", "stream.wav", None),
    "mp3": ("audio/mpeg", "stream.mp3",
            ["lame", "-r", "-s", str(RATE / 1000), "--bitwidth", str(BITS), "--signed",
             "--little-endian", "-m", "s", "-b", "320", "--cbr", "-q", "0",
             "--lowpass", "20.5", "--quiet", "-", "-"]),
}


def parse_args():
    ap = argparse.ArgumentParser(description="Stream PC audio to a Chromecast / Google Cast device.")
    ap.add_argument("-d", "--device", help="device name, UUID or IP (default: the only device found)")
    ap.add_argument("-l", "--list", action="store_true", help="list devices on the network and exit")
    ap.add_argument("-c", "--codec", choices=CODECS, default="flac")
    ap.add_argument("-p", "--port", type=int, default=5000, help="HTTP port of the stream (default: 5000)")
    ap.add_argument("--keep-default", action="store_true",
                    help="don't switch the system default output to the cast sink")
    return ap.parse_args()


def wav_header():
    # "Infinite" WAV header for a live stream
    byte_rate = RATE * CHANNELS * BITS // 8
    size = 0xFFFFFFFF - 36
    return (b"RIFF" + struct.pack("<I", 0xFFFFFFFF) + b"WAVE"
            + b"fmt " + struct.pack("<IHHIIHH", 16, 1, CHANNELS, RATE, byte_rate,
                                    CHANNELS * BITS // 8, BITS)
            + b"data" + struct.pack("<I", size))


def local_ip(target):
    # Address of the interface that routes to the cast device (no packet is sent)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect((target, 8009))
        return s.getsockname()[0]


def pactl(*a):
    return subprocess.run(["pactl", *a], check=True, capture_output=True, text=True).stdout.strip()


def norm(s):
    # casefold + strip diacritics, so "kancelar" matches "Kancelář"
    return "".join(c for c in unicodedata.normalize("NFKD", s.casefold())
                   if not unicodedata.combining(c))


def print_devices(infos):
    if not infos:
        print("No Cast devices found.")
    for i in sorted(infos, key=lambda i: norm(i.friendly_name)):
        print(f"{i.friendly_name:<28} {i.model_name or '':<24} {i.host:<15} {i.uuid}")


def pick_device(infos, query):
    if query:
        q = norm(query)
        infos = ([i for i in infos if q in (str(i.uuid), i.host, norm(i.friendly_name))]
                 or [i for i in infos if q in norm(i.friendly_name)])
    if len(infos) == 1:
        return infos[0]
    if not infos:
        sys.exit(f"No device matching '{query}' found (try --list)." if query
                 else "No Cast devices found.")
    print_devices(infos)
    sys.exit("More than one device - pick one with -d NAME|UUID|IP.")


class StreamHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        mime, _, encoder = CODECS[self.server.codec]
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        parec = subprocess.Popen(
            ["parec", "-d", f"{SINK}.monitor", f"--format=s{BITS}le", f"--rate={RATE}",
             f"--channels={CHANNELS}", "--latency-msec=50"],
            stdout=subprocess.PIPE)
        procs = [parec]
        if encoder:
            enc = subprocess.Popen(encoder, stdin=parec.stdout, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL)
            parec.stdout.close()
            procs.append(enc)
            out = enc.stdout
        else:
            out = parec.stdout
            self.wfile.write(wav_header())
        try:
            while chunk := out.read(8192):
                self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            for p in procs:
                p.kill()

    def log_message(self, *a):
        pass


def stream(info, browser, args):
    mime, path, _ = CODECS[args.codec]
    name = info.friendly_name
    # Quotes would break pactl's module-argument parsing
    desc = f"Cast: {name}".replace('"', "").replace("'", "’")
    old_default = pactl("get-default-sink")
    module_id = pactl("load-module", "module-null-sink", f"sink_name={SINK}",
                      f"rate={RATE}", f"channels={CHANNELS}", "format=s16le",
                      f"sink_properties=\"device.description='{desc}'\"")
    server = cast = None
    try:
        if not args.keep_default:
            pactl("set-default-sink", SINK)
        server = ThreadingHTTPServer(("0.0.0.0", args.port), StreamHandler)
        server.codec = args.codec
        threading.Thread(target=server.serve_forever, daemon=True).start()

        print(f"Connecting to '{name}'...")
        cast = pychromecast.get_chromecast_from_cast_info(info, browser.zc)
        cast.wait()
        url = f"http://{local_ip(info.host)}:{args.port}/{path}"
        print(f"Streaming {args.codec.upper()} {RATE} Hz -> {name}  ({url})")
        mc = cast.media_controller
        mc.play_media(url, mime, title="PC audio", stream_type="LIVE")
        mc.block_until_active(timeout=15)
        print(f"Playing. Audio sent to the '{desc}' output goes to the device. Ctrl+C to stop.")
        threading.Event().wait()
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        try:
            if cast:
                cast.media_controller.stop()
                cast.quit_app()
        except Exception:
            pass
        if server:
            server.shutdown()
        if not args.keep_default:
            subprocess.run(["pactl", "set-default-sink", old_default])
        subprocess.run(["pactl", "unload-module", module_id])


def main():
    args = parse_args()
    # An IP is also probed directly, for networks where mDNS discovery doesn't work
    try:
        known_hosts = [str(ipaddress.ip_address(args.device or ""))]
    except ValueError:
        known_hosts = None
    print("Searching for Cast devices...")
    infos, browser = discover_chromecasts(timeout=DISCOVERY_TIMEOUT, known_hosts=known_hosts)
    try:
        if args.list:
            print_devices(infos)
        else:
            stream(pick_device(infos, args.device), browser, args)
    finally:
        browser.stop_discovery()


if __name__ == "__main__":
    main()

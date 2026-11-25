import os
import re
import sys
import time
import signal
import logging
import subprocess
from threading import Thread, Event
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from PIL import Image, ImageDraw, ImageFont

# =========================
# CONFIGURATION
# =========================

WIDTH = 854
HEIGHT = 480
FPS = 30
BITRATE = os.getenv("VIDEO_BITRATE", "600k").strip()
CYCLE_SECONDS = 24 * 60 * 60

RTMP_URL = os.getenv("YOUTUBE_RTMP_URL", "").strip().rstrip("/")
STREAM_KEY = os.getenv("YOUTUBE_STREAM_KEY", "").strip()

TITLE = os.getenv("COUNTDOWN_TITLE", "24/7 COUNTDOWN").strip()
SUBTITLE = os.getenv("COUNTDOWN_SUBTITLE", "LIVE ON YOUTUBE").strip()

PORT = int(os.getenv("PORT", "10000"))

stop_event = Event()
ffmpeg_process = None


class SecretFilter(logging.Filter):
    def __init__(self, secret: str):
        super().__init__()
        self.secret = secret

    def filter(self, record: logging.LogRecord) -> bool:
        msg = str(record.getMessage())
        if self.secret:
            msg = msg.replace(self.secret, "[REDACTED]")
        msg = re.sub(r"(rtmp://[^\s/]+/[^\s/]+/)([^\s]+)", r"\1[REDACTED]", msg)
        record.msg = msg
        record.args = ()
        return True


logger = logging.getLogger("countdown_streamer")
logger.setLevel(logging.INFO)
_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
_handler.addFilter(SecretFilter(STREAM_KEY))
logger.handlers.clear()
logger.addHandler(_handler)


# =========================
# HEALTH CHECK SERVER
# =========================

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/health"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok","service":"countdown-streamer"}')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


def start_health_server():
    server = ThreadingHTTPServer(("0.0.0.0", PORT), HealthHandler)
    logger.info("Health server listening on port %s", PORT)
    server.serve_forever()


# =========================
# FONTS
# =========================

def load_font(size, bold=False):
    path = (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    )
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


FONT_LIVE = load_font(18, bold=True)
FONT_TITLE = load_font(35, bold=True)
FONT_TIMER = load_font(78, bold=True)
FONT_SUBTITLE = load_font(21, bold=True)
FONT_NOTE = load_font(12, bold=False)


# =========================
# COUNTDOWN DESIGN
# =========================

def draw_center(draw, y, text, font, color):
    bounds = draw.textbbox((0, 0), text, font=font)
    text_width = bounds[2] - bounds[0]
    x = (WIDTH - text_width) // 2
    draw.text((x, y), text, font=font, fill=color)


def create_frame():
    now = int(time.time())
    remaining = CYCLE_SECONDS - (now % CYCLE_SECONDS)

    hours = remaining // 3600
    minutes = (remaining % 3600) // 60
    seconds = remaining % 60

    timer = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    image = Image.new("RGB", (WIDTH, HEIGHT), (8, 13, 27))
    draw = ImageDraw.Draw(image)

    # Outer border
    draw.rounded_rectangle(
        (22, 22, WIDTH - 22, HEIGHT - 22),
        radius=20,
        outline=(35, 57, 88),
        width=2,
    )

    # Live indicator
    draw.ellipse(
        (WIDTH // 2 - 48, 70, WIDTH // 2 - 34, 84),
        fill=(255, 65, 80),
    )
    draw_center(draw, 65, "LIVE", FONT_LIVE, (245, 248, 255))

    # Main title
    draw_center(draw, 140, TITLE, FONT_TITLE, (245, 248, 255))

    # Timer box
    draw.rounded_rectangle(
        (75, 215, WIDTH - 75, 340),
        radius=22,
        fill=(15, 27, 48),
        outline=(38, 65, 100),
        width=2,
    )
    draw_center(draw, 224, timer, FONT_TIMER, (75, 170, 255))

    # Subtitle
    draw_center(draw, 380, SUBTITLE, FONT_SUBTITLE, (160, 180, 210))
    draw_center(
        draw,
        420,
        "THE COUNTDOWN RESETS EVERY 24 HOURS",
        FONT_NOTE,
        (105, 125, 155),
    )

    return image


# =========================
# FFMPEG
# =========================

def build_ffmpeg_command():
    destination = f"{RTMP_URL}/{STREAM_KEY}"
    gop = FPS * 2

    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "error",

        "-f", "rawvideo",
        "-pix_fmt", "rgb24",
        "-s", f"{WIDTH}x{HEIGHT}",
        "-r", str(FPS),
        "-i", "pipe:0",

        "-f", "lavfi",
        "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",

        "-vf", "format=yuv420p",

        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-tune", "zerolatency",
        "-b:v", BITRATE,
        "-maxrate", BITRATE,
        "-bufsize", "1200k",
        "-g", str(gop),
        "-keyint_min", str(gop),
        "-sc_threshold", "0",

        "-c:a", "aac",
        "-b:a", "64k",
        "-ar", "44100",
        "-shortest",

        "-f", "flv",
        destination,
    ]


def log_ffmpeg_stderr(proc):
    if not proc.stderr:
        return
    try:
        for line in proc.stderr:
            cleaned = line.strip()
            if cleaned:
                logger.warning("FFmpeg: %s", cleaned)
    except Exception:
        pass


# =========================
# STREAMING LOOP
# =========================

def start_stream():
    global ffmpeg_process

    frame_bytes_len = WIDTH * HEIGHT * 3
    frame_interval = 1.0 / FPS

    while not stop_event.is_set():
        logger.info("Starting FFmpeg encoder...")
        proc = None

        try:
            proc = subprocess.Popen(
                build_ffmpeg_command(),
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=False,
            )
            ffmpeg_process = proc
            logger.info("FFmpeg process started.")

            err_thread = Thread(target=log_ffmpeg_stderr, args=(proc,), daemon=True)
            err_thread.start()

            cached_frame_bytes = None
            last_second = -1

            while not stop_event.is_set() and proc.poll() is None:
                now_sec = int(time.time())
                if now_sec != last_second:
                    cached_frame_bytes = create_frame().tobytes()
                    last_second = now_sec

                if len(cached_frame_bytes) != frame_bytes_len:
                    logger.error("Unexpected frame byte size.")
                    break

                proc.stdin.write(cached_frame_bytes)
                proc.stdin.flush()
                stop_event.wait(frame_interval)

        except (BrokenPipeError, OSError) as error:
            logger.error("FFmpeg stream error: %s", type(error).__name__)
        finally:
            ffmpeg_process = None
            if proc is not None:
                try:
                    if proc.stdin:
                        proc.stdin.close()
                except OSError:
                    pass
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()

        if not stop_event.is_set():
            logger.warning("Restarting FFmpeg in 5 seconds...")
            stop_event.wait(5)


# =========================
# SHUTDOWN
# =========================

def shutdown_handler(signum, frame):
    logger.info("Shutdown signal received.")
    stop_event.set()
    proc = ffmpeg_process
    if proc is not None and proc.poll() is None:
        try:
            proc.terminate()
        except OSError:
            pass


# =========================
# MAIN
# =========================

def main():
    if not RTMP_URL or not STREAM_KEY:
        logger.error("YouTube RTMP environment variables are missing.")
        sys.exit(1)

    signal.signal(signal.SIGTERM, shutdown_handler)
    signal.signal(signal.SIGINT, shutdown_handler)

    health_thread = Thread(target=start_health_server, daemon=True)
    health_thread.start()

    logger.info("Countdown service initialized.")
    logger.info("Resolution: %dx%d @ %dfps", WIDTH, HEIGHT, FPS)
    logger.info("Video bitrate: %s", BITRATE)

    start_stream()
    logger.info("Service stopped cleanly.")


if __name__ == "__main__":
    main()

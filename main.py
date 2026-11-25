
import os
import sys
import time
import signal
import logging
import subprocess
from threading import Thread
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from PIL import Image, ImageDraw, ImageFont

# =========================
# CONFIGURATION
# =========================

WIDTH = 854
HEIGHT = 480
FPS = 30
BITRATE = "600k"
CYCLE_SECONDS = 24 * 60 * 60

RTMP_URL = os.getenv("YOUTUBE_RTMP_URL", "").strip().rstrip("/")
STREAM_KEY = os.getenv("YOUTUBE_STREAM_KEY", "").strip()

TITLE = os.getenv("COUNTDOWN_TITLE", "24/7 COUNTDOWN")
SUBTITLE = os.getenv("COUNTDOWN_SUBTITLE", "LIVE ON YOUTUBE")

PORT = int(os.getenv("PORT", "10000"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

running = True
ffmpeg_process = None

# =========================
# HEALTH CHECK SERVER
# =========================

class HealthHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        if self.path in ("/", "/health"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()

            response = (
                b'{"status":"ok","service":"countdown-streamer"}'
            )
            self.wfile.write(response)

        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


def start_health_server():
    server = ThreadingHTTPServer(
        ("0.0.0.0", PORT),
        HealthHandler
    )

    logging.info("Health server listening on port %s", PORT)
    server.serve_forever()


# =========================
# FONTS
# =========================

def load_font(size, bold=False):

    if bold:
        path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    else:
        path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


# =========================
# COUNTDOWN DESIGN
# =========================

def draw_center(draw, y, text, font, color):

    bounds = draw.textbbox((0, 0), text, font=font)
    width = bounds[2] - bounds[0]

    x = (WIDTH - width) // 2

    draw.text(
        (x, y),
        text,
        font=font,
        fill=color
    )


def create_frame():

    # Countdown resets every 24 hours
    now = int(time.time())
    remaining = CYCLE_SECONDS - (now % CYCLE_SECONDS)

    hours = remaining // 3600
    minutes = (remaining % 3600) // 60
    seconds = remaining % 60

    timer = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    image = Image.new(
        "RGB",
        (WIDTH, HEIGHT),
        (8, 13, 27)
    )

    draw = ImageDraw.Draw(image)

    # Outer border
    draw.rounded_rectangle(
        (22, 22, WIDTH - 22, HEIGHT - 22),
        radius=20,
        outline=(35, 57, 88),
        width=2
    )

    # Live indicator
    draw.ellipse(
        (WIDTH // 2 - 48, 70, WIDTH // 2 - 34, 84),
        fill=(255, 65, 80)
    )

    draw_center(
        draw,
        65,
        "LIVE",
        load_font(18, True),
        (245, 248, 255)
    )

    # Main title
    draw_center(
        draw,
        140,
        TITLE,
        load_font(35, True),
        (245, 248, 255)
    )

    # Timer background
    draw.rounded_rectangle(
        (75, 215, WIDTH - 75, 340),
        radius=22,
        fill=(15, 27, 48),
        outline=(38, 65, 100),
        width=2
    )

    # Timer
    draw_center(
        draw,
        224,
        timer,
        load_font(78, True),
        (75, 170, 255)
    )

    # Subtitle
    draw_center(
        draw,
        380,
        SUBTITLE,
        load_font(21, True),
        (160, 180, 210)
    )

    draw_center(
        draw,
        420,
        "THE COUNTDOWN RESETS EVERY 24 HOURS",
        load_font(12),
        (105, 125, 155)
    )

    return image


# =========================
# FFMPEG
# =========================

def build_ffmpeg_command():

    destination = f"{RTMP_URL}/{STREAM_KEY}"

    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "warning",

        "-f", "rawvideo",
        "-pix_fmt", "rgb24",
        "-s", f"{WIDTH}x{HEIGHT}",
        "-framerate", "1",
        "-i", "pipe:0",

        "-an",

        "-vf", "fps=30,format=yuv420p",

        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-tune", "zerolatency",

        "-b:v", BITRATE,
        "-maxrate", BITRATE,
        "-bufsize", "1200k",

        "-g", "60",
        "-keyint_min", "60",
        "-sc_threshold", "0",

        "-f", "flv",
        destination
    ]


# =========================
# STREAMING LOOP
# =========================

def start_stream():

    global ffmpeg_process

    while running:

        logging.info("Starting FFmpeg encoder...")

        try:

            ffmpeg_process = subprocess.Popen(
                build_ffmpeg_command(),
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )

            logging.info("FFmpeg process started.")

            while running and ffmpeg_process.poll() is None:

                frame = create_frame()

                ffmpeg_process.stdin.write(
                    frame.tobytes()
                )

                ffmpeg_process.stdin.flush()

                time.sleep(1)

        except (BrokenPipeError, OSError) as error:

            logging.error(
                "FFmpeg connection error: %s",
                type(error).__name__
            )

        finally:

            if ffmpeg_process:

                try:
                    if ffmpeg_process.stdin:
                        ffmpeg_process.stdin.close()
                except OSError:
                    pass

                if ffmpeg_process.poll() is None:
                    ffmpeg_process.terminate()

                    try:
                        ffmpeg_process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        ffmpeg_process.kill()
                        ffmpeg_process.wait()

                ffmpeg_process = None

        if running:
            logging.warning("Restarting FFmpeg in 5 seconds...")
            time.sleep(5)


# =========================
# SHUTDOWN
# =========================

def shutdown_handler(signum, frame):

    global running

    logging.info("Shutdown signal received.")

    running = False

    if ffmpeg_process and ffmpeg_process.poll() is None:
        ffmpeg_process.terminate()


# =========================
# MAIN
# =========================

def main():

    if not RTMP_URL or not STREAM_KEY:
        logging.error("YouTube RTMP environment variables are missing.")
        sys.exit(1)

    signal.signal(signal.SIGTERM, shutdown_handler)
    signal.signal(signal.SIGINT, shutdown_handler)

    health_thread = Thread(
        target=start_health_server,
        daemon=True
    )

    health_thread.start()

    logging.info("Countdown service initialized.")
    logging.info("Resolution: 854x480")
    logging.info("Video bitrate: %s", BITRATE)

    start_stream()


if __name__ == "__main__":
    main()

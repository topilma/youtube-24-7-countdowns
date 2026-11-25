import os
import sys
import time
import signal
import subprocess
from datetime import datetime, timezone
from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 1280, 720
FPS_INPUT = 1
CYCLE_SECONDS = 24 * 60 * 60

RTMP_URL = os.environ.get("YOUTUBE_RTMP_URL", "").strip().rstrip("/")
STREAM_KEY = os.environ.get("YOUTUBE_STREAM_KEY", "").strip()
TITLE = os.environ.get("COUNTDOWN_TITLE", "24/7 COUNTDOWN")
SUBTITLE = os.environ.get("COUNTDOWN_SUBTITLE", "LIVE ON YOUTUBE")
BACKGROUND = (8, 13, 27)
WHITE = (245, 248, 255)
MUTED = (145, 163, 190)
ACCENT = (65, 164, 255)

running = True

def stop_handler(_signum, _frame):
    global running
    running = False

signal.signal(signal.SIGTERM, stop_handler)
signal.signal(signal.SIGINT, stop_handler)

def load_font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()

FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

def centered(draw, y, text, font, fill):
    box = draw.textbbox((0, 0), text, font=font)
    x = (WIDTH - (box[2] - box[0])) // 2
    draw.text((x, y), text, font=font, fill=fill)

def make_frame(seconds_left):
    image = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(image)

    # Subtle decorative frame and accents
    draw.rounded_rectangle((42, 42, WIDTH - 42, HEIGHT - 42), radius=28,
                           outline=(31, 48, 76), width=2)
    draw.rounded_rectangle((WIDTH // 2 - 115, 112, WIDTH // 2 + 115, 154),
                           radius=21, fill=(18, 45, 75))
    draw.ellipse((WIDTH // 2 - 91, 126, WIDTH // 2 - 77, 140), fill=(255, 62, 82))
    centered(draw, 118, "LIVE", load_font(FONT_BOLD, 20), WHITE)

    centered(draw, 205, TITLE, load_font(FONT_BOLD, 42), WHITE)

    hours = seconds_left // 3600
    minutes = (seconds_left % 3600) // 60
    seconds = seconds_left % 60
    timer = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    # Timer panel
    draw.rounded_rectangle((190, 300, WIDTH - 190, 465), radius=30,
                           fill=(14, 24, 43), outline=(37, 67, 103), width=2)
    centered(draw, 325, timer, load_font(FONT_BOLD, 112), ACCENT)

    centered(draw, 510, SUBTITLE, load_font(FONT_BOLD, 25), MUTED)
    centered(draw, 580, "The countdown resets every 24 hours",
             load_font(FONT_REG, 19), (104, 126, 157))
    return image

def build_ffmpeg_command():
    destination = f"{RTMP_URL}/{STREAM_KEY}"
    return [
        "ffmpeg", "-hide_banner", "-loglevel", "warning",
        "-re", "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{WIDTH}x{HEIGHT}", "-framerate", str(FPS_INPUT),
        "-i", "pipe:0",
        "-an", "-vf", "fps=30,scale=640:360,format=yuv420p",
        "-c:v", "libx264", "-preset", "ultrafast",
        "-tune", "zerolatency", "-b:v", "400k",
        "-maxrate", "400k", "-bufsize", "800k",
        "-g", "60", "-keyint_min", "60", "-sc_threshold", "0",
        "-f", "flv", destination
    ]

def main():
    if not RTMP_URL or not STREAM_KEY:
        print("ERROR: Set YOUTUBE_RTMP_URL and YOUTUBE_STREAM_KEY in Render Environment.", flush=True)
        sys.exit(1)

    print("Countdown streamer starting. Stream key is hidden from logs.", flush=True)
    while running:
        proc = subprocess.Popen(
            build_ffmpeg_command(),
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        print("FFmpeg encoder started.", flush=True)
        try:
            while running and proc.poll() is None:
                now = int(time.time())
                remaining = CYCLE_SECONDS - (now % CYCLE_SECONDS)
                frame = make_frame(remaining)
                proc.stdin.write(frame.tobytes())
                proc.stdin.flush()
                time.sleep(1)
        except (BrokenPipeError, OSError):
            print("Encoder connection ended; restarting in 5 seconds.", flush=True)
        finally:
            try:
                if proc.stdin:
                    proc.stdin.close()
            except OSError:
                pass
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
        if running:
            time.sleep(5)

    print("Countdown streamer stopped.", flush=True)

if __name__ == "__main__":
    main()

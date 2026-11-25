# YouTube 24/7 Countdown Stream

A lightweight FFmpeg + Python countdown generator for a YouTube RTMP livestream.

## Important
- This version streams 360p at about 400 kbps to reduce bandwidth costs. At a continuous 24/7 rate, expect roughly 130 GB of outbound traffic per 30-day month. Render's Hobby workspace includes 5 GB/month, then public outbound bandwidth is currently $0.15/GB; check the current billing page before deploying.
- A continuous 24/7 stream needs an always-on paid Render Background Worker. Render Free web services spin down after 15 minutes without inbound traffic and are not suitable for this job.
- Never commit your YouTube stream key to GitHub. Add it only in Render's Environment settings.
- YouTube may not archive a live stream that runs longer than 12 hours. Plan separate stream sessions if you need archives.

## GitHub
1. Create a new GitHub repository named `youtube-24-7-countdown`.
2. Upload all files in this folder to the repository root.
3. Do not upload a real `.env` file or your stream key.

## Render
1. Open https://dashboard.render.com/
2. Click **New** -> **Background Worker**.
3. Connect GitHub and select `youtube-24-7-countdown`.
4. Choose **Docker** runtime if prompted. Render should detect the Dockerfile.
5. Select a paid always-on instance (Starter is the lowest paid tier shown in Render pricing; verify the current price before confirming).
6. In **Environment**, add:
   - `YOUTUBE_RTMP_URL` = the Server URL shown by YouTube Studio (usually `rtmp://a.rtmp.youtube.com/live2`)
   - `YOUTUBE_STREAM_KEY` = the stream key from YouTube Studio
   - `COUNTDOWN_TITLE` = `24/7 COUNTDOWN`
   - `COUNTDOWN_SUBTITLE` = `LIVE ON YOUTUBE`
7. Save and deploy. Check **Logs** for `FFmpeg encoder started.`

## YouTube
1. Open YouTube Studio -> Go Live -> Stream.
2. Confirm the stream key is the one entered in Render.
3. Wait for YouTube's preview to appear.
4. Click **Go Live** in YouTube Studio if the stream is scheduled/manual. Do not share the stream key.

## Countdown behavior
The timer counts down to the next 24-hour boundary using UTC system time, then starts another 24-hour cycle. It is a looping countdown display, not a countdown to a custom event date.

## Troubleshooting
- `Set YOUTUBE_RTMP_URL and YOUTUBE_STREAM_KEY`: one or both Render environment variables are missing.
- No preview: check the RTMP URL and key, then inspect Render logs. Never paste the key into chat.
- Worker restarts: check Render instance events, usage, and billing. A restart interrupts the live stream; the process restarts FFmpeg automatically, but YouTube may require you to start a new live session.

import os
import re
import sys
import shutil
import subprocess
import textwrap
import pandas as pd
from PIL import Image, ImageDraw, ImageFont

# --- CONFIGURATION ---
CLIP_DURATION = 18  # Seconds per song clip
WIDTH, HEIGHT = 1920, 1080
VID_W, VID_H = 1310, 736
VID_X, VID_Y = (WIDTH - VID_W) // 2, (HEIGHT - VID_H) // 2  # (305, 172)

# If ffmpeg is not in your Windows PATH, paste the full path to ffmpeg.exe here:
# Example: FFMPEG_BIN = r"C:\ffmpeg\bin\ffmpeg.exe"
FFMPEG_BIN = shutil.which("ffmpeg") or "ffmpeg"

VOTERS = [
    "junoelise", "lernaeus", "icy", "canonbomb18", "uta",
    "krystallxe", "calin", "t3knyks", "strykex", "fakebrin",
    "son", "redgmd", "thicke", "emi", "victor", "sunny", "paato"
]

os.makedirs("temp_clips", exist_ok=True)
os.makedirs("temp_overlays", exist_ok=True)
os.makedirs("rendered_segments", exist_ok=True)

def check_dependencies():
    """Verify yt-dlp and ffmpeg are reachable before running all 109 songs."""
    try:
        subprocess.run([sys.executable, "-m", "yt_dlp", "--version"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    except Exception:
        print("ERROR: 'yt-dlp' is not installed in this Python environment.")
        print(f"Run: {sys.executable} -m pip install yt-dlp")
        sys.exit(1)

    if not shutil.which(FFMPEG_BIN) and not os.path.exists(FFMPEG_BIN):
        print("ERROR: 'ffmpeg' was not found on your Windows PATH or folder.")
        print("Install it in PowerShell with:  winget install Gyan.FFmpeg")
        print("Then restart your terminal/IDE, or put ffmpeg.exe in this script's folder.")
        sys.exit(1)

def get_font(size, bold=False):
    font_candidates = [
        "arialbd.ttf" if bold else "arial.ttf",
        "segoeuib.ttf" if bold else "segoeui.ttf",
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    ]
    for f in font_candidates:
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            continue
    return ImageFont.load_default()

def extract_yt_id(url):
    match = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})", str(url))
    return match.group(1) if match else None

def build_timestamp_lookup(responses_csv):
    if not os.path.exists(responses_csv):
        return {}
    df_resp = pd.read_csv(responses_csv)
    ts_lookup = {}
    for _, row in df_resp.iterrows():
        raw_ts = str(row.get("Timestamps go here", ""))
        matches = re.findall(r"([1-5])[:.]\s*(\d{1,2}:\d{2})", raw_ts)
        ts_dict = {int(k): v for k, v in matches}
        for i in range(1, 6):
            link = str(row.get(f"Song {i} link", "")).strip()
            yt_id = extract_yt_id(link)
            if yt_id and i in ts_dict:
                ts_lookup[yt_id] = ts_dict[i]
    return ts_lookup

def time_str_to_seconds(t_str):
    if not t_str:
        return 30
    parts = [int(p) for p in t_str.split(":")]
    return parts[0] * 60 + parts[1] if len(parts) == 2 else parts[0] * 3600 + parts[1] * 60 + parts[2]

def create_overlay(row, comments_row, output_path):
    img = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle([VID_X, VID_Y, VID_X + VID_W, VID_Y + VID_H], fill=(0, 0, 0, 0))

    rank = int(float(row["FINAL RANK"]))
    nominator = str(row["WHO ADDED"]).strip()
    avg_score = float(row["SONG AVG"])
    title = str(row.iloc[31]).strip() if len(row) > 31 and pd.notna(row.iloc[31]) else str(row["SONG"])
    artist = str(row.iloc[32]).strip() if len(row) > 32 and pd.notna(row.iloc[32]) else ""

    draw.text((VID_X + 10, 20), f"#{rank}", fill=(0, 255, 0, 255), font=get_font(90, bold=True))
    draw.text((VID_X + VID_W - 10, 50), f"nominated by {nominator}", fill=(255, 255, 255, 255), font=get_font(52), anchor="ra")
    draw.text((VID_X + 10, VID_Y + VID_H + 15), f"{avg_score:.2f}", fill=(230, 145, 56, 255), font=get_font(85))

    song_label = f'“{title}” by {artist}' if artist else title
    draw.text((WIDTH // 2 + 80, VID_Y + VID_H + 45), song_label, fill=(255, 255, 255, 255), font=get_font(44), anchor="mm")

    left_voters, right_voters = VOTERS[:9], VOTERS[9:]

    def get_grade_color(val_str):
        val_str = str(val_str).strip()
        if val_str in ["-", "", "nan", "forgot"]:
            return (91, 155, 213, 255), "-"
        try:
            v = float(val_str)
            if v == 10:
                return (0, 255, 0, 255), f"{v:g}"
            elif v < 5:
                return (224, 90, 71, 255), f"{v:g}"
            return (255, 255, 255, 255), f"{v:g}"
        except ValueError:
            return (91, 155, 213, 255), val_str

    y_start, y_step = 65, 108
    for idx, voter in enumerate(left_voters):
        y = y_start + idx * y_step
        color, g_text = get_grade_color(row.get(voter, "-"))
        draw.text((20, y), voter.capitalize(), fill=(255, 255, 255, 255), font=get_font(38), anchor="la")
        draw.text((VID_X - 15, y), g_text, fill=color, font=get_font(38), anchor="ra")

    for idx, voter in enumerate(right_voters):
        y = y_start + idx * y_step
        color, g_text = get_grade_color(row.get(voter, "-"))
        draw.text((VID_X + VID_W + 15, y), g_text, fill=color, font=get_font(38), anchor="la")
        draw.text((WIDTH - 20, y), voter.capitalize(), fill=(255, 255, 255, 255), font=get_font(38), anchor="ra")

    avatar_path = f"avatars/{nominator.lower()}.png"
    if os.path.exists(avatar_path):
        avatar = Image.open(avatar_path).convert("RGBA").resize((155, 155))
        img.paste(avatar, (VID_X + VID_W - 155, VID_Y), avatar)

    if comments_row is not None:
        active_comments = [
            (v, str(comments_row.get(v, "")).strip())
            for v in VOTERS
            if str(comments_row.get(v, "")).strip() and str(comments_row.get(v, "")).strip().lower() != "nan"
        ]
        left_y, right_y = VID_Y + 140, VID_Y + 180
        box_w = 260
        for i, (voter, c_text) in enumerate(active_comments):
            is_left = (i % 2 == 0)
            bx = VID_X + 10 if is_left else VID_X + VID_W - box_w - 10
            by = left_y if is_left else right_y

            wrapped = textwrap.fill(c_text, width=26)
            lines = wrapped.split("\n")
            body_h = max(65, len(lines) * 22 + 16)
            header_h = 30

            draw.rectangle([bx, by, bx + box_w, by + header_h], fill=(255, 255, 255, 255))
            draw.text((bx + box_w // 2, by + header_h // 2), voter, fill=(0, 0, 0, 255), font=get_font(20), anchor="mm")

            draw.rectangle([bx, by + header_h, bx + box_w, by + header_h + body_h], fill=(255, 255, 0, 255))
            draw.multiline_text(
                (bx + box_w // 2, by + header_h + body_h // 2),
                wrapped, fill=(0, 0, 0, 255), font=get_font(18), anchor="mm", align="center"
            )
            if is_left:
                left_y += header_h + body_h + 45
            else:
                right_y += header_h + body_h + 45

    img.save(output_path)

def download_and_render(rank, yt_url, start_sec, overlay_path):
    raw_clip = f"temp_clips/rank_{rank:03d}_raw.mp4"
    final_segment = f"rendered_segments/rank_{rank:03d}.mp4"

    if os.path.exists(final_segment):
        return final_segment

    end_sec = start_sec + CLIP_DURATION
    # Invoking yt_dlp via sys.executable avoids [WinError 2] if Scripts/ is not in PATH
    cmd_dl = [
        sys.executable, "-m", "yt_dlp",
        "--ffmpeg-location", FFMPEG_BIN,
        "-f", "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]",
        "--download-sections", f"*{start_sec}-{end_sec}",
        "--force-keyframes-at-cuts",
        "-o", raw_clip,
        yt_url
    ]
    subprocess.run(cmd_dl, check=True)

    filter_complex = (
        f"[0:v]scale={VID_W}:{VID_H}:force_original_aspect_ratio=decrease,"
        f"pad={VID_W}:{VID_H}:(ow-iw)/2:(oh-ih)/2,setsar=1[vid];"
        f"color=c=black:s={WIDTH}x{HEIGHT}:d={CLIP_DURATION}[bg];"
        f"[bg][vid]overlay={VID_X}:{VID_Y}:shortest=1[bg_vid];"
        f"[bg_vid][1:v]overlay=0:0[outv]"
    )
    cmd_ffmpeg = [
        FFMPEG_BIN, "-y",
        "-i", raw_clip,
        "-i", overlay_path,
        "-filter_complex", filter_complex,
        "-map", "[outv]", "-map", "0:a?",
        "-t", str(CLIP_DURATION),
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-r", "30",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        final_segment
    ]
    subprocess.run(cmd_ffmpeg, check=True)
    return final_segment

def main():
    check_dependencies()

    df_grades = pd.read_csv("grades.csv")
    df_comments = pd.read_csv("comments.csv")
    ts_lookup = build_timestamp_lookup("responses.csv")

    df_grades = df_grades[pd.to_numeric(df_grades["FINAL RANK"], errors="coerce").notna()].copy()
    df_grades["FINAL RANK"] = df_grades["FINAL RANK"].astype(int)
    df_grades = df_grades.sort_values(by="FINAL RANK", ascending=False)

    segment_files = []

    for _, row in df_grades.iterrows():
        rank = row["FINAL RANK"]
        song_name = str(row["SONG"]).strip()
        yt_url = str(row.iloc[30]).strip()

        c_match = df_comments[df_comments["SONG"].astype(str).str.strip() == song_name]
        comments_row = c_match.iloc[0] if not c_match.empty else None

        overlay_path = f"temp_overlays/rank_{rank:03d}.png"
        create_overlay(row, comments_row, overlay_path)

        yt_id = extract_yt_id(yt_url)
        start_sec = time_str_to_seconds(ts_lookup.get(yt_id, "0:30"))

        print(f"Processing #{rank}: {song_name} (Start: {start_sec}s)...")
        try:
            seg = download_and_render(rank, yt_url, start_sec, overlay_path)
            segment_files.append(seg)
        except Exception as e:
            print(f"Failed on #{rank} ({song_name}): {e}")

    if not segment_files:
        print("No segments were rendered. Check the errors above.")
        return

    with open("concat_list.txt", "w", encoding="utf-8") as f:
        for seg in segment_files:
            f.write(f"file '{seg}'\n")

    subprocess.run([
        FFMPEG_BIN, "-y", "-f", "concat", "-safe", "0",
        "-i", "concat_list.txt", "-c", "copy", "final_countdown_video.mp4"
    ], check=True)
    print("Done! Saved to final_countdown_video.mp4")

if __name__ == "__main__":
    main()
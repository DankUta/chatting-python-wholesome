import io
import math
import os
import random
import re
import shutil
import subprocess
import sys
import textwrap
import time
import urllib.request
import pandas as pd
from PIL import Image, ImageDraw, ImageFont

# --- CONFIGURATION ---
CLIP_DURATION = 18  # Seconds per song clip
DOWNLOAD_SLEEP_RANGE = (3.0, 6.0)  # Random delay (min, max) seconds between YouTube downloads
WIDTH, HEIGHT = 1920, 1080
VID_W, VID_H = 1310, 736
VID_X, VID_Y = (WIDTH - VID_W) // 2, (HEIGHT - VID_H) // 2  # (305, 172)

# If ffmpeg is not in your Windows PATH, paste the full path to ffmpeg.exe here:
# Example: FFMPEG_BIN = r"C:\ffmpeg\bin\ffmpeg.exe"
FFMPEG_BIN = shutil.which("ffmpeg") or "ffmpeg"

# --- AGE-RESTRICTED COOKIE SETTINGS ---
# 1. Preferred: Place exported 'cookies.txt' in the same folder as this script.
COOKIES_FILE = "cookies.txt"
# 2. Fallback: Browser name to pull cookies from if cookies.txt is not found.
#    Options: "firefox", "edge", "chrome", "brave", or None
#    (Note: Chrome/Edge/Brave must be completely closed in Task Manager for browser extraction to work on Windows)
COOKIES_BROWSER = "firefox"

os.makedirs("avatars", exist_ok=True)
os.makedirs("temp_clips", exist_ok=True)
os.makedirs("temp_overlays", exist_ok=True)
os.makedirs("rendered_segments", exist_ok=True)


def check_dependencies():
    """Verify yt-dlp and ffmpeg are reachable before running all songs."""
    try:
        subprocess.run(
            [sys.executable, "-m", "yt_dlp", "--version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
    except Exception:
        print("ERROR: 'yt-dlp' is not installed in this Python environment.")
        print(f"Run: {sys.executable} -m pip install yt-dlp")
        sys.exit(1)

    if not shutil.which(FFMPEG_BIN) and not os.path.exists(FFMPEG_BIN):
        print("ERROR: 'ffmpeg' was not found on your Windows PATH or folder.")
        print("Install it in PowerShell with:  winget install Gyan.FFmpeg")
        print("Then restart your terminal/IDE, or put ffmpeg.exe in this script's folder.")
        sys.exit(1)


def is_valid_file(filepath, min_bytes=10240):
    """Ensure a file exists and isn't a 0-byte or corrupted stub from a power outage."""
    return os.path.exists(filepath) and os.path.getsize(filepath) > min_bytes


def get_font(size, bold=False):
    font_candidates = [
        "arialbd.ttf" if bold else "arial.ttf",
        "segoeuib.ttf" if bold else "segoeui.ttf",
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
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


def extract_drive_id(url):
    match = re.search(r"(?:id=|/d/)([A-Za-z0-9_-]{20,})", str(url))
    return match.group(1) if match else None


def get_cookie_args():
    """Return yt-dlp arguments for authenticated age-restricted downloads."""
    if os.path.exists(COOKIES_FILE) and os.path.getsize(COOKIES_FILE) > 0:
        return ["--cookies", COOKIES_FILE]
    if COOKIES_BROWSER:
        return ["--cookies-from-browser", COOKIES_BROWSER]
    return []


# --- 1. DYNAMIC VOTERS FROM CSV ---
def get_active_voters(df_grades):
    """
    Dynamically extract participant columns between 'WHO ADDED' and 'SONG AVG'.
    Only include participants who have at least 1 numeric grade in the sheet.
    """
    cols = list(df_grades.columns)
    if "WHO ADDED" in cols and "SONG AVG" in cols:
        start_idx = cols.index("WHO ADDED") + 1
        end_idx = cols.index("SONG AVG")
        candidate_cols = cols[start_idx:end_idx]
    else:
        candidate_cols = cols[2:19]

    active_voters = []
    for col in candidate_cols:
        if str(col).startswith("Unnamed:"):
            continue
        has_grades = pd.to_numeric(df_grades[col], errors="coerce").notna().any()
        if has_grades:
            active_voters.append(col)

    print(f"Detected {len(active_voters)} active graders from CSV: {', '.join(active_voters)}")
    return active_voters


# --- 2. AUTOMATED PROFILE PICTURE DOWNLOADER & TIMESTAMP PARSER ---
def sync_avatars_and_timestamps(responses_csv, df_grades):
    """
    Parses timestamps and automatically downloads profile pictures from Google Drive links
    in responses.csv, mapping form usernames to grades.csv usernames.
    """
    if not os.path.exists(responses_csv):
        return {}

    df_resp = pd.read_csv(responses_csv)
    ts_lookup = {}

    # Map YouTube ID -> WHO ADDED in grades.csv so nicknames (like 'suwunny' -> 'sunny') match automatically
    yt_to_nominator = {}
    for _, row in df_grades.iterrows():
        yt_id = extract_yt_id(row.iloc[30])
        nom = str(row.get("WHO ADDED", "")).strip().lower()
        if yt_id and nom:
            yt_to_nominator[yt_id] = nom

    for _, row in df_resp.iterrows():
        raw_name = str(row.get("Name", "")).strip().lower()
        raw_ts = str(row.get("Timestamps go here", ""))
        matches = re.findall(r"([1-5])[:.]\s*(\d{1,2}:\d{2})", raw_ts)
        ts_dict = {int(k): v for k, v in matches}

        matched_nominator = None
        for i in range(1, 6):
            link = str(row.get(f"Song {i} link", "")).strip()
            yt_id = extract_yt_id(link)
            if yt_id:
                if i in ts_dict:
                    ts_lookup[yt_id] = ts_dict[i]
                if yt_id in yt_to_nominator:
                    matched_nominator = yt_to_nominator[yt_id]

        # Download avatar if a Drive link is provided
        pic_url = str(row.get("Profile pic", "")).strip()
        drive_id = extract_drive_id(pic_url)
        if drive_id:
            target_names = {raw_name}
            if matched_nominator:
                target_names.add(matched_nominator)

            for name in target_names:
                if not name or name == "nan":
                    continue
                avatar_path = f"avatars/{name}.png"
                if not is_valid_file(avatar_path, min_bytes=512):
                    dl_url = f"https://drive.google.com/uc?export=download&id={drive_id}"
                    try:
                        print(f"Downloading profile picture for '{name}'...")
                        req = urllib.request.Request(dl_url, headers={"User-Agent": "Mozilla/5.0"})
                        with urllib.request.urlopen(req, timeout=15) as resp:
                            img_bytes = resp.read()
                        img = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
                        img.save(avatar_path, "PNG")
                    except Exception as e:
                        print(f"  Warning: Could not download avatar for '{name}': {e}")

    return ts_lookup


def time_str_to_seconds(t_str):
    if not t_str:
        return 30
    parts = [int(p) for p in t_str.split(":")]
    return parts[0] * 60 + parts[1] if len(parts) == 2 else parts[0] * 3600 + parts[1] * 60 + parts[2]


# --- 3. GENERATE OVERLAY PNG (1920x1080) ---
def create_overlay(row, comments_row, voters, output_path):
    img = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle([VID_X, VID_Y, VID_X + VID_W, VID_Y + VID_H], fill=(0, 0, 0, 0))

    rank = int(float(row["FINAL RANK"]))
    nominator = str(row["WHO ADDED"]).strip()
    avg_score = float(row["SONG AVG"])
    title = str(row.iloc[31]).strip() if len(row) > 31 and pd.notna(row.iloc[31]) else str(row["SONG"])
    artist = str(row.iloc[32]).strip() if len(row) > 32 and pd.notna(row.iloc[32]) else ""

    draw.text((VID_X + 10, 20), f"#{rank}", fill=(0, 255, 0, 255), font=get_font(90, bold=True))
    draw.text(
        (VID_X + VID_W - 10, 50),
        f"nominated by {nominator}",
        fill=(255, 255, 255, 255),
        font=get_font(52),
        anchor="ra",
    )
    draw.text((VID_X + 10, VID_Y + VID_H + 15), f"{avg_score:.2f}", fill=(230, 145, 56, 255), font=get_font(85))

    song_label = f'“{title}” by {artist}' if artist else title
    draw.text(
        (WIDTH // 2 + 80, VID_Y + VID_H + 45),
        song_label,
        fill=(255, 255, 255, 255),
        font=get_font(44),
        anchor="mm",
    )

    # Split active voters evenly between Left and Right columns
    split_idx = math.ceil(len(voters) / 2)
    left_voters, right_voters = voters[:split_idx], voters[split_idx:]

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

    y_start = 65
    max_per_side = max(len(left_voters), len(right_voters), 1)
    y_step = min(108, (HEIGHT - 120) // max_per_side)

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
    if is_valid_file(avatar_path, min_bytes=512):
        avatar = Image.open(avatar_path).convert("RGBA").resize((155, 155))
        img.paste(avatar, (VID_X + VID_W - 155, VID_Y), avatar)

    if comments_row is not None:
        comment_cols = [
            c for c in comments_row.index
            if c not in ["SONG", "COUNT", "rank", "Viv"] and not str(c).startswith("Unnamed:")
        ]
        active_comments = [
            (v, str(comments_row.get(v, "")).strip())
            for v in comment_cols
            if pd.notna(comments_row.get(v))
            and str(comments_row.get(v, "")).strip()
            and str(comments_row.get(v, "")).strip().lower() != "nan"
        ]
        left_y, right_y = VID_Y + 140, VID_Y + 180
        box_w = 260
        for i, (voter, c_text) in enumerate(active_comments):
            is_left = i % 2 == 0
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
                wrapped,
                fill=(0, 0, 0, 255),
                font=get_font(18),
                anchor="mm",
                align="center",
            )
            if is_left:
                left_y += header_h + body_h + 45
            else:
                right_y += header_h + body_h + 45

    img.save(output_path)


# --- 4. ATOMIC DOWNLOAD & RENDER (POWER-OUTAGE & AGE-RESTRICTION SAFE) ---
def download_and_render(rank, yt_url, start_sec, overlay_path):
    raw_clip = f"temp_clips/rank_{rank:03d}_raw.mp4"
    raw_clip_part = f"temp_clips/rank_{rank:03d}_raw.part.mp4"

    final_segment = f"rendered_segments/rank_{rank:03d}.mp4"
    final_segment_part = f"rendered_segments/rank_{rank:03d}.part.mp4"

    # 1. If final segment already exists and is non-corrupted, skip immediately
    if is_valid_file(final_segment):
        print(f"  -> Skipping #{rank} (already rendered).")
        return final_segment

    # 2. Download raw clip if not already cached
    if not is_valid_file(raw_clip):
        if os.path.exists(raw_clip_part):
            os.remove(raw_clip_part)

        end_sec = start_sec + CLIP_DURATION
        base_cmd_dl = [
            sys.executable, "-m", "yt_dlp",
            "--no-playlist",
            "--ffmpeg-location", FFMPEG_BIN,
            "--sleep-requests", "1",
            "-f", "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]",
            "--download-sections", f"*{start_sec}-{end_sec}",
            "--force-keyframes-at-cuts",
            "-o", raw_clip_part,
            yt_url,
        ]

        try:
            # Attempt 1: Standard anonymous download (protects your account from rate-limits)
            subprocess.run(base_cmd_dl, check=True)
        except subprocess.CalledProcessError:
            cookie_args = get_cookie_args()
            if not cookie_args:
                raise RuntimeError(
                    f"Download failed for #{rank} (possibly age-restricted), and no cookies.txt or browser configured."
                )
            print(
                f"  -> Standard download failed for #{rank} (likely age-restricted). "
                f"Retrying with cookies ({' '.join(cookie_args)})..."
            )
            if os.path.exists(raw_clip_part):
                os.remove(raw_clip_part)
            # Attempt 2: Retry with cookies inserted right after 'yt_dlp'
            auth_cmd_dl = base_cmd_dl[:3] + cookie_args + base_cmd_dl[3:]
            subprocess.run(auth_cmd_dl, check=True)

        if is_valid_file(raw_clip_part):
            os.replace(raw_clip_part, raw_clip)
        else:
            raise RuntimeError(f"Downloaded clip for #{rank} is missing or empty.")

        # Polite sleep after an actual YouTube download to avoid rate-limiting
        delay = random.uniform(*DOWNLOAD_SLEEP_RANGE)
        print(f"  -> Waiting {delay:.1f}s to avoid YouTube rate-limiting...")
        time.sleep(delay)

    # 3. Render final composite segment via atomic .part.mp4 file
    if os.path.exists(final_segment_part):
        os.remove(final_segment_part)

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
        final_segment_part,
    ]
    subprocess.run(cmd_ffmpeg, check=True)

    # Only rename to rank_XXX.mp4 once FFmpeg finishes 100% cleanly
    if is_valid_file(final_segment_part):
        os.replace(final_segment_part, final_segment)
    else:
        raise RuntimeError(f"Rendered segment for #{rank} is empty or corrupted.")

    return final_segment


def main():
    check_dependencies()

    df_grades = pd.read_csv("grades.csv")
    df_comments = pd.read_csv("comments.csv")

    # Dynamically extract voters who have actual grades in grades.csv
    voters = get_active_voters(df_grades)

    # Parse timestamps and automatically download profile pictures from responses.csv
    ts_lookup = sync_avatars_and_timestamps("responses.csv", df_grades)

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
        if not is_valid_file(overlay_path, min_bytes=1024):
            create_overlay(row, comments_row, voters, overlay_path)

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

    subprocess.run(
        [
            FFMPEG_BIN, "-y", "-f", "concat", "-safe", "0",
            "-i", "concat_list.txt", "-c", "copy", "final_countdown_video.mp4",
        ],
        check=True,
    )
    print("Done! Saved to final_countdown_video.mp4")


if __name__ == "__main__":
    main()
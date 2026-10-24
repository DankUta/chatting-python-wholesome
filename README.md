# Chatting 🎶

The whole admin side of **Chatting**, our song contest: everyone submits 5 songs through
the Google Form, rates everyone's songs anonymously, and the admin turns it all into a
master spreadsheet and a 1080p countdown video.

```
Google Form responses ──► chatting sheet ──► rating sheet (anonymous, shuffled)
                                                  │ everyone fills in a copy
                                                  ▼
          filled-in rating sheets ──► chatting compile ──► master.xlsx (ranking + comments)
                                                                │ fix anything by hand
                                                                ▼
                                       chatting preview / render ──► countdown video
```

What the video shows for every song, from last place to #1:

- the rank and the average rating (your rating of your **own** song doesn't count — it shows as `-`)
- who submitted it ("nominated by …") and their profile picture
- every voter's rating, split equally between the left and right side
- **all** the comments for that song (if there are too many to fit, they're shown in
  pages that change during the clip)
- 15 seconds of the song's video, starting at the submitted timestamp, with a short audio
  fade in/out and the loudness evened out between songs

---

## 1. Install (once)

1. **Python 3.9+** — [python.org](https://www.python.org/downloads/) (on Windows tick
   **"Add Python to PATH"**).
2. **FFmpeg**
   * Windows: `winget install Gyan.FFmpeg` (then restart the terminal), or put `ffmpeg.exe`
     and `ffprobe.exe` in this folder
   * macOS: `brew install ffmpeg`
   * Linux: `sudo apt install ffmpeg`
3. **Python packages** — from this folder:
   ```bash
   pip install -r requirements.txt
   ```
   (Optional: `pip install pillow-heif` if people upload iPhone `.heic` pictures.)

Check everything is found:

```bash
python -m chatting check
```

## 2. Start an edition

```bash
python -m chatting init editions/2026-autumn --edition "Edition 6"
cd editions/2026-autumn
```

This makes a `chatting.toml` (all the settings, with comments) and the folders
`data/ratings`, `data/avatars` and `data/clips`. Every command below is run from this
folder (or from anywhere with `-c path/to/chatting.toml`).

## 3. Submissions → rating sheet

In the Google Form go to **Responses → Link to Sheets**. Then either

* share that sheet as **Anyone with the link → Viewer** and paste its link into
  `chatting.toml` as `responses = "https://docs.google.com/spreadsheets/d/…"`, or
* download it (**File → Download → .csv**) to `data/responses.csv`.

The form's questions are detected automatically (name, "Song 1 title/artist/link" …,
profile picture, timestamps). If one isn't, set it under `[columns]` in `chatting.toml`.

```bash
python -m chatting sheet
```

This writes to `output/`:

| File | What it is |
| --- | --- |
| `rating_sheet.xlsx` / `.csv` | The anonymous sheet: `#`, `Song`, `Link`, `Rating`, `Comments`, songs in shuffled order. Upload it to Google Drive and give everyone their own copy (tip: a link ending in `/copy` instead of `/edit` makes Google ask "Make a copy?"). |
| `songs.csv` | **Private** — which song is whose. It pins the song numbers, so keep it until the video is done. |

It also lists songs without a timestamp; those start at `default_start` (0:30) unless you
fix them later in the master sheet.

The timestamps field understands most ways people write it: `1: 0:45, 2: 1:20`,
`1. 0:45` on separate lines, `song 1 - 1:15`, `1) 1:05`, `1: 45s`, `1: 1m20s`, a plain list
`0:45, 1:20, …` in song order, and a `?t=95` in the YouTube link itself.

## 4. Ratings → master sheet

When the sheets come back, put each one in `data/ratings/`, **named after the voter**
(`bianca.xlsx`, `calin.csv`, …; `.xlsx`, `.csv` and `.ods` all work). Voters who'd rather
share a link go in `chatting.toml`:

```toml
[input.rating_links]
Bianca = "https://docs.google.com/spreadsheets/d/…/edit"
```

Ratings like `6.78`, `6,78`, `7/10` and `8 (lol)` are all read; blank, `-` or `forgot` means no
rating. Anything else (or outside 0–10) is reported so you can fix it. If someone sorted
or reordered their sheet, songs are still matched by number and name.

If the same person is spelled differently in different places (`Călin` in the form,
`calin.xlsx`, …), accents and capitals are already ignored; anything else goes in
`[people]`:

```toml
[people]
"Călin" = ["calin_b", "CB"]
```

```bash
python -m chatting compile
```

`output/master.xlsx` has four tabs:

* **Ranking** — rank, average, number of votes, song, artist, who submitted it, link,
  clip start, then one column per voter (`own` = their own song, not counted)
* **Comments** — every comment, one column per voter
* **Submitters** — how each person's songs did on average
* **Voters** — how many ratings each voter gave, their average, how many 10s

Fix whatever you want **in the master sheet** (a typo, a rating, a start time, the order
of the voter columns = the order on screen). The video is made from the master sheet and
the averages and ranks are recalculated from it, so your edits count. Running `compile`
again rebuilds it from the rating sheets (the previous one is kept as
`master.backup.xlsx`).

Tied averages share a rank.

## 5. Profile pictures

The form's picture upload is used automatically if those Drive files are shared
(**Anyone with the link**). Otherwise put the pictures in `data/avatars/` named after the
person (`bianca.jpg`). Downloading the form's upload folder from Drive works too: Google
names those files `photo - Bianca.jpg`, which is recognised. Anyone without a picture gets
a coloured square with their initials.

## 6. Preview, then render

```bash
python -m chatting preview            # PNGs of every screen in output/preview/
python -m chatting preview --ranks 1-3
python -m chatting render             # the full video
python -m chatting render --ranks 1-5 # a quick test with a few songs
```

The video goes to `output/<title> <edition>.mp4`. Clips are downloaded one by one with a
pause in between so YouTube doesn't block you, and everything is cached in `work/`: if a
render stops or one song fails, run the same command again and only what's missing is
done.

If a song's video won't download:

1. update yt-dlp: `pip install -U yt-dlp`
2. if YouTube asks to sign in, add `yt_dlp_args = ["--cookies-from-browser", "firefox"]`
   (or `"chrome"`, `"edge"`) under `[video]`
3. or download the video yourself and save it as `data/clips/<song #>.mp4` (the `#` from
   the rating sheet); it's used instead, cut at the song's start time — or from the
   beginning if the file is too short for that, so an already-cut 15 s clip works too

Songs whose clip couldn't be found still get their screen (with a black box) and are listed
at the end, so the countdown is never missing a place.

## Settings

Everything lives in `chatting.toml`; `python -m chatting init` writes one with comments.
The most useful ones:

| Setting | Default | |
| --- | --- | --- |
| `[video] clip_seconds` | `15` | length of each song's clip |
| `[video] default_start` | `"0:30"` | start for songs without a timestamp |
| `[video] audio_fade` | `1.0` | seconds of fade in/out (0 = off) |
| `[video] normalize_audio` | `true` | same loudness for every song |
| `[video] sleep_between_downloads` | `3` | seconds between YouTube downloads |
| `[voting] exclude_own` | `true` | your own song's rating doesn't count |
| `[voting] voter_order` | `[]` | side-panel order (default A–Z, or the master sheet's column order) |
| `[fonts] regular / bold / emoji` | auto | font files, if the defaults look wrong |

## Try it with the demo

`examples/demo` is a made-up edition (5 people, 25 songs, 6 voters):

```bash
python -m chatting -c examples/demo/chatting.toml compile
python -m chatting -c examples/demo/chatting.toml preview --offline
```

## Development

```bash
pip install -r requirements.txt pytest
python -m pytest
```

The code is in `chatting/`: `submissions.py` (form), `ratings.py` (rating sheets),
`master.py` (averages, ranks, master sheet), `overlay.py` + `text.py` (the on-screen
graphics), `clips.py` (yt-dlp) and `render.py` (ffmpeg).

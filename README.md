# viral-clipper

A local MCP server for Claude Code that turns a long video (YouTube URL or local file) into the 10
most viral-worthy vertical clips, each with burned-in word-by-word captions, an opening hook, normalized
audio, and per-platform titles, descriptions and hashtags.

Everything that touches video runs on your machine: `yt-dlp`, Whisper (`mlx-whisper` on Apple Silicon,
`faster-whisper` elsewhere), PySceneDetect, librosa, OpenCV and FFmpeg. Claude is only used, optionally,
to polish titles and hooks.

```
clip_video("https://www.youtube.com/watch?v=...", niche="mrbeast")
  → ~/Desktop/viral-clipper/<video-title>/clip_01.mp4 … clip_10.mp4
    + thumbnails/, captions/*.srt, clips.json, clips.csv
```

## Requirements

- **FFmpeg** (`ffmpeg` and `ffprobe` on PATH). macOS: `brew install ffmpeg`. Windows: `winget install Gyan.FFmpeg`.
  No libass needed: captions are rendered as PNG overlays.
- **uv** (https://docs.astral.sh/uv/). It installs Python 3.12 and every dependency for you.
- ~3 GB of disk for Whisper models on first run (`large-v3-turbo`), less if you pick `small`.
- GPU is optional. Apple Silicon uses the GPU through MLX; NVIDIA needs CUDA 12 + cuDNN 9 for
  faster-whisper (see *Windows / NVIDIA* below); otherwise it falls back to CPU with the `small` model.

## Install

```bash
git clone <this repo> viral-clipper
cd viral-clipper
uv sync --extra mlx        # macOS Apple Silicon (mlx-whisper)
# uv sync                  # Windows / Linux / Intel Mac (faster-whisper)
uv run pytest              # ~20 s, synthesizes its own test video
```

## Register in Claude Code

```bash
claude mcp add --scope user viral-clipper -- uv --directory /ABSOLUTE/PATH/TO/viral-clipper run viral-clipper
```

On this machine that is:

```bash
claude mcp add --scope user viral-clipper -- uv --directory /Users/yogesh/Documents/Project/viral-clipper run viral-clipper
```

Windows (PowerShell):

```powershell
claude mcp add --scope user viral-clipper -- uv --directory C:\path\to\viral-clipper run viral-clipper
```

Check with `claude mcp list`, then in a Claude Code session:

> Use viral-clipper to analyze https://www.youtube.com/watch?v=_c2e1NcI3Sc, show me the top moments for
> the mrbeast niche, then cut 10 clips.

## Tools

| Tool | Purpose |
|---|---|
| `clip_video(source, niche="generic", num_clips=10, min_len=30, max_len=70, platforms=None, output_dir=None)` | The whole pipeline. Returns every clip with path, score, reasons, hook and per-platform metadata. |
| `analyze_video(source, force=False)` | Transcript sentences with timestamps, scene cuts, audio peaks, 1 Hz energy and motion curves. Cached. |
| `score_moments(source, niche, num_clips, min_len, max_len)` | Ranked moments with a 0-100 score, per-signal contributions and plain-language reasons. Renders nothing. |
| `generate_metadata(clip_path, platform, niche=None)` | Title, description, hashtags and hook for one existing clip and platform. |
| `set_clip_metadata(clip_path, platform, title, description, hashtags, hook="")` | Save your own copy into `clips.json` / `clips.csv`. |
| `list_outputs(output_dir=None)` | Every processed video and its saved clips. |

`source` is a YouTube URL (anything yt-dlp supports) or a path to an `.mp4/.mov/.mkv/.webm` file.
`niche` is a file in `profiles/`: `gta6`, `mrbeast`, `generic`. Platforms: `youtube_shorts`, `tiktok`,
`instagram_reels`, `facebook_reels`.

### CLI (same pipeline, handy for testing)

```bash
uv run viral-clipper clip "https://www.youtube.com/watch?v=..." --niche gta6 --num-clips 10
uv run viral-clipper score ./gameplay.mp4 --niche gta6
uv run viral-clipper analyze ./gameplay.mp4
uv run viral-clipper list
uv run viral-clipper              # = serve (MCP over stdio)
```

## Output

```
~/Desktop/viral-clipper/<video-title>/
├── source.mp4            downloaded source (local files are used in place)
├── analysis.json         cached transcript + signal curves
├── clip_01.mp4 … clip_10.mp4   1080x1920, 30 fps, H.264 + AAC 48 kHz, -14 LUFS
├── thumbnails/clip_NN.jpg      frame at the payoff moment
├── captions/clip_NN.srt|.ass   editable captions
├── clips.json            full records: score, timestamps, reasons, features, hook, metadata per platform
└── clips.csv             one row per clip per platform: title, hashtags, description, hook
```

## How moments are chosen

1. **Analyze**: Whisper word timestamps → sentences; librosa loudness/onset/shout-band z-scores
   (causal, so a spike is a surprise relative to the previous 10 s); PySceneDetect cuts; OpenCV motion
   intensity and centroid; fused "action" events where motion, audio and a cut coincide.
2. **Candidates**: windows that start on a sentence start (snapped to a shot cut just before it) and end on
   a sentence end, between `min_len` and `max_len`. Pure gameplay without speech falls back to cuts and a grid.
3. **Score**: 16 normalized features × the niche profile's weights → 0-100, with the top-3 contributing
   signals turned into reasons ("loudness spike at 3:12", "mentions $100,000", "story turn: but, then").
4. **Select**: greedy, no overlaps, 2 s gap.
5. **Hook**: a pattern (curiosity gap / shock / wait for it / bold claim / open loop) chosen from the
   signal shape, filled from the transcript's numbers, names and keywords.
6. **Render**: face → motion → centre reframe to 9:16 with smooth pans, PNG word captions, hook card for
   the first 2 s, two-pass `loudnorm`, x264 CRF 18.

The weights and hook templates come from the research in [`docs/research.md`](docs/research.md); the
module layout is in [`docs/architecture.md`](docs/architecture.md).

## Configuration

`config.yaml` holds every knob (paths, whisper backend/model, clip length, caption style, loudness,
LLM). Put personal overrides in `config.local.yaml` (git-ignored). Profiles live in `profiles/*.yaml`;
copy one to add a niche: weights, keyword list, hook/title templates and hashtag sets per platform.

### Titles and hooks: templates or Claude

By default (`llm.provider: auto`) metadata comes from the niche templates, so nothing leaves your
machine and no key is needed. In Claude Code you can rewrite any clip's copy and save it with
`set_clip_metadata`. If `ANTHROPIC_API_KEY` is set (or you ran `ant auth login`), the server asks Claude
(`claude-opus-5-5` by default) to rewrite hooks/titles/descriptions and to score each clip on Hook / Flow /
Value / Trend; that score is fused into the final score (`llm.fusion_weight`). Set `llm.provider: none`
to disable API calls entirely.

### Windows / NVIDIA

`uv sync` installs faster-whisper. For GPU transcription install CUDA 12 + cuDNN 9 (the
[Purfview whisper-standalone-win libs](https://github.com/Purfview/whisper-standalone-win/releases/tag/libs)
are the easiest way) and keep `whisper.device: auto`; the server picks `large-v3-turbo` on CUDA and
`small` on CPU. Set `whisper.model: medium` for a middle ground on CPU.

## Originality and policy notes

- Platforms demote re-uploads without added value (YouTube Oct 2026, Instagram Apr 2024, Facebook Jul
  2025, TikTok guidelines). Captions and reframing alone do not count as transformation. Add your own
  commentary, voiceover or reaction when clipping someone else's video; `clips.json` keeps `source` for
  attribution and `captions/*.srt` makes voiceover scripting easy.
- YouTube does not monetize graphic game violence in the first 7 seconds; the `gta6` profile penalizes it.
- Clips run 30 s to 1:10 by default. Note that a YouTube Short over one minute with a Content ID claim is
  blocked globally, so pass `max_len=60` when clipping third-party footage for Shorts.

## Tests

```bash
uv run pytest            # fast suite: synthesized 40 s sample video, canned transcript
uv run pytest -m slow    # also runs the real Whisper backend on the sample (downloads the tiny model)
uv run ruff check src tests
```

## Troubleshooting

- *`ffmpeg` was not found on PATH* — install FFmpeg; on Windows restart the terminal after installing.
- *The video is private / unavailable* — only public, non-age-gated videos can be downloaded.
- *yt-dlp warns "n challenge solving failed / Some formats may be missing"* — YouTube's player needs a
  JavaScript runtime for some formats. Downloads still work (1080p was fetched without it); install
  `deno` (`brew install deno` / `winget install DenoLand.Deno`) to silence it and unlock every format.
- *Transcription is slow on CPU* — set `whisper.model: small` (default on CPU) or `base`; on Apple Silicon
  make sure you installed with `--extra mlx`.
- Logs: `logs/viral-clipper.log` (rotating). The MCP wire uses stdout, so nothing is ever printed there.

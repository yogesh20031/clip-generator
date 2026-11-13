# clip-generator (viral-clipper)

A local MCP server for Claude Code that turns a long video (YouTube URL or local file) into the 10
most viral-worthy vertical clips, each with burned-in word-by-word captions, an opening hook, normalized
audio, and per-platform titles, descriptions and hashtags.

Everything that touches video runs on your machine: `yt-dlp`, Whisper (`mlx-whisper` on Apple Silicon,
`faster-whisper` elsewhere), PySceneDetect, librosa, OpenCV and FFmpeg. Claude is only used, optionally,
to polish titles and hooks.

```
clip_video("https://www.youtube.com/watch?v=...", niche="mrbeast")
  → ~/Documents/Desktop/viral-clipper/<video-title>/clip_01.mp4 … clip_10.mp4
    + thumbnails/, captions/*.srt, clips.json, clips.csv
```

New here? [`docs/how-it-works.html`](docs/how-it-works.html) is a one-page visual explainer of the whole
pipeline; open it in a browser.

## Requirements

- **FFmpeg** (`ffmpeg` and `ffprobe` on PATH). macOS: `brew install ffmpeg`. Windows: `winget install Gyan.FFmpeg`.
  No libass needed: captions are rendered as PNG overlays.
- **uv** (https://docs.astral.sh/uv/). It installs Python 3.12 and every dependency for you.
- ~3 GB of disk for Whisper models on first run (`large-v3-turbo`), less if you pick `small`.
- GPU is optional. Apple Silicon uses the GPU through MLX; NVIDIA needs CUDA 12 + cuDNN 9 for
  faster-whisper (see *Windows / NVIDIA* below); otherwise it falls back to CPU with the `small` model.

## Install

```bash
git clone https://github.com/yogesh20031/clip-generator.git
cd clip-generator
uv sync --extra mlx        # macOS Apple Silicon (mlx-whisper)
# uv sync                  # Windows / Linux / Intel Mac (faster-whisper)
uv run pytest              # ~35 s, synthesizes its own test video
```

## Register in Claude Code

```bash
claude mcp add --scope user viral-clipper -- uv --directory /ABSOLUTE/PATH/TO/viral-clipper run viral-clipper
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
| `clip_video(source, niche="generic", num_clips=10, min_len=30, max_len=70, platforms=None, output_dir=None)` | The whole pipeline: one complete story per clip (premise → stakes → build-up → payoff → reaction, filler jump-cut out). Returns every clip with path, edit list, story context, score, reasons, hook and per-platform metadata. |
| `cut_clip(source, start, end=None, duration=None, niche="generic", hook=None, platforms=None, output_dir=None)` | Cut one clip from an exact range (`"17:42"` + `duration="1:20"`), same captions/hook/reframe/loudness, appended as the next clip number. |
| `story_map(source, niche="generic")` | Every story in the video with numbered sentences, each labelled transition / stakes / payoff / action / filler / sponsor / body, plus the automatic edits and their scores. |
| `render_edit(source, sentence_ids=None, segments=None, niche="generic", hook=None, …)` | Render your own edit: sentence ids from `story_map` and/or `[start, end]` ranges, joined with jump cuts, with the same captions, reframe, hook card and loudness. |
| `analyze_video(source, force=False)` | Transcript sentences with timestamps, scene cuts, audio peaks, 1 Hz energy and motion curves. Cached. |
| `score_moments(source, niche, num_clips, min_len, max_len)` | Ranked moments with a 0-100 score, per-signal contributions and plain-language reasons. Renders nothing. |
| `generate_metadata(clip_path, platform, niche=None)` | Title, description, hashtags and hook for one existing clip and platform. |
| `set_clip_metadata(clip_path, platform, title, description, hashtags, hook="")` | Save your own copy into `clips.json`, `clips.csv` and the clip's `.txt` sheet. |
| `list_outputs(output_dir=None)` | Every processed video and its saved clips. |

`source` is a YouTube URL (anything yt-dlp supports) or a path to an `.mp4/.mov/.mkv/.webm` file.
`niche` is a file in `profiles/`: `gta6`, `mrbeast`, `generic`. Platforms: `youtube_shorts`, `tiktok`,
`instagram_reels`, `facebook_reels`.

### CLI (same pipeline, handy for testing)

```bash
uv run viral-clipper clip "https://www.youtube.com/watch?v=..." --niche gta6 --num-clips 10
uv run viral-clipper cut "https://www.youtube.com/watch?v=..." --start 17:42 --duration 1:20 --niche mrbeast
uv run viral-clipper score ./gameplay.mp4 --niche gta6
uv run viral-clipper analyze ./gameplay.mp4
uv run viral-clipper list
uv run viral-clipper              # = serve (MCP over stdio)
```

## Output

```
~/Documents/Desktop/viral-clipper/<video-title>/
├── source.mp4            downloaded source (local files are used in place)
├── analysis.json         cached transcript + signal curves
├── clip_01.mp4 … clip_10.mp4   1080x1920, 30 fps, H.264 + AAC 48 kHz, -14 LUFS
├── clip_01.txt … clip_10.txt   copy sheet per clip: hook, title, hashtags, description for each platform
├── thumbnails/clip_NN.jpg      frame at the payoff moment
├── captions/clip_NN.srt|.ass   editable captions
├── clips.json            full records: score, timestamps, reasons, features, hook, metadata per platform
└── clips.csv             one row per clip per platform: title, hashtags, description, hook
```

## How clips are built: one story per clip

A clip is not "the loudest 60 seconds". It is one complete story that someone who never saw the long
video can follow: **who** is involved, **what is at stake**, the **build-up**, the **payoff** and the
**reaction**. The filler between those beats is jump-cut out. This is how professional editors and the
published clipping systems work (HIVE, OpusClip's Repurpose-10K, Adobe PodReels; see
[`docs/research.md` §6](docs/research.md)).

1. **Analyze.**
   - Whisper word timestamps become sentences.
   - librosa gives loudness, onset and shout-band z-scores. They are causal, so a spike is a surprise relative to the previous 10 s.
   - PySceneDetect finds cuts.
   - OpenCV measures motion intensity and its centroid.
   - Places where motion, audio and a cut coincide are fused into "action" events.
2. **Find the stories.**
   - The video is split at spoken transitions ("For our next challenge…", "It is finally time to meet…", "let's go see…").
   - Each split is backed by a topic change, a change of names, a pause and a scene cut.
   - Sponsor reads are found and never used.
   - Stretches with no speech but lots of action (a race, a shot, a crash) become units of their own, so the action is kept.
3. **Find each story's payoffs.** A payoff is the loud moment that the next lines confirm ("That was a tie!", "Here is one million dollars!"). The story's final result gets a bonus.
4. **Build the edit.**
   - Always kept:
     - the opening line
     - the stakes ("If Khalid can beat Ronaldo, I'm going to give him a million dollars")
     - the line that introduces anyone named at the payoff
     - the build-up into the payoff
     - the payoff itself
     - up to 6 s of reaction
   - The clip ends on the reaction, never the wind-down.
   - Optional lines are added by importance until the niche's target length, capped at `max_len`.
   - Filler, dead air and pauses over 0.5 s are cut out.
5. **Premise card.** The clip opens on a card such as "Ronaldo vs Khalid for $1M", built from the story's names and stakes, so the context lands in the first 3.5 s. The same text is the title.
6. **Score and select.**
   - 16 normalized features × the niche weights, plus a coverage score. Coverage checks for a clean opening, stakes set up, names explained, a payoff, and an ending on the reaction.
   - No two clips share a payoff.
   - When a video has fewer stories than `num_clips`, the rest are filled with the best contiguous windows.
7. **Render.**
   - Each piece is reframed separately (face → motion → centre).
   - Pieces are joined frame-exactly with 15 ms audio fades, so the jump cuts don't click.
   - Captions are remapped to the clip's timeline.
   - Two-pass `loudnorm` over the joined audio.

### Gameplay with no commentary

Story mode needs speech. For uncommentated gameplay (a GTA stunt run, a race) two safeguards kick in:

- **Whisper hallucination filter.** Over game audio Whisper invents lines ("Thanks for watching!",
  foreign-script text, low-confidence rambling). `drop_hallucinations` removes stock phrases,
  wrong-script text and anything below `whisper.min_word_prob` (0.4) that isn't near confident speech.
  The raw transcript stays in the cache, so changing the threshold doesn't need a re-transcribe.
- **Window mode fallback.** When a video has fewer than `clip.min_speech_wpm` (20) spoken words per
  minute, it is treated as uncommentated and cut into continuous action windows instead of story edits.
  For these, pick one complete run by looking at the frames and write the hook yourself
  (`cut_clip(..., hook="Rocket car vs the BIGGEST mega ramp")`): a manual hook becomes the premise card
  and the title.

### Credit lines

The source's channel and licence come from yt-dlp. Every description gets a credit line:
`Gameplay: <channel> (CC BY)` for Creative Commons videos, `Original video: <channel>` otherwise. Niche
profiles can also swap wording per source: the `gta6` profile's `source_variants` say "GTA 5" instead of
"GTA 6" when the source is a GTA 5 video.

`clip_NN.txt` lists the premise, the stakes line, where the story sits in the source and the full edit
list. `clip.mode: window` in `config.yaml` brings back the old single-window behaviour.

**Hand-editing.** In Claude Code, ask for the story map, then pick the sentences you want:

```text
> map the stories in https://www.youtube.com/watch?v=0BjlBnfHcHM (mrbeast)
> render sentences 471, 473, 484-487 and 544, plus 20:43-21:01, with hook "Ronaldo vs Khalid for $1M"
```

From the CLI:

```bash
uv run viral-clipper stories <url> --niche mrbeast
uv run viral-clipper edit <url> --ids 471 473 484 485 486 487 544 --seg 20:43-21:01 --hook "Ronaldo vs Khalid for \$1M"
```

### Rules every clip must satisfy

1. **It stands on its own.** A viewer who has never seen the source must still get it.
   - The clip is one story with its premise, stakes, build-up, payoff and reaction (see above).
   - It never opens on "and…", "but…" or a dangling pronoun.
   - Everyone named at the payoff is introduced earlier in the clip or on the premise card.
   - This is scored as `context_completeness`. Clips below `clip.min_context` (0.35) are skipped.
   - The mrbeast and generic profiles weight it at 0.9 and 0.8, so a complete story outranks a louder fragment.
2. **The thumbnail is picked for clicks.** Frames are sampled across the finished clip and scored on the
   biggest visible face/reaction, contrast and sharpness, biased towards the payoff. The best frame is
   `thumbnails/clip_NN.jpg`; two alternates (`_alt1`, `_alt2`) sit beside it so you can choose. The chosen
   time is recorded in `clips.json` (`thumbnail_time`). Add your own numbers later in each clip's
   `analytics` field (views, CTR, viewed-vs-swiped) and they feed the next round of weight tuning.
3. **Never cut mid-sentence**, never letterbox, never watermark, never mute the original audio.

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

## Posting the clips

viral-clipper only makes the clips. Posting is a separate local tool, `video-uploader`, which reads
`clips.json`, keeps your logins in its own Chrome profile and never publishes until you say "share".

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

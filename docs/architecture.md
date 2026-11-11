# Architecture

`viral-clipper` is a local MCP server (Python 3.12, `mcp` v2) that turns a long video into ranked,
captioned 9:16 clips with per-platform metadata. All video processing is local; only the optional
title/hook rewrite talks to Claude.

```
source (URL | file)
   │  ingest/      yt-dlp download → ffprobe → VideoInfo, work_dir = <output>/<slug>/
   ▼
analysis/          audio.wav ──► librosa: RMS, onsets, 300-3000 Hz band z-scores, silence
                   ├─────────► whisper (mlx-whisper on Apple Silicon | faster-whisper CUDA/CPU): words → sentences
                   video ────► PySceneDetect AdaptiveDetector: cuts
                   video ────► FFmpeg gray pipe @4 fps → OpenCV frame-diff: motion curve + centroid
                   events.py   fuse motion + onset + cut spikes → "action" events
                   analyze.py  everything cached in analysis.json (fingerprint = file + config)
   ▼
scoring/           signals.py   per-video robust 0-1 normalization
                   candidates.py sentence-boundary windows (min_len..max_len), snapped to cuts; grid fallback
                   scorer.py    16 features × profile weights → 0-100, top-3 reasons, hook pattern
                   profile      profiles/<niche>.yaml (weights, keywords, hook/title templates, hashtags)
   ▼
render/            crop.py      YuNet face → motion centroid → centre, EMA-smoothed, cut resets → crop expr
                   captions.py  Pillow word-state PNGs → concat demuxer overlay (no libass needed)
                   hook_overlay.py  hook card PNG for the first ~2 s
                   thumbnail.py face/contrast/sharpness-scored frame near the payoff + alternates
                   ffmpeg.py    loudnorm two-pass (-14 LUFS / -1 dBTP / LRA 11), progress parsing
                   clip.py      one ffmpeg call: crop → scale 1080x1920 → overlays → x264 + aac
   ▼
metadata/          templates.py  deterministic hooks/titles/descriptions/hashtags (always available)
                   llm.py        optional Claude rewrite + Hook/Flow/Value/Trend virality score
                   platforms.py  per-platform limits (title length, hashtag counts)
                   outputs.py    clips.json / clips.csv, list_outputs, set_clip_metadata
   ▼
<output>/<slug>/   source.mp4, analysis.json, clip_01..NN.mp4, thumbnails/, captions/*.srt|.ass, clips.json, clips.csv
```

## MCP tools

| Tool | What it does |
|---|---|
| `clip_video(source, niche, num_clips, min_len, max_len, platforms, output_dir)` | full pipeline → clips + metadata |
| `analyze_video(source, force)` | transcript sentences, scene cuts, audio peaks, 1 Hz energy/motion curves |
| `score_moments(source, niche, num_clips, min_len, max_len)` | ranked candidates with reasons, nothing rendered |
| `generate_metadata(clip_path, platform, niche)` | title/description/hashtags/hook for one clip |
| `set_clip_metadata(clip_path, platform, title, description, hashtags, hook)` | persist your own copy into clips.json/csv |
| `list_outputs(output_dir)` | every processed video and its clips |

Every long tool streams `report_progress` notifications; pipeline code runs on a worker thread.

## Scoring

`score = 100 · clip(Σ wᵢ·fᵢ / Σ positive wᵢ, 0, 1)`, features in 0-1, penalties negative. Features:
`audio_peak, motion_intensity, scene_cut_density, event_density, speech_excitement, laughter_shout,
keyword_hits, money_number_mentions, twist_connectives, payoff_in_window, hook_strength,
sentence_boundary_bonus, length_prior, context_completeness, silence_penalty, violence_first7s` (+ zero-weight v2 slots
`face_reaction, ocr_banner, audio_event_class`, and `llm_hook_flow_value_trend` which only counts when
Claude scored the clip). Weights and their research basis: `docs/research.md` §5.

Windows with `context_completeness < clip.min_context` are dropped first (a clip must make sense on its own). Selection is then greedy by score with no overlap and a `min_gap_s` buffer. Clips start on a sentence start
(or a shot cut just before it) and end on a sentence end, so speech is never cut mid-sentence.

## Design decisions

- **PNG overlays instead of libass**: Homebrew's FFmpeg has no `subtitles`/`ass`/`drawtext` filters; the
  concat-demuxer overlay works on every build and gives exact styling control.
- **Causal z-scores** for spikes: a spike is a surprise relative to the previous 10 s, not a centred window.
- **No letterboxing**: Instagram demotes bordered Reels, so the reframe is always a true crop.
- **Templates first, Claude optional**: `clip_video` never depends on an API key; the Claude Code session
  that drives the server can rewrite copy and persist it with `set_clip_metadata`.
- **Cross-platform**: macOS Apple Silicon is the tested target (mlx-whisper); Windows/Linux use
  faster-whisper with CUDA 12 + cuDNN 9 when present, CPU otherwise.

## v2 backlog

AudioSet tagging (YAMNet/PANNs) for laughter/explosions, CLIP prompt packs, Video-LLM re-rank of the
top 20, OCR for game banners (WASTED/BUSTED), diarization-driven active-speaker crops, Apache-licensed
person tracking, 61-90 s variants, analytics feedback loop that refits profile weights.

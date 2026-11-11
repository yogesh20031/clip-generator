# Research: what makes a short-form clip travel, and how to find it locally

Researched 2026-11-11 for the `viral-clipper` MCP server. Every factual claim links to its source.

Status labels used throughout:

- **Official** — the platform's own help page, newsroom, transparency center or developer blog.
- **Official (press-reported)** — the platform said it, but only trade or news coverage of the statement was fetched.
- **Research** — peer-reviewed or arXiv work.
- **Vendor claim** — a company's own marketing about its own product.
- **creator-observed, not confirmed** — common creator or marketer wisdom with no official source or data behind it.

No platform publishes ranking weights. Nothing below claims knowledge of the internal algorithm.

---

## 1. What the platforms say about ranking short-form video

### 1.1 YouTube Shorts

- **Viewed vs. swiped away / "Stayed to watch"** — Official — [YouTube Help: Shorts analytics](https://support.google.com/youtube/answer/12220281) — "Stayed to watch" is "the percentage of times viewers stayed to watch past the initial seconds of a Short."
- **Engaged views (retention-gated)** — Official — [same page](https://support.google.com/youtube/answer/12220281) — engaged views count "how many times viewers stayed to watch past the initial seconds, not including any loops." Average view duration and average percentage viewed are computed from engaged views.
- **Replays count as views, not as engaged views** — Official — [YouTube Help: view counts](https://support.google.com/youtube/answer/10059070) — since 2025-03-31 a view counts each time a Short "starts to play or replay, with no minimum watch time." Partner Program eligibility and revenue stay tied to engaged views.
- **View counting unified across formats** — Official — [same analytics page](https://support.google.com/youtube/answer/12220281) — from 2026-08-24 a view counts "the moment a video starts to play across all formats, including Shorts."
- **Seed-audience testing** — Official (press-reported; Shorts product lead Todd Sherman, 2023) — [TechCrunch](https://techcrunch.com/2023/08/25/youtube-demystifies-the-shorts-algorithm-views-and-answers-other-creator-questions/), [Search Engine Journal](https://searchenginejournal.com/youtube-explains-how-shorts-algorithm-works/494953) — a Short is shown to a small seed audience first; their response decides further reach.
- **"No length is best"** — Official (press-reported, Sherman 2023) — [TechCrunch](https://techcrunch.com/2023/08/25/youtube-demystifies-the-shorts-algorithm-views-and-answers-other-creator-questions/) — match length to the story.
- **Posting frequency does not help; delete-and-re-upload can look like spam** — Official (press-reported, Sherman 2023) — same TechCrunch article.
- **Custom thumbnails and posting time barely matter in the swipe feed** — Official (press-reported, Sherman 2023) — same article.
- **Satisfaction surveys, likes/dislikes, viewing behaviour** — Official (all of YouTube) — [How YouTube works: recommendations](https://www.youtube.com/howyoutubeworks/recommendations/).
- **Length limit 3 minutes, square or vertical** — Official — [YouTube Help: Shorts length](https://support.google.com/youtube/answer/15424877) — uploads since 2024-10-15 up to 3 minutes count as Shorts.
- **Content ID over 1 minute blocks the Short globally** — Official — [same page](https://support.google.com/youtube/answer/15424877) — a Short longer than one minute with an active copyright claim "will be blocked globally"; blocked Shorts are not recommended. Under one minute is exempt. **This is why the default `max_len` stays at 60 s.**
- **Re-uploads without added value lose reach (Oct 2026)** — Official (press-reported TeamYouTube Help Community post, 2026-10-01) — [PPC Land](https://ppc.land/re-uploaded-shorts-lose-reach-as-youtube-favours-original-clips/), [Social Media Today](https://www.socialmediatoday.com/news/youtube-updates-shorts-algorithm-to-put-more-focus-on-original-content/), [Dexerto](https://www.dexerto.com/youtube/youtube-cracks-down-on-clipping-channels-in-shorts-update-prioritizing-original-content-3415700/) — YouTube will "reduce the reach of content re-uploaded from other creators without adding anything of your own"; "minor technical edits or template-based changes" do not count as original.
- **Reused-content monetization policy** — Official — [YouTube Help: reused content](https://support.google.com/youtube/answer/1311392) — not allowed: "Clips of moments from your favorite show edited together with little or no narrative." Allowed when you "add a storyline and commentary."
- **Gaming-violence ad rules (2026-09-04)** — Official (press-reported) — [Dexerto](https://www.dexerto.com/gta/youtube-updates-gaming-violence-monetization-rules-ahead-of-gta-6-launch-3405945/) — graphic violence in the **first 7 seconds** cannot earn ad revenue; graphic gameplay from 8-15 s can; blurred violence can; "compilations of players slaughtering groups of NPCs" can be fully demonetized. Licensed in-game radio can trigger Content ID.
- **70-90% "viewed" target** — creator-observed, not confirmed — [vidIQ](https://vidiq.com/blog/post/youtube-shorts-algorithm/) — YouTube publishes no threshold.

### 1.2 TikTok

- **Finishing a longer video is a strong signal** — Official — [TikTok Newsroom: How TikTok recommends videos For You](https://newsroom.tiktok.com/how-tiktok-recommends-videos-for-you/?lang=en) — "whether a user finishes watching a longer video from beginning to end, would receive greater weight than a weak indicator."
- **Watch time weighted most** — Official — [TikTok Support: How TikTok recommends content](https://support.tiktok.com/en/using-tiktok/exploring-videos/how-tiktok-recommends-content) — "the time spent watching a video, are generally weighted more heavily than others."
- **Predicted finish / skip / like / share / comment / time spent** — Official — [TikTok Transparency: recommendation system](https://www.tiktok.com/transparency/en/recommendation-system).
- **Video information: captions, sounds, hashtags, length** — Official — newsroom and transparency pages above.
- **Follower count is not a direct factor** — Official — newsroom page above.
- **Diversity and duplicates** — Official — newsroom page above — no two videos in a row with the same sound or creator; duplicated content is not recommended.
- **Unoriginal content ineligible for For You** — Official — [Community Guidelines: integrity and authenticity](https://www.tiktok.com/community-guidelines/integrity-authenticity/) — "ineligible for the FYF if it includes unoriginal or reused material without anything new."
- **Hook in the first second, captions matter** — Official (creator tips published by TikTok, not stated ranking factors) — [TikTok Newsroom: scroll-stopping tips](https://newsroom.tiktok.com/scroll-stopping-tips-from-top-tiktok-creators?lang=en-GB) (2025-10-22).
- **Ad creative guidance: proposition in the first 3 s, hook within 6 s** — Official (press-reported) — [Marketing Brew](https://www.marketingbrew.com/stories/2023/12/18/pay-attention-to-me-report-shares-brand-tips-for-catching-users-interest-on-tiktok).
- **Length options** — Official (press-reported) — [TechCrunch 2022](https://techcrunch.com/2022/02/28/tiktok-expands-max-video-length-to-10-minutes-up-from-3-minutes), [TechCrunch 2024](https://techcrunch.com/2024/05/16/tiktok-upload-60-minute-videos).
- **Creator Rewards needs ≥ 1 minute, original** — creator-observed, not confirmed — [Metricool](https://metricool.com/tiktok-creator-next/), [Nuelink](https://blog.nuelink.com/tiktok-creator-rewards-program/) — a monetization rule, not ranking.
- **Watermarks from other platforms suppressed** — creator-observed, not confirmed — [Online Optimism](https://onlineoptimism.com/blog/updates-tiktoks-community-guidelines).

### 1.3 Instagram Reels

- **Mosseri "Ranking Explained" (2023-05-31)** — Official — [about.instagram.com](https://about.instagram.com/blog/announcements/instagram-ranking-explained) — predicts how likely you are to "reshare a reel, watch a reel all the way through, like it, and go to the audio page." Inputs in order: your activity, your history with the poster, information about the reel, information about the poster.
- **Watermarked, low-res, muted, bordered, mostly-text and reposted Reels are shown less** — Official — same page.
- **Top three signals (Jan 2025): watch time, likes per reach, sends per reach** — Official (press-reported Mosseri) — [Social Media Today](https://www.socialmediatoday.com/news/instagram-shares-algorithm-insights-2025/738034/) — sends matter more for non-followers.
- **Skip rate measured at 3 seconds** — Official — [Meta developer blog, 2025-12-03](https://developers.facebook.com/blog/post/2025/12/03/instragram-api-updates/) — Reels Skip Rate is "the percentage of views where viewers skip a Reel within the first 3 seconds." Retention chart added to Insights around Aug 2025: [Website Builder Expert](https://www.websitebuilderexpert.com/news/instagram-reel-retention-chart/).
- **Originality policy (2024-04-30)** — Official — [Instagram Creators: recommendations and originality](https://creators.instagram.com/recommendations-and-originality) — "no visible watermarks"; of identical content "we will only recommend the original one"; accounts that repeatedly post content they "didn't create or enhance in a material way" are dropped from recommendations. Material edits include voiceover, parody, reaction remix.
- **"10 reposts in 30 days" aggregator threshold** — Official (press-reported) — [Engadget](https://www.engadget.com/instagrams-algorithm-overhaul-will-reward-original-content-and-penalize-aggregators-130018977.html).
- **3-minute Reels (2025-01-20)** — Official (press-reported) — [Social Media Today](https://www.socialmediatoday.com/news/instagram-officially-expands-reels-length-3-minutes/737766/).
- **Reels over 3 minutes not recommended to non-followers** — creator-observed, not confirmed — [SocialPilot](https://www.socialpilot.co/?p=563048).
- **5-hashtag cap (Dec 2025)** — creator-observed, not confirmed (sources disagree) — [Later](https://later.com/blog/instagram-hashtags/amp).

### 1.4 Facebook Reels

- **System card (updated 2026-06-19)** — Official — [Meta Transparency Center: Facebook Reels](https://transparency.meta.com/features/explaining-ranking/fb-reels/) — predictions include how long you watch, whether you watch rather than skip, watch to completion, how much you watch, share to WhatsApp, share count on Messenger, "see less" and "hide." Inputs include the reel's length and whether it is original.
- **Surveys in prediction training** — Official — [Meta Newsroom 2023](https://about.fb.com/news/2023/06/how-ai-ranks-content-on-facebook-and-instagram/).
- **Unoriginal content crackdown (2025-07-14)** — Official — [Facebook Creators blog](https://creators.facebook.com/blog/combating-unoriginal-content) — duplicates get reduced distribution; "simply stitching together clips or adding your watermark does not qualify as meaningful enhancement." Captions do best with no links, minimal capitals, at most 5 hashtags.
- **Best practices** — Official — [Facebook Creators: Reels best practices](https://creators.facebook.com/reels-best-practices-tips-tricks) — "Vertical content (9:16)"; "a strong hook or payoff"; "avoid 3rd-party fonts and watermarks"; avoid blurry low-res video; "Don't post Reels that are visibly recycled from other apps."
- **All Facebook videos are Reels, no length cap (June 2025)** — Official (press-reported) — [Tubefilter](https://www.tubefilter.com/2025/06/17/meta-facebook-reels-all-videos-update/).
- **Captions raise view time ~12% (2016 ads data)** — Official (press-reported, not organic Reels) — [MarTech](https://martech.org/facebook-releases-new-video-ad-features-including-automated-captions).

### 1.5 Research on short-video recommenders

- **Early skips are strong negatives** — Research — [Lee et al., AAAI 2025](https://arxiv.org/abs/2504.03107) — skips within the first seconds are treated as negatives; most skips in KuaiRand-style datasets happen within ~5 s.
- **Duration bias** — Research — [Zhan et al., Kuaishou, KDD 2022](https://arxiv.org/pdf/2206.06003) — length confounds exposure and watch time; production systems correct for it, so length is not a free win.
- **Completion rate is a noisy target** — Research — [Zhao et al. 2023, D2Co](https://arxiv.org/pdf/2308.08120).
- **Swipe timing is predictable per video** — Research — [Dashlet, NSDI 2023](https://www.cs.princeton.edu/~ravian/publications/dashlet_nsdi23.pdf).

### 1.6 Cross-platform takeaways → engineering rules

| # | Rule in the clipper | Supported by |
|---|---|---|
| 1 | Score the hook in the first 1-3 s; start cold on the payoff/question/conflict; speech or motion within ~0.5 s | YT (engaged view, viewed-vs-swiped), IG (3 s skip rate), FB (watch-vs-skip), TikTok (skip prediction), research |
| 2 | Optimize for completion; trim dead air and filler | FB (completion), TikTok (finish = strong), IG (watch-through) |
| 3 | Default 15-60 s; `length_prior` centred at 25 s (gta6) / 45 s (mrbeast); never over 60 s for third-party or music-bearing material | YT (Content ID > 60 s blocked), research (duration bias) |
| 4 | End right after the payoff, no outro, loop-friendly | YT (replays count as views) + inference |
| 5 | Pick self-contained "send this to a friend" moments | IG (sends per reach), FB (WhatsApp/Messenger shares), TikTok (shares) |
| 6 | No watermarks or branding bugs, ever | IG, FB (official), TikTok (creator-observed) |
| 7 | Native 9:16 1080x1920 crop; no letterbox or blur bars | IG (borders demoted), FB (9:16), YT (vertical required) |
| 8 | Short word-level captions in the safe zone; never mute the original audio | IG (mostly-text and muted demoted), TikTok (sound is a signal), FB (captions +12%) |
| 9 | Originality warning in README and output; `clips.json` keeps `source_url` | all four |
| 10 | Return fewer clips rather than duplicates; never re-upload | IG, FB, TikTok, YT |
| 11 | Clean metadata: topical caption, 3-10 hashtags by platform, no links, not all caps | TikTok, FB, YT |
| 12 | Reserve an `analytics` field per clip for the feedback loop (viewed-vs-swiped, skip rate) | YT, IG, FB |

---

## 2. Automatic highlight detection: methods that run locally

### 2.1 Signal-based features (cheap, CPU)

- **Audio RMS energy and spectral flux** — [librosa onset_strength](https://librosa.org/doc/main/generated/librosa.onset.onset_strength.html) — `feature.rms` for loudness, `onset_strength` (spectral flux) for sudden changes (roars, impacts, laugh bursts). Z-score against a ~60 s rolling median, smooth 1-3 s, weighted sum. ISC license. **MVP baseline.**
- **YAMNet (AudioSet, 521 classes)** — [repo](https://github.com/tensorflow/models/tree/master/research/audioset/yamnet), [class map](https://raw.githubusercontent.com/tensorflow/models/master/research/audioset/yamnet/yamnet_class_map.csv) — relevant classes: Shout 6, Whoop 8, Yell 9, Screaming 11, Laughter 13, Clapping 58, Cheering 61, Applause 62, Crowd 64, Explosion 420, Gunshot 421. ~3.7M params, CPU fine, Apache-2.0. **v2 plug-in** (keeps TensorFlow out of the MVP).
- **PANNs CNN14 (527 classes, PyTorch)** — [paper](https://arxiv.org/abs/1912.10211), [repo](https://github.com/qiuqiangkong/audioset_tagging_cnn) — higher mAP than YAMNet, ~80M params. **v2 alternative.**
- **LAION CLAP (zero-shot audio-text)** — [repo](https://github.com/LAION-AI/CLAP) — score windows against prompts like "car crash", "people laughing". **v2.**
- **Laughter detection** — [jrgillick/laughter-detection](https://github.com/jrgillick/laughter-detection), [Interspeech 2021](https://www.isca-archive.org/interspeech_2021/gillick21_interspeech.html) — pinned to old torch; AudioSet laughter class usually suffices. **Later.**
- **Speech rate and excitement from ASR** — [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (MIT) — `word_timestamps=True`, `vad_filter=True`; words/sec, pause density, loudness during speech. GPU needs CUDA 12 + cuDNN 9 (ctranslate2 ≥ 4.5). No Metal support, hence [mlx-whisper](https://pypi.org/project/mlx-whisper/) on Apple Silicon. **MVP core.**
- **PySceneDetect** — [detectors docs](https://www.scenedetect.com/docs/latest/api/detectors.html) — ContentDetector `threshold=27`, `min_scene_len=15`; AdaptiveDetector `adaptive_threshold=3.0`, `min_content_val=15`, `window_width=2`. Cut density is itself an energy feature; cut points make good clip boundaries. **MVP (AdaptiveDetector).**
- **Motion intensity (OpenCV)** — [optical flow tutorial](https://docs.opencv.org/4.x/d4/dee/tutorial_optical_flow.html) — `absdiff` mean at 2-4 fps on ~320 px grayscale frames (cheap) or Farneback flow (better). Normalize per video. **MVP (absdiff).**
- **Transcript lexicon** — exclamations, superlatives, questions, "wait", "no way", numbers, money; optional [twitter-roberta sentiment](https://huggingface.co/cardiffnlp/twitter-roberta-base-sentiment-latest). **MVP as regex prior.**
- **Chat-spike detection** — [josec07/clipper](https://github.com/josec07/clipper), [PogChampNet](https://medium.com/@farzatv/pogchampnet-how-we-used-twitch-chat-deep-learning-to-create-automatic-game-highlights-with-only-61ed7f7b22d4) — needs chat logs; **not applicable to VOD files.**

### 2.2 Learned models (local feasibility)

- **Moment-DETR / QVHighlights** — [repo](https://github.com/jayleicn/moment_detr), [paper](https://arxiv.org/abs/2107.09609) — query-driven; QVHighlights annotations are CC BY-NC-SA 4.0 (checkpoints effectively non-commercial); 150 s video cap. **Skip for MVP.**
- **QD-DETR / CG-DETR / UVCOM / TR-DETR via Lighthouse** — [Lighthouse](https://github.com/line/lighthouse) (Apache-2.0), [CG-DETR](https://github.com/wjun0830/CGDETR), [paper](https://arxiv.org/abs/2408.02901) — one API for query-based highlight detection; CLIP features on CPU possible. Same licence caveat. **v2 experiment.**
- **UniVTG (ICCV 2023)** — [repo](https://github.com/showlab/UniVTG), [paper](https://arxiv.org/abs/2307.16715) — research-grade. **Later.**
- **UMT (CVPR 2022)** — [repo](https://github.com/TencentARC/UMT), [paper](https://arxiv.org/abs/2203.12745) — query-free audio-visual HD; needs pre-extracted features. **Later.**
- **PGL-SUM / DSNet (TVSum/SumMe)** — [PGL-SUM](https://github.com/e-apostolidis/PGL-SUM), [DSNet](https://github.com/li-plus/dsnet) — "representative" ≠ "viral". **Skip.**
- **CLIP zero-shot frame scoring** — [open_clip](https://github.com/mlfoundations/open_clip) (MIT) — ViT-B-32 at 1 fps vs prompt packs ("explosion", "celebration"). **v1.1 optional.**
- **Video-LLMs (Qwen2.5-VL / Qwen3-VL / LLaVA-Video / InternVL)** — [Qwen3-VL report](https://arxiv.org/abs/2511.21631), [TimeLens](https://arxiv.org/abs/2512.14698), [Qwen2.5-VL-7B](https://huggingface.co/Qwen/Qwen2.5-VL-7B-Instruct), [LLaVA-Video](https://huggingface.co/lmms-lab/LLaVA-Video-7B-Qwen2), [InternVL3-8B](https://huggingface.co/OpenGVLab/InternVL3-8B) — re-rank only the top ~20 candidates; needs ≥ 8-12 GB GPU. **v2.**
- **LLM-over-transcript re-ranking** — [RHAPSODY, COLM 2025](https://arxiv.org/abs/2505.19429) (13K podcasts labelled with YouTube "most replayed"; text + audio features beat text alone), [Spotify previews](https://arxiv.org/abs/2505.23908) — what commercial clippers do. **MVP (optional Anthropic path), fused with signals.**

### 2.3 Open-source projects worth borrowing from

- [ClipsAI](https://github.com/ClipsAI/clipsai) (MIT) — [resize docs](https://www.clipsai.com/references/resize): face detection + diarization + scene detection for 9:16 reframing. Borrow the crop logic.
- [FunClip](https://github.com/modelscope/FunClip) (MIT) — "select text → clip" UX and LLM clipping prompts.
- [auto-editor](https://github.com/WyattBlue/auto-editor) (Unlicense) — silence/low-motion removal. v2 dead-air tightening.
- [AutoClip](https://github.com/artbyjazi/autoclip), [Skate](https://github.com/r2hu1/skate) — local whisper + LLM pipelines; closest architectural twins.
- [SupoClip](https://github.com/FujiwaraChoki/supoclip), [AI-Youtube-Shorts-Generator](https://github.com/Anil-matcha/AI-Youtube-Shorts-Generator) — prompt templates and crop code.
- [ShortGPT](https://github.com/RayVentura/ShortGPT) — different problem (generation). Skip.
- [video-use loudness notes](https://instagit.com/browser-use/video-use/social-media-loudness-normalization-targets/) — -14 LUFS / -1 dBTP / LRA 11.
- [auto-subtitle](https://github.com/m1guelpf/auto-subtitle) — minimal whisper + ffmpeg burn-in.
- Reframing: [AutoFlip](https://opensource.googleblog.com/2020/02/autoflip-open-source-framework-for.html) is legacy (skip); [pyautoflip](https://pypi.org/project/pyautoflip/) (InsightFace models non-commercial, v2); [smartcrop.py](https://github.com/smartcrop/smartcrop.py) (per-frame jitter, skip); [MediaPipe Face Detector](https://ai.google.dev/edge/mediapipe/solutions/vision/face_detector) (Apache-2.0); [Ultralytics](https://github.com/ultralytics/ultralytics) is **AGPL-3.0** ([license](https://ultralytics.com/license)) → prefer [YOLOX](https://github.com/Megvii-BaseDetection/YOLOX) (Apache-2.0) or RT-DETR in v2. MVP uses OpenCV's bundled YuNet face detector + motion centroid.

### 2.4 Loudness and captions

- **Loudness target** — -14 LUFS integrated, -1 dBTP, LRA ~11 ([Forasoft 2026](https://www.forasoft.com/learn/audio-for-video/articles-audio/lufs-targets-per-platform-2026)); no official TikTok/YouTube spec; EBU R128's -23 is too quiet for shorts.
- **ffmpeg `loudnorm`** — [filter docs](https://ffmpeg.org/ffmpeg-filters.html#loudnorm), [guide](https://dev.to/javidjamae/ffmpeg-loudnorm-filter-ebu-r128-loudness-normalization-guide-15d4) — defaults are I=-24, LRA=7, TP=-2, so always set explicitly; two passes (`print_format=json` then `measured_*` + `linear=true`); single-pass upsamples to 192 kHz so add `-ar 48000`.
- **Captions via ASS/libass** — [pysubs2](https://github.com/tkarabela/pysubs2); ASS `\k` uses centiseconds while `\t` uses milliseconds (a classic bug); word-by-word look = re-emit the phrase with the active word recoloured/scaled ([reference](https://dev.to/danielrusnok/captions-that-read-along-one-word-at-a-time-3alg)). **Finding during planning: the local Homebrew FFmpeg 9.0.2 has no libass** (`subtitles`, `ass` and `drawtext` filters absent), and Windows "essentials" builds vary → the clipper renders captions as Pillow PNG overlays fed through the concat demuxer and `overlay`, which needs only core filters.
- **`drawtext`** — [docs](https://ffmpeg.org/ffmpeg-filters.html#drawtext-1) — verbose, needs libfreetype; fallback only.

### 2.5 Recommended local stack (MVP) and v2

1. faster-whisper / mlx-whisper with word timestamps and VAD.
2. Audio track at 4 Hz: z-scored RMS + onset strength, band-limited spike detector for laughter/shouts.
3. Visual track: PySceneDetect AdaptiveDetector + OpenCV frame-diff motion with centroid.
4. Candidates on sentence boundaries, 15-60 s, non-overlapping, snapped to cuts.
5. Weighted fusion per niche profile → 0-100 with per-signal reasons; optional LLM re-rank (Hook/Flow/Value/Trend) fused 0.6/0.4.
6. 9:16 reframe: face detection → motion centroid → centre, EMA-smoothed, reset at cuts.
7. Render: FFmpeg trim, crop, scale, PNG caption overlay, two-pass loudnorm, H.264 30 fps.

v2: AudioSet tagging (YAMNet/PANNs), CLIP prompt packs, Video-LLM re-rank, diarization for active speaker, Apache-licensed person tracking, OCR for game banners, analytics feedback loop, 61-90 s variants, chat-log ingestion for stream VODs.

---

## 3. How commercial AI clipping tools work

### 3.1 Per-tool findings

- **OpusClip** — virality score 0-99 built from **Hook, Flow, Value, Trend** ([help center](https://help.opus.pro/docs/article/virality-score.md)); inputs claimed: emotional intensity, narrative completeness, hook strength, audio dynamics, quotability, visual engagement (vendor claim, [API blog](https://www.opus.pro/blog/viral-moment-detection-api)); competitor says lower-scored clips sometimes performed better ([Submagic review](https://submagic.co/blog/opus-clip-review)). ClipAnything = multimodal moment search with a prompt and genre ([help](https://help.opus.pro/docs/article/how-to-use-clipanything.md)); uses Gemini Flash for visual descriptions ([Google developers blog](https://developers.googleblog.com/opusclip-achieves-30-percent-cost-savings-in-visual-description-processing-with-gemini-flash/)). ReframeAnything favors speakers; objects need manual tracking ([subject tracking](https://help.opus.pro/docs/article/subject-tracking), [AI reframe](https://opus.pro/ai-reframe)). Free ~60 min/mo with watermark, Starter ~$15/mo ([Toolradar](https://toolradar.com/tools/opusclip/pricing)). **Own data** ([Anatomy of a viral TikTok 2026](https://www.opus.pro/blog/anatomy-of-a-viral-tiktok-2026)): viral-tier median 41 s vs 50 s overall; 15-30 s overrepresented, 60-90 s underrepresented; 80.2% captioned, 78.6% animated captions; 10.4 hashtags vs 4.8 in the bottom tier; niche + generic tags ≈ 2.5× median views.
- **Klap** — topic extraction + virality score; face-recognition reframe; "AI Reframe 2" adds Split Screen, Screencast and **Gaming** layouts; prompted themes ([klap.app](https://klap.app), [blog](https://klap.app/blog/ai-clip-maker)); Basic $14.50/mo yearly.
- **Vizard** — free plan, virality score ([Klap comparison](https://klap.app/alternatives/vizard-ai), competitor opinion); gaming guide for facecam-in-shot clips ([Vizard](https://agent.vizard.ai/how-to/cut-gaming-highlights-that-keep-your-facecam-in-shot.html)).
- **Submagic** — captions in 118 languages, auto emojis, sound effects, B-roll, Magic Zoom, Smart Trim (silence/filler) ([features](https://www.submagic.co/features/auto-video-editor)); Magic Clips on higher plans, ~$19-50/mo ([review](https://ucstrategies.com/news/submagic-review-2026-pricing-features-is-it-worth-it-for-creators/)).
- **Descript** — "Find good clips" with an editable prompt ([AI actions](https://www.descript.com/ai-actions/find-good-clips)); Underlord "Create Clips" ([blog](https://www.descript.com/blog/article/underlord-ai-can-watch-videos)).
- **Riverside Magic Clips** — ~2 clips per 5 min, 30-90 s each, scored 70-99, "experimental" ([support](https://support.riverside.com/hc/en-us/articles/12124048765981)).
- **Captions.ai AI Shorts** — up to 5 clips ≤ 60 s, best on talking heads ([docs](https://captions.ai/help/docs/project/ai-shorts.md)).
- **VEED Clips** — powered by Sieve, "AI Rating", needs > 2 min with speech ([partnership](https://www.veed.io/learn/veed-and-sieve-partnership), [clips](https://veed.io/clips)).
- **Pictory** — transcript soundbites ([Practical Ecommerce](https://www.practicalecommerce.com/ai-tools-for-video-captions)), ~$25/mo ([PricingSaaS](https://pricingsaas.com/companies/pictory)).
- **Kapwing** — Smart Cut silence removal with sensitivity slider ([Smart Cut](https://kapwing.com/tools/smart-cut)), Repurpose Studio ([clip maker](https://www.kapwing.com/ai/clip-maker)).
- **2short.ai** — "center stage" face tracking, animated subtitles, $9.90-49.90 ([Toolbit](https://www.toolbit.ai/ai-tool/2short-ai)).
- **Vidyo.ai → quso.ai** — rebranded, added scheduling/analytics ([quso](https://quso.ai/vidyo-ai)).
- **Munch** — pivoted to AI social posts ([munchstudio.com](https://www.munchstudio.com/)).
- **Eklipse.gg (gaming)** — detects kills, clutches, multi-kills, chat spikes ([AI highlights](https://eklipse.gg/ai-highlights)); GTA V page lists 5-star chases, ramp stunts, heist getaways, airborne wrecks, NPC chaos, jet dogfights, crashes and near-misses "even when no one is eliminated" ([GTA V use case](https://eklipse.gg/use-case/grand-theft-auto-v-highlights)); "action and reaction cues", "chaos spikes", voice "Clip it!"; 9:16 crop keeping the facecam; skips streams < 30 min ([guide](https://blog.eklipse.gg/eklipse-news-and-guide/create-a-highlight-clip-eklipse.html)); $24.99/mo or $179.99/yr.
- **Spikes Studio** — animated captions, emojis ([spikes.studio](https://spikes.studio)); generic audio/activity signals per competitors ([Eklipse comparison](https://eklipse.gg/compare/eklipse-vs-spikes-studio/)).
- **Powder.gg** — game-specific detection for 40+ games, audio "heightened emotions" fallback ([FileHorse](https://filehorse.com/download-powder)); operating status disputed ([Eklipse](https://blog.eklipse.gg/tools/eklipse-vs-powder-gg.html)).

### 3.2 Feature matrix

Y = advertised, ? = unverified, blank = not advertised.

| Tool | Transcript/LLM | Visual | Game events | Score | Face reframe | Gaming layout | Animated captions | Emoji | B-roll | SFX/zoom | Silence cut | Prompt search | Entry price |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| OpusClip | Y | Y | partial | 0-99 | Y | ? | Y | Y | Y | ? | ? | Y | ~$15 |
| Klap | Y | ? | | Y | Y | Y | Y | ? | | | | Y | $14.50 |
| Vizard | Y | ? | | Y | Y | Y | Y | ? | ? | ? | ? | ? | free/~$16 |
| Submagic | Y | | | | ? | | Y | Y | Y | Y | Y | | ~$19+ |
| Descript | Y | partial | | | ? | | Y | | | | Y | Y | plan |
| Riverside | Y | | | 70-99 | Y | | Y | | | | | | plan |
| Captions.ai | Y | | | | Y | | Y | ? | ? | ? | ? | | plan |
| VEED | Y | | | Y | ? | | Y | | | | Y | | plan |
| Pictory | Y | | | | | | Y | | Y | | | | ~$25 |
| Kapwing | Y | | | | ? | | Y | | | | Y | | plan |
| 2short.ai | Y | | | | Y | | Y | | | | | | $9.90 |
| quso.ai | Y | ? | | Y? | Y | ? | Y | ? | ? | ? | ? | ? | plan |
| Eklipse | | Y | **Y** | | Y | Y | Y | Y | | Y | | voice | $14.99 |
| Spikes | Y | ? | generic | ? | ? | ? | Y | Y | | | | | ~$10-29 |
| Powder | | Y | **Y** | | ? | ? | Y | | | | | | $9.99? |

### 3.3 What to copy (MVP) and where to improve

Copy: ranked list with an explainable 0-100 score (OpusClip's Hook/Flow/Value/Trend rubric in the LLM prompt); word-level animated captions (80% of viral clips); silence trimming; layout presets (face-track, action-crop); game-event detection from audio + motion (Eklipse/Powder approach); return fewer clips when the source is short (Riverside's ~2 per 5 min).

Improve: show per-signal contributions and make weights editable per niche (commercial scores are hidden and distrusted); keep signal vectors per clip so weights can be refit from real analytics; treat gameplay as a first-class subject (track motion, not faces); snap to sentence boundaries; pre-export policy checks (violence in first 7 s, licensed radio, too-little-original-edit).

---

## 4. How GTA and MrBeast clip channels edit

### 4.1 GTA

- **GTA 6 release**: Thursday **2026-11-19** ([Rockstar Newswire](https://www.rockstargames.com/newswire/article/ak3ak31a49a221/grand-theft-auto-vi-is-now-set-to-launch-november-19-2026)); reconfirmed in Take-Two's 2026-11-09 earnings release ("ten days away", [SEC 8-K](https://www.sec.gov/Archives/edgar/data/0000946581/000162828026072175/ttwo2q27earningsrelease.htm)); PS5 / Xbox Series X|S only, no PC date ([GameLuster](https://gameluster.com/gta-6-release-date-2/)). Trailer 2 drew 475M views in 24 h ([TechRadar](https://www.techradar.com/gaming/the-latest-grand-theft-auto-6-trailer-has-set-a-major-record-by-racking-up-475-million-views-in-just-24-hours)). **No public gameplay yet → the `gta6` profile is tuned on GTA V footage and hard-codes no on-screen banners.**
- **Policy**: YouTube gaming-violence ad rules (first 7 s, shock compilations) — see §1.1; Rockstar permits occasional non-commercial fan use ([video policy](https://support.rockstargames.com/articles/200153756/rockstar-games-video-policy)); in-game radio = Content ID risk. **Rule: open on a chase, stunt, ragdoll or glitch, never on a kill.**
- **Moments**: Eklipse's list (5-star chases, ramp stunts, heist getaways, airborne wrecks, NPC chaos, jet dogfights, crashes, near-misses); ragdoll fails, physics glitches, NPC reactions, mod chaos, RP drama (creator-observed). For streamer footage the peak is often "a face or a voice at maximum energy" (vendor claim, [ClipSpeed](https://clipspeed.ai/gta6/turn-gta-6-gameplay-into-viral-shorts.html)).
- **Length and pacing**: 15-35 s default (OpusClip data; [Hootsuite](https://blog.hootsuite.com/social-media-video-length/)); 61-90 s variant for TikTok rewards ([Buffer](https://buffer.com/resources/longer-tiktoks-get-more-views-data/): > 60 s got +43% reach); escalate — second-best moment first, best last (vendor advice); "wait for it" structure: ~1 s setup with text hook, cut to 2-5 s before payoff, hold 1-2 s on reaction, hard cut (creator-observed).
- **Layout, captions, audio**: centre/action crop for pure gameplay; facecam on top + game below for streams, keep minimap clear, record ≥ 1440p ([dor.gg](https://clip.dor.gg/en/blog/record-game-vertical-shorts)); bold 1-3 word captions because gaming is watched muted ([Eklipse](https://blog.eklipse.gg/basic-knowledge/common-vertical-video-mistakes-streamers-fix.html)); frame-1 hook text ("WAIT FOR IT 💀", creator-observed); keep game SFX as the main track ([Eklipse](https://blog.eklipse.gg/streaming-tips-2/gta-edits-montages.html)).

### 4.2 MrBeast

- **2024 leaked production doc** (36 pages, posted by Rosanna Pansino, authenticity not independently confirmed — [NetInfluencer](https://www.netinfluencer.com/mrbeast-productions-leaked-internal-document-rosanna-pansino/)). Quotes ([transcript](https://www.alexanderjarvis.com/memo-how-to-succeed-in-mrbeast-production/), [Creator Handbook](https://www.creatorhandbook.net/leaked-document-allegedly-reveals-mrbeasts-secrets-to-youtube-success-the-key-takeaways/), [Tubefilter](https://www.tubefilter.com/2024/09/17/mrbeast-internal-production-guide-leaked-key-points/amp/)): "The first minute of each video is the most important minute"; "We lost 21 million viewers in the first minute"; re-engagement at 3 and 6 minutes; "As you get deeper in the video the stakes get higher"; core metrics CTR, AVD, AVP; "never lose our wow"; title/thumbnail set expectations; "the more extreme, the better." For Shorts the first 1-3 s plays the role of his first minute (inference).
- **Retention ideas**: pacing = speed of progressive novel information ([Mario Joos via Vidpros](https://vidpros.com/retention-editing-what-you-can-learn-from-mario-joos/)); "but/therefore" rule from Parker & Stone ([Cheat Sheet](https://www.cheatsheet.com/entertainment/south-park-trey-parker-and-matt-stone-1-rule.html/)) → score causal/contrast connectives.
- **What gets clipped** (creator-observed): money reveals and counts, eliminations, "last to leave" exits, twists, huge reactions, giveaways, before/after, "$1 vs $X."
- **Rights and reach**: MrBeast encouraged reposting his videos as Shorts (Jan 2025, [Dexerto](https://dexerto.com/youtube/mrbeast-encourages-youtubers-to-repost-his-content-after-stealing-videos-poll-3024810)) — **but** YouTube's Oct 2026 originality update cuts reach for template edits ([Dexerto](https://www.dexerto.com/youtube/youtube-cracks-down-on-clipping-channels-in-shorts-update-prioritizing-original-content-3415700/)) → add commentary/voiceover. Vyro pays ~$3/1k views per brief (OpusClip's report, [link](https://www.opus.pro/blog/mrbeasts-vyro)); fan stat: Shorts passed 47.3B views ([Tribune](https://tribune.com.pk/story/2564552/mrbeasts-youtube-shorts-surpass-long-form-videos-in-total-views), unofficial).
- **Captions and titles**: Hormozi-style 1-3 words, ALL CAPS, heavy sans, white with yellow/green active word and thick stroke ([Choppity](https://www.choppity.com/tools/recreate-video-editing-style/alex-hormozi/)); title formats "$1 vs $1,000,000", "Last To Leave", "I Survived 50 Hours", "Ages 1-100"; thumbnails: dominant faces, high contrast, specific numbers ([Alici](https://alici.ai/blog/mrbeast-thumbnails-patterns-2026)). Length 30-60 s (setup + payoff), inference.

### 4.3 General short-form heuristics

- Official limits: Shorts 3 min ([YouTube](https://support.google.com/youtube/answer/15424877)); Reels 3 min ([SMT](https://www.socialmediatoday.com/news/instagram-officially-expands-reels-length-to-3-minutes/737766/)).
- Hook: first 3 s proposition, hook within 6 s (TikTok ads guidance, [Marketing Brew](https://www.marketingbrew.com/stories/2023/12/18/pay-attention-to-me-report-shares-brand-tips-for-catching-users-interest-on-tiktok)); "strong hook from the very first second" ([TikTok Newsroom](https://newsroom.tiktok.com/scroll-stopping-tips-from-top-tiktok-creators?lang=en-GB)); YouTube's viewed-vs-swiped is the hook metric, 75-80% figures are creator-reported ([Creator Essentials](https://www.creatoressentials.com/glossary/viewed-vs-swiped-away/)).
- Length data: Buffer (1.1M TikToks) > 60 s → +43% reach, +64% watch time; Socialinsider: ~30 s best engagement rate, 2-3 min most views ([Socialinsider](https://www.socialinsider.io/blog/how-long-are-tiktok-videos/)); OpusClip: 15-30 s overrepresented. **Takeaway: 20-35 s cut by default, long variant later.**
- Captions: 80% of viral clips captioned (OpusClip); word-by-word vs sentence has no controlled evidence ([BlitzCut](https://blitzcutai.com/blog/word-by-word-captions-vs-full-sentence-captions)).
- Loops: counted as views since 2025-03-31; no platform confirms loops raise ranking ([CapCut](https://www.capcut.com/create/short-form-video-loop-count)).
- creator-observed: jump cuts every 2-4 s; 110-120% punch-ins on reactions; remove gaps > 0.3-0.5 s; visual change every 2-3 s.
- Hashtags: YouTube shows 3 above the title and ignores all if > 60 ([YouTube Help](https://support.google.com/youtube/answer/6390658)); Instagram reportedly 5 ([Later](https://later.com/blog/instagram-hashtags/amp)); TikTok niche + generic mix (OpusClip, correlational).

---

## 5. Derived scoring profiles, hooks, titles and hashtags

These are starting priors to be refit from the user's own analytics. Weights are 0-1; signals are normalized 0-1 per video; penalties are negative. Rows marked v2 are declared in the profile yaml with weight 0 so the schema is stable.

| Signal (how computed) | gta6 | mrbeast | MVP |
|---|---|---|---|
| audio_peak (RMS/onset spikes vs rolling median) | 0.80 | 0.55 | yes |
| motion_intensity (frame-diff magnitude) | 0.85 | 0.30 | yes |
| scene_cut_density (cuts per 10 s) | 0.50 | 0.40 | yes |
| event_density (motion + audio + cut spikes within 1 s) | 0.90 | 0.20 | yes |
| speech_excitement (RMS during speech, words/sec) | 0.60 | 0.85 | yes |
| laughter_shout (band-limited RMS spikes; AudioSet classes v2) | 0.70 | 0.80 | heuristic |
| keyword_hits (profile keyword list) | 0.45 | 0.75 | yes |
| money_number_mentions ("$", "million", counts) | 0.05 | 0.90 | regex |
| twist_connectives ("but", "until", "then", "suddenly") | 0.25 | 0.70 | regex |
| payoff_in_window (peak in the last 40%) | 0.70 | 0.65 | yes |
| hook_strength (first 3 s energy relative to window) | 0.60 | 0.60 | yes |
| sentence_boundary_bonus | 0.30 | 0.70 | yes |
| length_prior (gaussian; gta6 μ=25 σ=10, mrbeast μ=45 σ=12) | 0.40 | 0.40 | yes |
| silence_penalty (dead air seconds) | -0.60 | -0.80 | yes |
| violence_first7s (violence keywords/event spike in first 7 s) | -0.70 | -0.10 | heuristic |
| face_reaction | 0.55 | 0.85 | v2 |
| ocr_banner (WASTED/BUSTED/stars) | 0.75 | 0.00 | v2 |
| audio_event_class (AudioSet) | 0.90 | 0.20 | v2 |
| llm_hook_flow_value_trend (OpusClip rubric) | 0.50 | 0.80 | when API key present |

Length targets: gta6 15-35 s (61-90 s compilation variant later); mrbeast 30-60 s.

Hook templates (all creator-observed; patterns: curiosity_gap, shock, wait_for_it, bold_claim, open_loop) and title templates live in `profiles/gta6.yaml` and `profiles/mrbeast.yaml`. Hashtag sets per platform:

| Platform | gta6 | mrbeast |
|---|---|---|
| YouTube Shorts (3 shown) | #GTA6 #GTA #Shorts | #MrBeast #Shorts #Challenge |
| TikTok (5-10, niche + generic) | #gta6 #gta #gtavi #gtaonline #gaming #gamingclips #fyp #viral | #mrbeast #mrbeastchallenge #challenge #money #reaction #fyp #viral #foryou |
| Instagram Reels (≤ 5) | #gta6 #gta #gaming #gamer #reels | #mrbeast #challenge #money #reaction #reels |
| Facebook Reels (3-5) | #GTA6 #Gaming #Reels | #MrBeast #Challenge #Reels |

Hashtag co-occurrence source: [DisplayPurposes #gta6](https://displaypurposes.com/hashtags/hashtag/gta6). No TikTok view totals for GTA tags were found.

## Gaps

- The original TeamYouTube Oct 2026 post and the Creator Insider video were not fetched directly.
- TikTok publishes no guidance on watermarks, resolution or ideal length.
- The Instagram Reels system card on transparency.meta.com returned 404 at research time.
- Some licences (PANNs, laughter-detection, Qwen weights) and ffmpeg loudnorm defaults were not verified on a primary page.

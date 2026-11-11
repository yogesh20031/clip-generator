"""Command line entry point. `viral-clipper` with no arguments starts the MCP server."""

from __future__ import annotations

import argparse
import json
import sys

from rich.console import Console
from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn
from rich.table import Table

from viral_clipper import pipeline
from viral_clipper.config import get_config, list_profiles
from viral_clipper.errors import ClipperError
from viral_clipper.log import setup_logging
from viral_clipper.metadata import outputs
from viral_clipper.models import ALL_PLATFORMS, Platform

console = Console(stderr=True)


def _progress_bar():
    return Progress(
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        TextColumn("{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        TextColumn("[dim]{task.fields[msg]}"),
        console=console,
        transient=False,
    )


def _with_bar(label: str, fn, *args, **kwargs):
    with _progress_bar() as bar:
        task = bar.add_task(label, total=100, msg="")

        def progress(frac: float, msg: str) -> None:
            bar.update(task, completed=frac * 100, msg=msg[:60])

        return fn(*args, **kwargs, progress=progress)


def cmd_clip(args: argparse.Namespace) -> int:
    cfg = get_config()
    req = pipeline.ClipRequest(
        source=args.source,
        niche=args.niche,
        num_clips=args.num_clips,
        min_len=args.min_len,
        max_len=args.max_len,
        platforms=[Platform(p) for p in args.platforms] if args.platforms else list(ALL_PLATFORMS),
        output_dir=args.output_dir,
    )
    result = _with_bar("clip_video", pipeline.run_clip_video, req, cfg)
    table = Table(title=f"{result.video_title} — {len(result.clips)} clips → {result.output_dir}")
    table.add_column("#", justify="right")
    table.add_column("time")
    table.add_column("score", justify="right")
    table.add_column("hook")
    table.add_column("why")
    for c in result.clips:
        table.add_row(str(c.index), f"{c.start:.0f}-{c.end:.0f}s", f"{c.score:.0f}", c.hook, "; ".join(c.reasons[:2]))
    console.print(table)
    for w in result.warnings:
        console.print(f"[yellow]warning:[/] {w}")
    console.print(f"[dim]timings: {result.timings_s}[/]")
    print(result.clips_json)
    return 0


def cmd_analyze(args: argparse.Namespace) -> int:
    summary = _with_bar("analyze_video", pipeline.run_analyze, args.source, get_config(), force=args.force)
    print(summary.model_dump_json(indent=2))
    return 0


def cmd_score(args: argparse.Namespace) -> int:
    req = pipeline.ClipRequest(
        source=args.source, niche=args.niche, num_clips=args.num_clips, min_len=args.min_len, max_len=args.max_len
    )
    selected = _with_bar("score_moments", pipeline.run_score, req, get_config())
    print(json.dumps([c.model_dump(exclude={"contributions"}) for c in selected], indent=2))
    return 0


def cmd_cut(args: argparse.Namespace) -> int:
    record = _with_bar(
        "cut_clip",
        pipeline.run_cut_clip,
        args.source,
        args.start,
        args.end,
        args.duration,
        get_config(),
        niche=args.niche,
        hook=args.hook,
        platforms=[Platform(p) for p in args.platforms] if args.platforms else None,
        output_dir=args.output_dir,
    )
    console.print(
        f"[bold]{record.path}[/]  {record.start:.0f}-{record.end:.0f}s  score {record.score:.0f}  hook: {record.hook}"
    )
    print(record.path)
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    cfg = get_config()
    root = pipeline._with_output_dir(cfg, args.output_dir).output_root
    for entry in outputs.list_outputs(root):
        console.print(f"[bold]{entry.video_title}[/] — {entry.clip_count} clips — {entry.output_dir}")
        for c in entry.clips:
            console.print(f"  {c.index:02d} {c.start:6.1f}-{c.end:6.1f}s  {c.score:5.1f}  {c.hook}")
    return 0


def cmd_serve(_args: argparse.Namespace) -> int:
    from viral_clipper.server import main as serve

    serve()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="viral-clipper", description="Cut viral short clips, locally.")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("serve", help="run the MCP server over stdio (default)").set_defaults(func=cmd_serve)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("source", help="YouTube URL or local video path")
        p.add_argument("--niche", default="generic", choices=list_profiles())
        p.add_argument("--num-clips", type=int, default=10)
        p.add_argument("--min-len", type=float, default=30)
        p.add_argument("--max-len", type=float, default=70)

    p = sub.add_parser("clip", help="analyze, score, cut and write metadata")
    common(p)
    p.add_argument("--platforms", nargs="*", choices=[pl.value for pl in ALL_PLATFORMS])
    p.add_argument("--output-dir")
    p.set_defaults(func=cmd_clip)

    p = sub.add_parser("analyze", help="transcript, scene cuts, audio peaks, curves")
    p.add_argument("source")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser("score", help="ranked moments without rendering")
    common(p)
    p.set_defaults(func=cmd_score)

    p = sub.add_parser("cut", help="cut one clip from an exact range (seconds or mm:ss)")
    p.add_argument("source")
    p.add_argument("--start", required=True)
    p.add_argument("--end")
    p.add_argument("--duration")
    p.add_argument("--niche", default="generic", choices=list_profiles())
    p.add_argument("--hook", help="your own on-screen hook text")
    p.add_argument("--platforms", nargs="*", choices=[pl.value for pl in ALL_PLATFORMS])
    p.add_argument("--output-dir")
    p.set_defaults(func=cmd_cut)

    p = sub.add_parser("list", help="show saved clips")
    p.add_argument("--output-dir")
    p.set_defaults(func=cmd_list)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.command is None:
        args.func = cmd_serve
    if args.command not in (None, "serve"):
        cfg = get_config()
        setup_logging(cfg.log_dir, cfg.log_level)
    try:
        sys.exit(args.func(args))
    except ClipperError as exc:
        console.print(f"[red]error:[/] {exc.user_message()}")
        sys.exit(2)


if __name__ == "__main__":
    main()

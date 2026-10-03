"""Command-line interface (the GUI is the main entry point; this is for scripting)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .engine import Engine, extract_zip, items_from_packs
from .model import LABELS, MODELS
from .paths import data_dir
from .policy import CENSOR_STYLES, PRESETS_BY_KEY, Settings, top_label
from .scanner import CATEGORIES


def _progress(done: int, total: int, msg: str) -> None:
    if sys.stderr.isatty():
        sys.stderr.write(f"\r{msg} ({done}/{total})   ")
        sys.stderr.flush()


def _settings(args) -> Settings:
    s = Settings.load(data_dir() / "settings.json")
    if args.preset:
        s.apply_preset(args.preset)
    if args.min_level:
        s.min_level, s.preset = args.min_level, "custom"
    if args.strictness is not None:
        s.strictness, s.preset = args.strictness, "custom"
    if args.categories:
        s.categories = args.categories
    if getattr(args, "style", None):
        s.style = args.style
    if getattr(args, "copy_to", None):
        s.output_mode, s.copy_destination = "copy", str(args.copy_to)
    elif hasattr(args, "copy_to"):
        s.output_mode = "inplace"
    if args.model:
        s.model = args.model
    return s


def _resolve_inputs(paths: list[Path], extract_to: Path | None) -> list[Path]:
    out = []
    for p in paths:
        if p.is_file() and p.suffix.lower() == ".zip":
            dest = extract_to or p.parent
            print(f"Extracting {p.name} -> {dest}", file=sys.stderr)
            out.append(extract_zip(p, dest))
        else:
            out.append(p)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="packfilter-cli",
                                     description="Censor sexualized cover art in rhythm game song packs.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name, help_ in (("scan", "report what would be censored"), ("apply", "censor flagged images"),
                        ("restore", "put original images back")):
        p = sub.add_parser(name, help=help_)
        p.add_argument("paths", nargs="+", type=Path, help="pack folders, Songs folders or .zip files")
        p.add_argument("--preset", choices=sorted(PRESETS_BY_KEY))
        p.add_argument("--min-level", choices=LABELS[1:])
        p.add_argument("--strictness", type=int, help="0-100, higher censors more (default 50)")
        p.add_argument("--categories", nargs="+", choices=CATEGORIES)
        p.add_argument("--model", choices=sorted(MODELS))
        p.add_argument("--extract-to", type=Path, help="where to extract .zip packs (default: next to the zip)")
        p.add_argument("--json", action="store_true", help="print machine-readable results")
        if name == "apply":
            p.add_argument("--style", choices=CENSOR_STYLES)
            p.add_argument("--copy-to", type=Path, help="write censored copies here instead of editing in place")
    args = parser.parse_args(argv)

    settings = _settings(args)
    engine = Engine()
    packs = engine.collect(_resolve_inputs(args.paths, args.extract_to))
    items = items_from_packs(packs)
    if not items:
        print("No images found.", file=sys.stderr)
        return 1
    engine.classify(items, settings.model, _progress)
    if sys.stderr.isatty():
        sys.stderr.write("\n")

    if args.cmd == "apply":
        res = engine.apply(items, settings, _progress)
        print(f"Censored {res.censored} image(s); {len(res.errors)} error(s).", file=sys.stderr)
        for e in res.errors:
            print("  " + e, file=sys.stderr)
    elif args.cmd == "restore":
        res = engine.restore(items, _progress)
        print(f"Restored {res.restored} image(s); {len(res.errors)} error(s).", file=sys.stderr)

    rows = []
    for it in items:
        rows.append({
            "path": str(it.path), "pack": it.pack, "song": it.song, "categories": sorted(it.categories),
            "scores": it.scores, "rating": top_label(it.scores) if it.scores else None,
            "lewd_score": round(settings.lewd_score(it.scores), 4) if it.scores else None,
            "flagged": settings.should_censor(it.scores, it.categories),
            "censored": it.censored, "error": it.error,
        })
    if args.json:
        json.dump(rows, sys.stdout, indent=2)
        print()
    else:
        flagged = [r for r in rows if r["flagged"]]
        for r in rows:
            mark = "CENSORED" if r["censored"] else ("FLAG" if r["flagged"] else "ok")
            rating = r["rating"] or ("error" if r["error"] else "-")
            print(f"{mark:8} {rating:12} {r['lewd_score'] if r['lewd_score'] is not None else '':<7} "
                  f"[{','.join(r['categories'])}] {r['pack']} / {r['song']} :: {Path(r['path']).name}")
        print(f"\n{len(rows)} images in {len(packs)} pack(s); {len(flagged)} match the current settings "
              f"({settings.preset}, threshold {settings.threshold:.2f} on '{settings.min_level}' and up).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

# Pack Filter

Hide lewd cover art in rhythm game song packs.

Drop in your Etterna packs, as folders or downloaded `.zip` files. Pack Filter checks every
banner, background, jacket, CD title and pack banner with the
[`anime_dbrating`](https://huggingface.co/deepghs/anime_dbrating) model. Then you click
**Download** and get a filtered `.zip` of each pack in your Downloads folder (or a folder you
choose), with the covers you don't want censored. You decide how strict it is, from
"a bit suggestive" up to only outright hentai. Your original packs are never modified.

Runs on **Windows, macOS and Linux**, the same platforms as Etterna. It also works with StepMania
and ITG packs, osu! beatmap folders, Quaver, K-Shoot and BMS, and for anything it doesn't recognize
it scans every image in the folder.

## Features

- **Drag and drop.** Drop pack folders, your whole `Songs` folder, or downloaded `.zip` packs
  into the window. Zips are unpacked to a temporary folder that's cleaned up when you quit.
- **One filtered zip per pack.** Clicking **Download N filtered packs** saves `<Pack> (filtered).zip`
  files to Downloads, or to the folder shown next to the button. Each zip contains the whole pack
  (charts, audio, everything) with only the flagged images censored, and it extracts to a normal
  pack folder. Packs with nothing to censor are skipped unless you tick
  "Also save packs that had nothing to censor".
- **Choose what gets censored**
  - **Strict**: also hides suggestive covers (swimsuits, underwear, revealing outfits).
  - **Balanced** (default): hides clearly sexualized covers and anything explicit.
  - **Explicit only**: hides only pornographic / hentai covers.
  - **Custom**: pick which ratings count as lewd and set a strictness slider.
  - Turn image types on or off: jackets, banners, backgrounds, CD titles, pack banners, other images.
  - Override single images (or a whole selection) with **Censor** / **Keep**.
- **Previews stay hidden.** Any thumbnail that might be lewd is blurred in the list. To see one,
  click "Show original".
- **Censor styles**: heavy blur, pixelate, solid color, or your own replacement image, with an
  optional "CENSORED" label. A live preview shows the result. Image size and file format stay the
  same, so the game doesn't notice anything changed.
- **Fast.** Runs on the CPU with ONNX Runtime and caches results, so a re-scan is almost
  instant. The default model is bundled, so it works offline. A larger "Accurate" model can be
  downloaded from the settings.

## Download

Get the latest build for your OS from the **Releases** page:

| OS | File | How to run |
|---|---|---|
| Windows | `PackFilter-*-windows-x64.zip` | Unzip, run `PackFilter.exe`. If SmartScreen warns you, click "More info" → "Run anyway". |
| macOS (Apple Silicon / Intel) | `PackFilter-*-macos-arm64.dmg` / `-x64.dmg` | Drag to Applications. The first time, macOS blocks it because it isn't notarized: go to **System Settings → Privacy & Security**, then click **Open Anyway**. |
| Linux | `PackFilter-*-linux-x64.tar.gz` | Extract and run `PackFilter/PackFilter`. Optionally run `install.sh` to add it to your app menu. |

## How to use

1. Open Pack Filter and drop in your packs, or click **Add packs**.
2. Wait for the scan to finish. The **Will censor** tab lists what will be blurred.
3. Adjust the settings on the right. The list updates instantly, with no re-scan.
4. Click **Download N filtered packs**. When it's done, click **Show in folder**.
5. Extract the filtered zips into your Etterna `Songs` folder, replacing the original packs if
   you already had them installed.

If Etterna still shows old covers, restart it. If they still don't change, delete the `Cache`
folder in your Etterna install so Etterna rebuilds its banner cache.

## Running from source

Requires Python 3.10+.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
packfilter                       # GUI
packfilter-cli scan ~/Etterna/Songs
```

### Command line

```bash
packfilter-cli scan    PATH...  [--preset strict|balanced|explicit] [--strictness 0-100] [--json]
packfilter-cli export  PATH...  [--to DIR] [--include-unchanged] [--style blur|pixelate|solid]
packfilter-cli apply   PATH...  # advanced: censor inside the packs, backing up originals
packfilter-cli restore PATH...  # undo `apply`, byte-for-byte
```

`PATH` can be a pack, a Songs folder, or a `.zip`.

### Building the standalone app

```bash
pip install -e ".[dev]"
python packaging/build.py        # creates dist/PackFilter-<version>-<os>-<arch>.*
```

PyInstaller can't cross-compile, so build each OS on that OS. The GitHub Actions workflow in
`.github/workflows/build.yml` builds and smoke-tests Windows, macOS (arm64 + Intel) and Linux on
every push. Push a `v*` tag to publish a release.

### Tests

```bash
pip install -e ".[dev,reference]"
pytest
```

`tests/test_real_model.py` is an end-to-end test. It builds Etterna-style packs whose covers are
the labelled sample images (general / sensitive / questionable / explicit, **NSFW**) that the
model's authors publish in the imgutils docs. It checks:

- explicit and sexual covers are flagged and clean packs are left alone
- the exported zips contain no image the model still rates as lewd
- the source packs are unchanged
- `apply` followed by `restore` gives back identical files

It also checks that our inference matches `imgutils.validate.anime_dbrating_score`.
`tools/make_test_packs.py OUT_DIR` generates the same packs so you can try the app by hand.
The sample images are downloaded on demand and never committed.

## How it works

- `scanner.py` finds songs by their chart files (`.sm`, `.ssc`, `.dwi`, `.osu`, `.qua`, `.ksh`,
  `.bms`, ...) and reads image tags (`#BANNER`, `#BACKGROUND`, `#JACKET`, `#CDTITLE`,
  `#BGCHANGES`, ...). Lookups are case-insensitive, like the games. Untagged images are
  categorized by filename.
- `model.py` runs the deepghs `anime_dbrating` ONNX model. It uses the same preprocessing as
  imgutils, without pulling in imgutils' heavy dependencies.
- `policy.py` computes a "lewdness" score: the probability mass of the ratings you count as lewd.
  It compares that against the strictness threshold.
- `store.py` keeps a SQLite cache of scores and content-addressed backups of originals, in
  `%APPDATA%\PackFilter`, `~/Library/Application Support/PackFilter`, or `~/.local/share/packfilter`.

The model gives a rough estimate, not a guarantee. Use **Censor** / **Keep** on single images
for anything it gets wrong.

## License

Pack Filter is MIT licensed. The bundled `anime_dbrating` model is by [deepghs](https://huggingface.co/deepghs) and is released under the OpenRAIL license.

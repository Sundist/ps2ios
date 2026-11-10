# ps-to-ios

Takes a **zip** of your own PS1 disc dump, recompiles the game's code ahead of
time to C with [psxrecomp](https://github.com/RetroPortingToolKit/psxrecomp),
and builds a **native, signed iPhone/iPad app** from it. No emulator and no JIT.
Graphics, sound and videos are read at run time from the disc image on the phone.

> This repository contains no game data and downloads none. Use it only with
> dumps of discs you own. psxrecomp is licensed under PolyForm Noncommercial
> 1.0.0, so the apps you build are for noncommercial use.

## How it works

```
game.zip ─► find the disc (cue/bin, chd, lone bin, iso; multi-disc sets)
        ─► SYSTEM.CNF → BOOT → PS-X EXE header → serial (e.g. SCES-00891)
        ─► project:  a curated profile if one exists (profiles/<SERIAL>.json),
                     otherwise psxrecomp's own scaffold (setup_project.sh)
        ─► recompile the game from the disc (psxrecomp generate)
        ─► iOS layer (ios/): Documents game folder, touch PS pad, MoltenVK
        ─► Xcode project → xcodebuild archive (automatic signing) → .ipa
        ─► (optional) install with devicectl + copy the disc to Documents/disc/
```

psxrecomp runs code in three tiers: ahead-of-time compiled code, overlays
compiled at run time, and a MIPS interpreter that is always correct. iOS does
not allow generating code at run time, so tier 2 is switched off. Code the
static pass did not find runs in the interpreter, which iOS allows. So **every
game should run correctly from the first build**. Games with a curated profile
are fully compiled ahead of time and run faster.

| Project kind | Games | Result |
|---|---|---|
| Curated | Hercules PAL: SCES-00891…00895 ([hercules-recompiled](https://github.com/obaidr1/hercules-recompiled)) | Full AOT, mods |
| Generic | Any other PS1 disc | Main EXE compiled, the rest interpreted; speed and compatibility vary by game |

To add a curated project, write `profiles/<SERIAL>.json` (repo, commit,
project folder, patches, GameData).

## Usage

Identifying a disc works anywhere, Linux included:

```bash
python3 -m ps1ios inspect "Game.zip"
```

Building the iPhone app needs a Mac:

```bash
python3 -m ps1ios build "Game.zip" --team TEAMID --human
```

With install and disc copy:

```bash
python3 -m ps1ios build "Game.zip" --team TEAMID --device <device-id> --human
```

Device id:

```bash
xcrun devicectl list devices
```

Options: `--name` (home screen name), `--bios SCPH1001.BIN` (optional;
OpenBIOS is used otherwise), `--generic` (ignore curated profiles),
`--bundle-prefix`, `--work`, `--out`. Without `--human`, progress is printed
as JSON lines in the format HookLink and NX2Apple parse.

### Mac requirements

- Xcode (iOS SDK) and an Apple Developer team ID (a free Personal Team works)
- `brew install cmake ninja git`, `pip3 install numpy pillow`
- LunarG Vulkan SDK (`glslc` + `MoltenVK.xcframework`), with `VULKAN_SDK` set
- iPhone: iOS 16+, Developer Mode on

## Files

| Path | What |
|---|---|
| `ps1ios/ingest.py` | Safe zip extraction (zip-slip, links, size caps), disc discovery, cue generation for lone bins, filename case fixes |
| `ps1ios/disc.py` | ISO9660 reading, SYSTEM.CNF, BOOT, PS-X EXE header, serial and region |
| `ps1ios/pipeline.py` | Curated/generic project, patches, generate, Xcode, signing, IPA, install |
| `ios/` | iOS layer: `ios_platform.mm` (Documents game folder, disc discovery, touch pad, run-time compile off), `ios.cmake`, `Info.plist.in`, psxrecomp patch |
| `profiles/` | Curated projects |
| `tests/` | Unit tests on synthetic discs (no game data) |

## Status

- Verified: zip ingestion, disc identification, curated/generic project
  selection, CLI. 10 tests on synthetic discs. The psxrecomp patch applies to
  both clean psxrecomp (2a4824f) and the Hercules-patched tree.
- **Not yet verified:** the iOS build on a Mac, signing, and running on a
  device. Things to check on the first Mac build: whether the desktop OpenGL
  renderer compiles for iOS (if not, it is switched off on iOS and
  Vulkan/MoltenVK or the software renderer is used), SDL3's iOS startup, and
  loading the embedded MoltenVK.
- Frame rate is capped by the game itself. Most PS1 games step at 30 or 60 Hz;
  the port does not raise that.
- PS1 only. Despite the repository name, PS2 games are not supported.

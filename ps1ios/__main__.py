"""ps1ios command line.

  python3 -m ps1ios inspect game.zip
  python3 -m ps1ios build game.zip --team ABCDE12345 [--device <id>] [--name "My Game"]
  python3 -m ps1ios build game.zip --target simulator --run-seconds 30
  python3 -m ps1ios build game.zip --unsigned
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile

from . import __version__
from .disc import DiscError, probe
from .events import Events
from .ingest import IngestError, ingest
from .pipeline import Build, PipelineError, load_profile


def cmd_inspect(a) -> int:
    with tempfile.TemporaryDirectory() as d:
        ing = ingest(a.zip, d)
        out = {"discs": [{"label": x.label, "entry": os.path.basename(x.entry),
                          "generated_cue": x.generated_cue} for x in ing.discs],
               "warnings": ing.warnings}
        if ing.primary.data_track:
            info = probe(ing.primary.data_track)
            out["disc"] = info.as_dict()
            prof = load_profile(info.serial)
            out["project"] = {"kind": "curated", "title": prof["title"], "source": prof["source"]} if prof \
                else {"kind": "generic", "note": "psxrecomp scaffold + interpreter for code not yet compiled"}
        print(json.dumps(out, indent=2))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="ps1ios", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("inspect", help="unpack the zip and identify the disc (works anywhere)")
    i.add_argument("zip")
    i.set_defaults(fn=cmd_inspect)
    b = sub.add_parser("build", help="build a signed iPhone app from the zip (macOS + Xcode)")
    b.add_argument("zip")
    b.add_argument("--team", default=os.environ.get("PS1IOS_TEAM", ""), help="Apple Developer team ID")
    b.add_argument("--device", default=os.environ.get("PS1IOS_DEVICE", ""), help="devicectl device id: install + copy disc")
    b.add_argument("--name", default="", help="home screen name (default: curated title or serial)")
    b.add_argument("--serial", default="", help="override the serial read from the disc")
    b.add_argument("--bundle-id", default="", help="explicit bundle id")
    b.add_argument("--bundle-prefix", default="", help="bundle id prefix, e.g. your name (default ps1ios)")
    b.add_argument("--bios", default="", help="optional retail BIOS (SCPH1001.BIN); OpenBIOS is used otherwise")
    b.add_argument("--generic", action="store_true", help="ignore curated profiles")
    b.add_argument("--work", default="build", help="work folder (default ./build)")
    b.add_argument("--out", default="", help="folder for the .ipa (default: work folder)")
    b.add_argument("--target", choices=["device", "simulator"], default="device",
                   help="device (iPhone) or the iOS simulator (no Apple account needed)")
    b.add_argument("--unsigned", action="store_true",
                   help="device build without signing: an IPA for AltStore/Sideloadly to re-sign")
    b.add_argument("--renderer", choices=["auto", "vulkan", "software"], default="auto",
                   help="vulkan = MoltenVK/Metal (needs the Vulkan SDK); software = CPU renderer; auto picks vulkan if found")
    b.add_argument("--run-seconds", type=int, default=0,
                   help="simulator: start the game, wait this long, save a screenshot")
    b.add_argument("--human", action="store_true", help="readable progress instead of JSON lines")
    b.set_defaults(fn=None)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "inspect":
            return cmd_inspect(a)
        ev = Events(human=a.human)
        ipa = Build(a, ev).run()
        ev.say(f"Done: {ipa}")
        return 0
    except (IngestError, DiscError, PipelineError) as e:
        print(f"ps1ios: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

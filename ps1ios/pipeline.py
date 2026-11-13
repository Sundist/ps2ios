"""zip -> recompiled psxrecomp project -> signed iOS app -> (optional) iPhone.

Two project sources:
  curated  profiles/<SERIAL>.json names a hand-tuned psxrecomp project (pinned
           commit) for that disc. Best result: full AOT, mods.
  generic  any other disc: psxrecomp's own scaffold (setup_project.sh) makes a
           project from the disc (identity, boot EXE, first-pass seeds) and
           generates its C. Code the static pass did not find runs in
           psxrecomp's built-in MIPS interpreter, which iOS allows (no JIT),
           so the game is correct from the first build and gets faster as
           more of it is compiled ahead of time.
"""
from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
import sys

from . import disc as discmod
from .events import Events
from .ingest import ingest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IOS_DIR = os.path.join(HERE, "ios")
PROFILES = os.path.join(HERE, "profiles")
PSXRECOMP_REPO = "https://github.com/RetroPortingToolKit/psxrecomp"
PSXRECOMP_PIN = "2a4824fcb897cb635438958f0c8cffb5a27df656"


class PipelineError(Exception):
    pass


def run(cmd: list[str], ev: Events, cwd: str | None = None, env: dict | None = None, quiet=False) -> None:
    ev.say("$ " + " ".join(cmd))
    e = dict(os.environ, **(env or {}))
    p = subprocess.Popen(cmd, cwd=cwd, env=e, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    tail = []
    for line in p.stdout:
        line = line.rstrip("\n")
        tail = (tail + [line])[-120:]
        if not quiet or re.search(r"error|warning: .*ps1ios|\*\* ", line, re.I):
            ev.say(line)
    if p.wait() != 0:
        if quiet:
            for t in tail:
                ev.say(t)
        raise PipelineError(f"{os.path.basename(cmd[0])} failed (exit {p.returncode})")


def git_clone(url: str, commit: str, dest: str, ev: Events) -> None:
    if not os.path.isdir(os.path.join(dest, ".git")):
        run(["git", "clone", "--quiet", url, dest], ev)
    run(["git", "-C", dest, "checkout", "--quiet", commit], ev)
    run(["git", "-C", dest, "submodule", "update", "--init", "--recursive", "--quiet"], ev)


def apply_patch(repo: str, patch: str, ev: Events) -> None:
    ok = subprocess.run(["git", "-C", repo, "apply", "--check", patch], capture_output=True).returncode == 0
    if ok:
        run(["git", "-C", repo, "apply", patch], ev)
        return
    if subprocess.run(["git", "-C", repo, "apply", "--check", "-R", patch], capture_output=True).returncode == 0:
        ev.say(f"already applied: {os.path.basename(patch)}")
        return
    raise PipelineError(f"patch does not apply: {patch}")


def load_profile(serial: str | None) -> dict | None:
    if not serial:
        return None
    p = os.path.join(PROFILES, f"{serial}.json")
    if not os.path.exists(p):
        return None
    with open(p) as f:
        return json.load(f)


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "game"


def find_moltenvk() -> str | None:
    sdk = os.environ.get("VULKAN_SDK", "")
    for c in (f"{sdk}/iOS/lib/MoltenVK.xcframework", f"{sdk}/macOS/lib/MoltenVK.xcframework",
              f"{sdk}/../iOS/lib/MoltenVK.xcframework"):
        if sdk and os.path.isdir(c):
            return os.path.abspath(c)
    return None


def find_glslc() -> str | None:
    p = shutil.which("glslc")
    if p:
        return p
    sdk = os.environ.get("VULKAN_SDK", "")
    for c in (f"{sdk}/bin/glslc", f"{sdk}/macOS/bin/glslc"):
        if sdk and os.access(c, os.X_OK):
            return c
    return None


def set_toml_key(path: str, section: str, key: str, value: str) -> None:
    """Sets `key = "value"` in [section] of a TOML file (adds the section or key if missing)."""
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    out, inside, done = [], False, False
    line = f'{key} = "{value}"'
    for ln in lines:
        st = ln.strip()
        if st.startswith("[") and st.endswith("]"):
            if inside and not done:
                out.append(line)
                done = True
            inside = st == f"[{section}]"
        elif inside and re.match(rf"{re.escape(key)}\s*=", st):
            out.append(line)
            done = True
            continue
        out.append(ln)
    if inside and not done:
        out.append(line)
        done = True
    if not done:
        out += ["", f"[{section}]", line]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")


def set_toml_renderer(path: str, renderer: str) -> None:
    set_toml_key(path, "video", "renderer", renderer)


class Build:
    def __init__(self, args, ev: Events):
        self.a = args
        self.ev = ev
        self.work = os.path.abspath(args.work)
        os.makedirs(self.work, exist_ok=True)

    # ------------------------------------------------------------ stages
    def check_mac(self) -> None:
        missing = [t for t in ("xcodebuild", "xcrun", "cmake", "ninja", "git", "python3") if not shutil.which(t)]
        if missing:
            raise PipelineError("missing on this Mac: " + ", ".join(missing)
                                + " (Xcode from Apple; brew install cmake ninja git)")
        try:
            import numpy, PIL  # noqa: F401  (psxrecomp's generate needs them)
        except ImportError:
            raise PipelineError("python3 needs numpy and Pillow: pip3 install numpy pillow")
        self.signed = self.a.target == "device" and not self.a.unsigned
        if self.signed and not self.a.team:
            raise PipelineError("--team (Apple Developer team ID) is required to sign; "
                                "or use --unsigned (IPA for AltStore/Sideloadly) or --target simulator")
        self.glslc = find_glslc()
        self.mvk = find_moltenvk()
        have_vk = bool(self.glslc and self.mvk)
        if self.a.renderer == "vulkan" and not have_vk:
            raise PipelineError("--renderer vulkan needs LunarG's Vulkan SDK (glslc + MoltenVK) with VULKAN_SDK set")
        self.renderer = self.a.renderer if self.a.renderer != "auto" else ("vulkan" if have_vk else "software")
        if self.a.renderer == "auto" and not have_vk:
            self.ev.say("Vulkan SDK not found: building with the software renderer (set VULKAN_SDK for Vulkan/Metal)")
        out = subprocess.run(["xcodebuild", "-version"], capture_output=True, text=True).stdout.splitlines()
        self.ev.say(out[0] if out else "xcodebuild")

    def ingest(self):
        dest = os.path.join(self.work, "disc")
        if os.path.isdir(dest):
            shutil.rmtree(dest)
        res = ingest(self.a.zip, dest)
        for w in res.warnings:
            self.ev.say("warning: " + w)
        return res

    def probe(self, ing):
        d = ing.primary
        if not d.data_track:
            self.ev.say("CHD: identity is read by psxrecomp during generate")
            return None
        info = discmod.probe(d.data_track)
        with open(os.path.join(self.work, "disc_probe.json"), "w") as f:
            json.dump(info.as_dict(), f, indent=2)
        return info

    def project_curated(self, prof: dict, ing) -> str:
        src = os.path.join(self.work, "src", slug(prof["serial"]))
        git_clone(prof["source"]["repo"], prof["source"]["commit"], src, self.ev)
        recomp = os.path.join(src, prof["psxrecomp_dir"])
        for p in sorted(glob.glob(os.path.join(src, prof.get("patches_dir", "-"), "*.patch"))):
            apply_patch(recomp, p, self.ev)
        proj = os.path.join(src, prof["project_dir"])
        # Stage the disc where the project's game.toml expects it (disc/<redump name>).
        ddir = os.path.join(proj, "disc")
        os.makedirs(ddir, exist_ok=True)
        disc_dir = os.path.dirname(ing.primary.entry)
        for f in os.listdir(disc_dir):
            link = os.path.join(ddir, f)
            if not os.path.exists(link):
                os.symlink(os.path.join(disc_dir, f), link)
        self.recomp_dir = recomp
        return proj

    def project_generic(self, name: str, serial: str | None, ing) -> str:
        recomp = os.path.join(self.work, "psxrecomp")
        git_clone(PSXRECOMP_REPO, PSXRECOMP_PIN, recomp, self.ev)
        repo = slug(f"{name}-{serial or 'game'}")
        parent = os.path.join(self.work, "src")
        os.makedirs(parent, exist_ok=True)
        proj = os.path.join(parent, repo)
        if not os.path.isdir(proj):
            # The scaffold adds psxrecomp as a submodule by branch name; point it at
            # the local clone with a branch on the pinned commit.
            run(["git", "-C", recomp, "branch", "-f", "ps1ios-pin", PSXRECOMP_PIN], self.ev)
            env = {"PSXRECOMP_URL": recomp, "GIT_CONFIG_COUNT": "1",
                   "GIT_CONFIG_KEY_0": "protocol.file.allow", "GIT_CONFIG_VALUE_0": "always"}
            cmd = ["sh", os.path.join(recomp, "tools/new_project_layout/setup_project.sh"), "--yes",
                   "--name", name, "--disc", os.path.abspath(ing.primary.entry), "--dir", parent,
                   "--github-repo", repo, "--players", "1", "--psxrecomp-ref", "ps1ios-pin",
                   "--no-recomp-ui", "--no-netplay", "--no-wizard", "--no-ci", "--no-fetch-boxart",
                   "--no-github", "--no-build", "--generate"]
            if self.a.bios:
                cmd += ["--bios", os.path.abspath(self.a.bios)]
            run(cmd, self.ev, cwd=parent, env=env)
        self.recomp_dir = os.path.join(proj, "psxrecomp")
        return proj

    def generate_curated(self, proj: str, ing) -> None:
        cue = os.path.join(proj, "disc", os.path.basename(ing.primary.entry))
        cmd = [sys.executable, os.path.join(self.recomp_dir, "psxrecomp_cli.py"), "generate",
               "--config", os.path.join(proj, "game.toml"), "--project-root", proj, "--disc", cue]
        if self.a.bios:
            cmd += ["--bios", os.path.abspath(self.a.bios)]
        run(cmd, self.ev, cwd=proj)

    def stage_gamedata(self, proj: str, prof: dict | None) -> str:
        gd = os.path.join(self.work, "GameData")
        if os.path.isdir(gd):
            shutil.rmtree(gd)
        os.makedirs(gd)
        if prof:
            src_root = os.path.join(self.work, "src", slug(prof["serial"]))
            items = [os.path.join(src_root, p) for p in prof["gamedata"]]
        else:
            items = [os.path.join(proj, p) for p in ("game.toml", "game_options.toml", "mods", "assets")]
        for it in items:
            if os.path.isdir(it):
                shutil.copytree(it, os.path.join(gd, os.path.basename(it)), dirs_exist_ok=True)
            elif os.path.isfile(it):
                shutil.copy2(it, gd)
        # The bundled OpenBIOS the recompiled backend was built from; the runtime
        # looks for it at bios/openbios.bin in its game folder (Documents on iOS).
        os.makedirs(os.path.join(gd, "bios"), exist_ok=True)
        for f in ("openbios.bin", "OpenBIOS.LICENSE"):
            src = os.path.join(self.recomp_dir, "bios", f)
            if os.path.isfile(src):
                shutil.copy2(src, os.path.join(gd, "bios", f))
            else:
                self.ev.say(f"warning: {src} not found")
        # Licence notices travel with the app (psxrecomp: PolyForm Noncommercial; OpenBIOS: MIT).
        lic = os.path.join(gd, "licenses")
        os.makedirs(lic, exist_ok=True)
        for src, dst in (("LICENSE", "psxrecomp-LICENSE"), ("THIRD_PARTY_ATTRIBUTION.md", "THIRD_PARTY_ATTRIBUTION.md")):
            f = os.path.join(self.recomp_dir, src)
            if os.path.isfile(f):
                shutil.copy2(f, os.path.join(lic, dst))
        rl = os.path.join(self.recomp_dir, "runtime", "licenses")
        if os.path.isdir(rl):
            shutil.copytree(rl, lic, dirs_exist_ok=True)
        if self.a.universal:
            # Marks a universal player: the app runs whatever disc is in Documents/disc,
            # with all game code in the interpreter (see ios/src/ios_platform.mm).
            with open(os.path.join(gd, "ps1ios_universal"), "w") as f:
                f.write("1\n")
        toml = os.path.join(gd, "game.toml")
        if os.path.isfile(toml):
            set_toml_renderer(toml, self.renderer)
            # Player 1 = the first gamepad: the touch pad, or a connected controller
            # (psxrecomp's release default is the keyboard).
            set_toml_key(toml, "controller", "p1_device", "auto")
        return gd

    def configure(self, proj: str, gd: str, display: str, bundle: str) -> str:
        bdir = os.path.join(self.work, "xcode")
        cmd = ["cmake", "-S", proj, "-B", bdir, "-G", "Xcode",
               "-DCMAKE_SYSTEM_NAME=iOS", "-DCMAKE_OSX_ARCHITECTURES=arm64", "-DCMAKE_OSX_DEPLOYMENT_TARGET=16.0",
               # one configuration: psxrecomp's build stamps files per configuration
               "-DCMAKE_CONFIGURATION_TYPES=Release", "-DCMAKE_BUILD_TYPE=Release",
               f"-DCMAKE_PROJECT_INCLUDE={IOS_DIR}/ios.cmake",
               f"-DPS1IOS_TEAM={self.a.team}", f"-DPS1IOS_BUNDLE_ID={bundle}", f"-DPS1IOS_RENDERER={self.renderer}",
               f"-DPS1IOS_DISPLAY_NAME={display}", f"-DPS1IOS_GAMEDATA={gd}"]
        if self.a.target == "simulator":
            cmd.append("-DCMAKE_OSX_SYSROOT=iphonesimulator")
        if self.renderer == "vulkan":
            cmd += [f"-DGLSLC_EXE={self.glslc}", f"-DPS1IOS_MOLTENVK={self.mvk}"]
        run(cmd, self.ev, quiet=True)
        xp = glob.glob(os.path.join(bdir, "*.xcodeproj"))
        if not xp:
            raise PipelineError("cmake did not produce an Xcode project")
        return xp[0]

    def build_unsigned(self, xcodeproj: str) -> str:
        """Simulator build, or an unsigned device build for sideloading tools that re-sign."""
        sdk = "iphonesimulator" if self.a.target == "simulator" else "iphoneos"
        dd = os.path.join(self.work, "DerivedData")
        run(["xcodebuild", "-project", xcodeproj, "-scheme", "psx-runtime", "-configuration", "Release",
             "-sdk", sdk, "-derivedDataPath", dd, "-IDEBuildingContinueBuildingAfterErrors=YES",
             "CODE_SIGNING_ALLOWED=NO", "CODE_SIGNING_REQUIRED=NO",
             "CODE_SIGN_IDENTITY=", "build"], self.ev, quiet=True)
        apps = [p for p in glob.glob(os.path.join(self.work, "**", "PS1Game.app"), recursive=True)
                if f"-{sdk}" in p]
        if not apps:
            raise PipelineError(f"build produced no PS1Game.app; open {xcodeproj} in Xcode for the full log")
        apps.sort(key=os.path.getmtime)
        return apps[-1]

    def archive(self, xcodeproj: str) -> str:
        arch = os.path.join(self.work, "PS1Game.xcarchive")
        run(["xcodebuild", "-project", xcodeproj, "-scheme", "psx-runtime", "-configuration", "Release",
             "-destination", "generic/platform=iOS", "-archivePath", arch, "-allowProvisioningUpdates",
             f"DEVELOPMENT_TEAM={self.a.team}", "archive"], self.ev, quiet=True)
        app = os.path.join(arch, "Products", "Applications", "PS1Game.app")
        if not os.path.isdir(app):
            raise PipelineError(f"archive has no app; open {xcodeproj} in Xcode for the full log")
        run(["codesign", "--verify", "--deep", "--strict", app], self.ev)
        return app

    def ipa(self, app: str, name: str) -> str:
        d = os.path.join(self.work, "ipa")
        if os.path.isdir(d):
            shutil.rmtree(d)
        os.makedirs(os.path.join(d, "Payload"))
        shutil.copytree(app, os.path.join(d, "Payload", os.path.basename(app)), symlinks=True)
        out_dir = os.path.abspath(self.a.out or self.work)
        os.makedirs(out_dir, exist_ok=True)
        out = os.path.join(out_dir, f"{slug(name)}.ipa")
        run(["/usr/bin/ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", "Payload", out], self.ev, cwd=d)
        return out

    def install(self, app: str, bundle: str, ing) -> None:
        dev = self.a.device
        run(["xcrun", "devicectl", "device", "install", "app", "--device", dev, app], self.ev)
        seen = set()
        for disc in ing.discs:
            ddir = os.path.dirname(disc.entry)
            for f in sorted(os.listdir(ddir)):
                p = os.path.join(ddir, f)
                if p in seen or not os.path.isfile(p):
                    continue
                seen.add(p)
                run(["xcrun", "devicectl", "device", "copy", "to", "--device", dev, "--source", p,
                     "--destination", f"Documents/disc/{f}", "--domain-type", "appDataContainer",
                     "--domain-identifier", bundle], self.ev)

    def run_simulator(self, app: str, bundle: str, ing) -> str:
        """Boots an iPhone simulator, installs the app, copies the disc in, starts the
        game and saves a screenshot after --run-seconds."""
        import time
        devs = json.loads(subprocess.run(["xcrun", "simctl", "list", "devices", "available", "-j"],
                                         capture_output=True, text=True, check=True).stdout)["devices"]
        cands = [(rt, d) for rt, ds in devs.items() if "iOS" in rt for d in ds if d["name"].startswith("iPhone")]
        if not cands:
            raise PipelineError("no iPhone simulator available (Xcode > Settings > Components)")
        pro_max = [c for c in cands if "Pro Max" in c[1]["name"]]
        rt, dev = sorted(pro_max or cands, key=lambda c: c[0])[-1]
        udid = dev["udid"]
        self.ev.say(f"simulator: {dev['name']} ({rt.rsplit('.', 1)[-1]})")
        subprocess.run(["xcrun", "simctl", "boot", udid], capture_output=True)
        run(["xcrun", "simctl", "bootstatus", udid, "-b"], self.ev, quiet=True)
        run(["xcrun", "simctl", "install", udid, app], self.ev)
        data = subprocess.run(["xcrun", "simctl", "get_app_container", udid, bundle, "data"],
                              capture_output=True, text=True, check=True).stdout.strip()
        ddir = os.path.join(data, "Documents", "disc")
        os.makedirs(ddir, exist_ok=True)
        if self.a.run_disc:
            # Run a different disc than the one the app was built from (universal player test).
            rd = os.path.join(self.work, "run-disc")
            if os.path.isdir(rd):
                shutil.rmtree(rd)
            ing = ingest(self.a.run_disc, rd)
            self.ev.say("running disc: " + os.path.basename(ing.primary.entry))
        for disc in ing.discs:
            src = os.path.dirname(disc.entry)
            for f in os.listdir(src):
                if os.path.isfile(os.path.join(src, f)):
                    shutil.copy2(os.path.join(src, f), ddir)
        subprocess.run(["xcrun", "simctl", "ui", udid, "appearance", "dark"], capture_output=True)
        log_path = os.path.join(self.work, "simulator.log")
        out_dir = os.path.abspath(self.a.out or self.work)
        os.makedirs(out_dir, exist_ok=True)
        env = dict(os.environ)
        if self.a.pad_demo:
            # simctl passes SIMCTL_CHILD_* to the app; the pad then holds Right+Cross after 15 s
            env["SIMCTL_CHILD_PS1IOS_PAD_DEMO"] = "1"
        with open(log_path, "w") as log:
            proc = subprocess.Popen(["xcrun", "simctl", "launch", "--console-pty", "--terminate-running-process",
                                     udid, bundle], stdout=log, stderr=subprocess.STDOUT, env=env)
            # Four screenshots spread over the run: the first can land before the game
            # draws on a slow machine, and two later ones give a frame-rate measurement.
            base = os.path.join(out_dir, f"{slug(self.name)}-simulator")
            marks = [max(1, self.a.run_seconds * k // 4) for k in (1, 2, 3)] + [self.a.run_seconds]
            waited = 0
            for n, mark in enumerate(marks, 1):
                time.sleep(max(0, mark - waited))
                waited = mark
                shot = f"{base}.png" if n == len(marks) else f"{base}-{n}.png"
                run(["xcrun", "simctl", "io", udid, "screenshot", shot], self.ev, quiet=True)
            alive = proc.poll() is None
            proc.terminate()
        for label, root in (("app bundle", app), ("Documents", os.path.join(data, "Documents"))):
            files = []
            for dp, dn, fn in os.walk(root):
                dn[:] = [d for d in dn if not d.endswith((".lproj", "_CodeSignature"))]
                for n in fn:
                    rel = os.path.relpath(os.path.join(dp, n), root)
                    if rel.count(os.sep) <= 2:
                        files.append(rel)
            self.ev.say(f"{label}: " + ", ".join(sorted(files)[:80]))
        with open(log_path, errors="replace") as f:
            tail = f.read().splitlines()[-60:]
        for ln in tail:
            self.ev.say("app: " + ln)
        if not alive:
            raise PipelineError(f"the app exited within {self.a.run_seconds}s (log: {log_path}, screenshot: {shot})")
        return shot

    # ------------------------------------------------------------ main
    def run(self) -> str:
        ev = self.ev
        sim = self.a.target == "simulator"
        ev.total = 9 + (1 if (self.a.device or (sim and self.a.run_seconds > 0)) else 0)
        with ev.stage("check this Mac"):
            self.check_mac()
            ev.summary = f"target {self.a.target}, renderer {self.renderer}, {'signed' if self.signed else 'unsigned'}"
        with ev.stage("unpack zip and find the disc"):
            ing = self.ingest()
            ev.summary = os.path.basename(ing.primary.entry)
        with ev.stage("read the disc"):
            info = self.probe(ing)
            serial = self.a.serial or (info.serial if info else None)
            if info:
                ev.say(json.dumps(info.as_dict()))
            ev.summary = f"{serial or 'unknown serial'}"
        prof = None if self.a.generic else load_profile(serial)
        if self.a.universal:
            prof = None   # a universal player is built from the generic scaffold
            name = self.a.name or "PS1 Player"
            bundle = self.a.bundle_id or f"com.{slug(self.a.bundle_prefix or 'ps1ios')}.player".replace("-", "")
        else:
            name = self.a.name or (prof["display_name"] if prof else (serial or "PS1 Game"))
            bundle = self.a.bundle_id or f"com.{slug(self.a.bundle_prefix or 'ps1ios')}.{slug(serial or name)}".replace("-", "")
        self.name = name
        with ev.stage("make the recompilation project"):
            if prof:
                ev.say(f"curated project for {serial}: {prof['title']}")
                proj = self.project_curated(prof, ing)
            else:
                ev.say("no curated project for this disc: using psxrecomp's generic scaffold")
                proj = self.project_generic(name, serial, ing)
            ev.summary = proj
        with ev.stage("iOS patches"):
            for p in sorted(glob.glob(os.path.join(IOS_DIR, "patches", "*.patch"))):
                apply_patch(self.recomp_dir, p, ev)
        with ev.stage("recompile the game from your disc"):
            if prof:
                self.generate_curated(proj, ing)
            else:
                ev.say("generated by the scaffold (setup_project.sh --generate)")
        with ev.stage("Xcode project (iOS)"):
            gd = self.stage_gamedata(proj, prof)
            xp = self.configure(proj, gd, name, bundle)
            ev.summary = xp
        with ev.stage("build" + (" and sign" if self.signed else " (unsigned)")):
            app = self.archive(xp) if self.signed else self.build_unsigned(xp)
            ev.summary = app
        result = app
        with ev.stage("package"):
            if sim:
                ev.summary = "simulator app (no IPA)"
            else:
                result = self.ipa(app, name)
                ev.summary = result + ("" if self.signed else " (unsigned: re-sign with AltStore/Sideloadly)")
        if self.a.device and self.signed:
            with ev.stage("install and copy the disc to the iPhone"):
                self.install(app, bundle, ing)
                ev.summary = bundle
        elif sim and self.a.run_seconds > 0:
            with ev.stage("run in the iPhone simulator"):
                result = self.run_simulator(app, bundle, ing)
                ev.summary = result
        return result

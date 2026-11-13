## PS1 Player (universal, unsigned IPA)

One iPhone/iPad app for PS1 games. No Mac, no Xcode and no per-game build:

1. Sideload `ps1-player.ipa` with AltStore, SideStore or Sideloadly (they sign it with your Apple ID).
2. In the Files app, open **On My iPhone → PS1 Player → disc** and copy in your own disc dump
   (`.cue` + `.bin`, or `.bin`, `.img`, `.iso`).
3. Open the app. With several games in the folder it asks which one to start.

How it runs: the app is psxrecomp's runtime with the bundled OpenBIOS. The game's code is read from
your disc and run by psxrecomp's interpreter (iOS does not allow generating native code on the
phone). It is slower than a game recompiled ahead of time with `ps1ios build`, and compatibility
depends on the game.

**Experimental.** Verified in CI: the app starts a disc it was not built from in the iPhone
simulator, and the touch pad controls it. Not verified: commercial games and physical devices.

This download contains no game and no Sony BIOS. Use it only with dumps of discs you own.

Licences: psxrecomp is under the PolyForm Noncommercial License 1.0.0
(https://polyformproject.org/licenses/noncommercial/1.0.0), so this build is for noncommercial use
only; OpenBIOS is MIT. The notices are inside the app (`licenses/`).

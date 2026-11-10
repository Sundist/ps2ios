/* iOS platform layer for psxrecomp games (any PS1 title built with ps1-to-ios).
 * The game code itself is unchanged: this only maps the desktop
 * assumptions (writable folder next to the exe, a picked disc, a keyboard
 * or pad) onto an iPhone app. */
#ifndef PS1IOS_PLATFORM_H
#define PS1IOS_PLATFORM_H
#ifdef __cplusplus
extern "C" {
#endif

/* Writable game folder: <app container>/Documents. Replaces the exe
 * directory as the anchor for settings.toml, disc.cfg, saves/, mods/.
 * On first call it copies the bundle's GameData/ (assets, lang, mods)
 * into it and, when disc.cfg is missing, points it at the first .cue/.chd
 * found in Documents/disc/ (copied there with the Files app or devicectl). */
const char *ps1ios_data_dir(void);

#ifdef __cplusplus
}
#endif
#endif

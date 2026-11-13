/* Universal player: describe the disc that is actually in Documents/disc to
 * the psxrecomp runtime by rewriting the [game] section of its game.toml. */
#ifndef PS1IOS_GAME_CONFIG_H
#define PS1IOS_GAME_CONFIG_H

#include <string>
#include "disc_probe.h"

/* Returns `toml` with [game] id/name/exe/disc/load_address/entry_pc/text_size/
 * stack_base set from the disc, and the sections that pin the original disc's
 * hashes ([prepare_disc], [netplay] and their sub-tables) removed.
 * `disc_rel` is the disc path relative to the game folder, e.g. "disc/Game.cue". */
std::string ps1ios_game_toml_for_disc(const std::string &toml, const ps1_disc_info &d,
                                      const std::string &disc_rel);

#endif

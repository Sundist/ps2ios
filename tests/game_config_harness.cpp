// usage: game_config_harness <disc track> <disc_rel> < game.toml > patched.toml
#include <cstdio>
#include <iostream>
#include <iterator>
#include <string>
#include "game_config.h"

int main(int argc, char **argv) {
    if (argc != 3) return 2;
    ps1_disc_info d;
    char err[128];
    if (!ps1_disc_probe(argv[1], &d, err, sizeof err)) { std::fprintf(stderr, "%s\n", err); return 1; }
    std::string toml((std::istreambuf_iterator<char>(std::cin)), std::istreambuf_iterator<char>());
    std::cout << ps1ios_game_toml_for_disc(toml, d, argv[2]);
    return 0;
}

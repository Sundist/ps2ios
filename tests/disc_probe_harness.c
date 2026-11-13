/* usage: disc_probe_harness <cue|bin|iso>  -> one JSON line */
#include <stdio.h>
#include <string.h>
#include "disc_probe.h"

int main(int argc, char **argv) {
    if (argc != 2) return 2;
    char track[1024], err[128] = "";
    const char *path = argv[1];
    size_t n = strlen(path);
    if (n > 4 && strcmp(path + n - 4, ".cue") == 0) {
        if (!ps1_cue_first_track(path, track, sizeof track)) { printf("{\"ok\":0,\"err\":\"cue\"}\n"); return 1; }
        path = track;
    }
    ps1_disc_info d;
    if (!ps1_disc_probe(path, &d, err, sizeof err)) { printf("{\"ok\":0,\"err\":\"%s\"}\n", err); return 1; }
    printf("{\"ok\":1,\"boot\":\"%s\",\"serial\":\"%s\",\"entry_pc\":%u,\"load_address\":%u,\"text_size\":%u,\"stack_base\":%u}\n",
           d.boot, d.serial, d.entry_pc, d.load_address, d.text_size, d.stack_base);
    return 0;
}

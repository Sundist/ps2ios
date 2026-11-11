/* Prints pad_layout() output as JSON, then pad_hit() for each "x y" line on stdin.
 * usage: pad_harness W H safeL safeR safeT safeB scale */
#include <stdio.h>
#include <stdlib.h>
#include "pad_layout.h"

int main(int argc, char **argv) {
    if (argc != 8) return 2;
    pad_screen s = {strtof(argv[1], 0), strtof(argv[2], 0), strtof(argv[3], 0), strtof(argv[4], 0),
                    strtof(argv[5], 0), strtof(argv[6], 0), strtof(argv[7], 0)};
    pad_control c[PAD_MAX_CONTROLS];
    int n = pad_layout(&s, c);
    float gx0, gx1;
    pad_game_area(&s, &gx0, &gx1);
    printf("{\"game\":[%.2f,%.2f],\"controls\":[", gx0, gx1);
    for (int i = 0; i < n; i++)
        printf("%s{\"bit\":%u,\"kind\":%d,\"cx\":%.2f,\"cy\":%.2f,\"w\":%.2f,\"h\":%.2f,\"label\":\"%s\"}",
               i ? "," : "", c[i].bit, (int)c[i].kind, c[i].cx, c[i].cy, c[i].w, c[i].h, c[i].label);
    printf("],\"hits\":[");
    float x, y;
    int first = 1;
    while (scanf("%f %f", &x, &y) == 2) {
        printf("%s%u", first ? "" : ",", pad_hit(c, n, x, y));
        first = 0;
    }
    printf("]}\n");
    return 0;
}

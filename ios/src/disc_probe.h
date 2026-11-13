/* Reads a PS1 disc image on the device: SYSTEM.CNF -> BOOT file -> PS-X EXE
 * header. Plain C, shared with the unit tests. Used by the universal player
 * to describe whatever disc is in Documents/disc to the runtime. */
#ifndef PS1IOS_DISC_PROBE_H
#define PS1IOS_DISC_PROBE_H

#include <stdint.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    char boot[64];        /* boot file name on the disc, e.g. SLUS_005.94 */
    char serial[16];      /* SLUS-00594, or "" when the name is not a serial */
    uint32_t entry_pc, load_address, text_size, stack_base;
} ps1_disc_info;

/* `track` is the first data track: a raw 2352-byte image (.bin/.img) or a
 * cooked 2048-byte one (.iso). Returns 1 on success; on failure 0 and a short
 * reason in err (if given). */
int ps1_disc_probe(const char *track, ps1_disc_info *out, char *err, size_t err_cap);

/* First FILE named by a cue sheet, resolved next to it. Returns 1 on success. */
int ps1_cue_first_track(const char *cue, char *out, size_t cap);

#ifdef __cplusplus
}
#endif
#endif

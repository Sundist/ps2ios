#include "disc_probe.h"

#include <ctype.h>
#include <stdio.h>
#include <string.h>
#include <strings.h>

#define SECTOR 2048

typedef struct { FILE *f; long stride, offset; } image;

static void fail(char *err, size_t cap, const char *msg) {
    if (err && cap) snprintf(err, cap, "%s", msg);
}

static int image_open(image *im, const char *path) {
    static const unsigned char sync[12] = {0, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0};
    unsigned char head[16];
    im->f = fopen(path, "rb");
    if (!im->f) return 0;
    if (fread(head, 1, sizeof head, im->f) != sizeof head) { fclose(im->f); return 0; }
    if (memcmp(head, sync, 12) == 0) {
        im->stride = 2352;
        im->offset = head[15] == 2 ? 24 : 16;   /* Mode 2 has an 8-byte subheader */
    } else {
        im->stride = 2048;
        im->offset = 0;
    }
    return 1;
}

static int read_sector(image *im, uint32_t lba, unsigned char *buf) {
    if (fseek(im->f, (long)lba * im->stride + im->offset, SEEK_SET) != 0) return 0;
    return fread(buf, 1, SECTOR, im->f) == SECTOR;
}

static uint32_t le32(const unsigned char *p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static int name_eq(const unsigned char *rec_name, int len, const char *want) {
    /* compare case-insensitively, ignoring the ";1" version suffix */
    int n = 0;
    while (n < len && rec_name[n] != ';') n++;
    if ((int)strlen(want) != n) return 0;
    for (int i = 0; i < n; i++)
        if (toupper(rec_name[i]) != toupper((unsigned char)want[i])) return 0;
    return 1;
}

/* Finds `name` in the directory at (lba, size). */
static int dir_find(image *im, uint32_t lba, uint32_t size, const char *name, int want_dir,
                    uint32_t *out_lba, uint32_t *out_size) {
    unsigned char sec[SECTOR];
    for (uint32_t s = 0; s < (size + SECTOR - 1) / SECTOR && s < 64; s++) {
        if (!read_sector(im, lba + s, sec)) return 0;
        for (int pos = 0; pos < SECTOR;) {
            int len = sec[pos];
            if (len == 0) break;                       /* rest of the sector is padding */
            if (len < 34 || pos + len > SECTOR) return 0;
            const unsigned char *r = sec + pos;
            int is_dir = (r[25] & 2) != 0, nlen = r[32];
            if (33 + nlen <= len && is_dir == want_dir && name_eq(r + 33, nlen, name)) {
                *out_lba = le32(r + 2);
                *out_size = le32(r + 10);
                return 1;
            }
            pos += len;
        }
    }
    return 0;
}

/* Finds a file by path ("SYSTEM.CNF", "EXE\\MAIN.EXE") from the root directory. */
static int find_path(image *im, const char *path, uint32_t *out_lba, uint32_t *out_size) {
    unsigned char pvd[SECTOR];
    if (!read_sector(im, 16, pvd) || memcmp(pvd + 1, "CD001", 5) != 0) return 0;
    uint32_t lba = le32(pvd + 156 + 2), size = le32(pvd + 156 + 10);
    char part[64];
    const char *p = path;
    for (;;) {
        while (*p == '\\' || *p == '/') p++;
        size_t n = strcspn(p, "\\/");
        if (n == 0 || n >= sizeof part) return 0;
        memcpy(part, p, n);
        part[n] = 0;
        p += n;
        int last = *p == 0;
        if (!dir_find(im, lba, size, part, !last, &lba, &size)) return 0;
        if (last) { *out_lba = lba; *out_size = size; return 1; }
    }
}

static void serial_from_boot(const char *boot, char *out, size_t cap) {
    /* SLUS_005.94 -> SLUS-00594 */
    const char *b = strrchr(boot, '\\');
    b = b ? b + 1 : boot;
    out[0] = 0;
    if (strlen(b) != 11 || cap < 11) return;
    for (int i = 0; i < 4; i++) if (!isalpha((unsigned char)b[i])) return;
    if ((b[4] != '_' && b[4] != '-') || b[8] != '.') return;
    for (int i = 5; i < 11; i++) if (i != 8 && !isdigit((unsigned char)b[i])) return;
    snprintf(out, cap, "%c%c%c%c-%c%c%c%c%c", toupper(b[0]), toupper(b[1]), toupper(b[2]), toupper(b[3]),
             b[5], b[6], b[7], b[9], b[10]);
}

int ps1_disc_probe(const char *track, ps1_disc_info *out, char *err, size_t err_cap) {
    image im;
    unsigned char sec[SECTOR + 1];
    uint32_t lba, size;
    memset(out, 0, sizeof *out);
    if (!image_open(&im, track)) { fail(err, err_cap, "cannot open the disc image"); return 0; }
    int ok = 0;
    if (find_path(&im, "SYSTEM.CNF", &lba, &size)) {
        if (!read_sector(&im, lba, sec)) { fail(err, err_cap, "cannot read SYSTEM.CNF"); goto done; }
        sec[size < SECTOR ? size : SECTOR] = 0;
        /* BOOT = cdrom:\SLUS_005.94;1   (also cdrom0:, with or without the backslash) */
        char *p = (char *)sec, *boot = NULL;
        for (; *p; p++) {
            if ((p[0] == 'c' || p[0] == 'C') && strncasecmp(p, "cdrom", 5) == 0) {
                char *q = p + 5;
                while (isdigit((unsigned char)*q)) q++;
                if (*q == ':') { boot = q + 1; break; }
            }
        }
        if (!boot) { fail(err, err_cap, "SYSTEM.CNF has no BOOT line"); goto done; }
        while (*boot == '\\' || *boot == '/') boot++;
        size_t n = strcspn(boot, ";\r\n \t");
        if (n == 0 || n >= sizeof out->boot) { fail(err, err_cap, "bad BOOT line"); goto done; }
        memcpy(out->boot, boot, n);
    } else {
        /* very early titles boot PSX.EXE without a SYSTEM.CNF */
        snprintf(out->boot, sizeof out->boot, "PSX.EXE");
    }
    if (!find_path(&im, out->boot, &lba, &size) || !read_sector(&im, lba, sec)) {
        fail(err, err_cap, "the BOOT file is not on the disc");
        goto done;
    }
    if (memcmp(sec, "PS-X EXE", 8) != 0) { fail(err, err_cap, "the BOOT file is not a PS-X EXE"); goto done; }
    out->entry_pc = le32(sec + 0x10);
    out->load_address = le32(sec + 0x18);
    out->text_size = le32(sec + 0x1C);
    out->stack_base = le32(sec + 0x30);
    serial_from_boot(out->boot, out->serial, sizeof out->serial);
    ok = 1;
done:
    fclose(im.f);
    return ok;
}

int ps1_cue_first_track(const char *cue, char *out, size_t cap) {
    FILE *f = fopen(cue, "r");
    char line[1024];
    int ok = 0;
    if (!f) return 0;
    while (!ok && fgets(line, sizeof line, f)) {
        char *p = line;
        while (*p == ' ' || *p == '\t') p++;
        if (strncasecmp(p, "FILE", 4) != 0) continue;
        p += 4;
        while (*p == ' ' || *p == '\t') p++;
        const char *name;
        size_t n;
        if (*p == '"') { name = p + 1; n = strcspn(name, "\""); }
        else { name = p; n = strcspn(name, " \t\r\n"); }
        if (n == 0) continue;
        /* the track file sits next to the cue; drop any folder part the cue carries */
        const char *base = name;
        for (size_t i = 0; i < n; i++) if (name[i] == '/' || name[i] == '\\') base = name + i + 1;
        n -= (size_t)(base - name);
        const char *slash = strrchr(cue, '/');
        size_t dlen = slash ? (size_t)(slash - cue) + 1 : 0;
        if (dlen + n + 1 > cap) break;
        memcpy(out, cue, dlen);
        memcpy(out + dlen, base, n);
        out[dlen + n] = 0;
        ok = 1;
    }
    fclose(f);
    return ok;
}

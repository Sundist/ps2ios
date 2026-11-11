#include "pad_layout.h"

#include <math.h>

#define GAP 8.0f    /* vertical spacing */
#define EDGE 4.0f   /* horizontal: to the safe edge and to the picture */

static float clampf(float v, float lo, float hi) { return v < lo ? lo : (v > hi ? hi : v); }
static float maxf(float a, float b) { return a > b ? a : b; }
static float minf(float a, float b) { return a < b ? a : b; }

void pad_game_area(const pad_screen *s, float *x0, float *x1) {
    float gw = s->height * 4.0f / 3.0f;
    if (gw > s->width) gw = s->width;
    *x0 = (s->width - gw) * 0.5f;
    *x1 = *x0 + gw;
}

static pad_control mk(uint32_t bit, pad_kind k, float cx, float cy, float w, float h, const char *label) {
    pad_control c = {bit, k, cx, cy, w, h, label};
    return c;
}

int pad_layout(const pad_screen *s, pad_control *out) {
    const float scale = clampf(s->scale > 0 ? s->scale : 1.0f, 0.8f, 1.3f);
    float gx0, gx1;
    pad_game_area(s, &gx0, &gx1);

    /* Width each side strip offers between the safe edge and the picture. */
    float strip_l = gx0 - s->safe_left - 2 * EDGE;
    float strip_r = (s->width - gx1) - s->safe_right - 2 * EDGE;
    float usable = minf(strip_l, strip_r);

    /* D-pad radius: fill the strip, within thumb-sized bounds. */
    float R = clampf(usable * 0.5f, 44.0f, 66.0f) * scale;

    /* Face diamond: button radius b (>= 44 pt targets), centres d from the
     * cluster centre, never closer than 2b + 2 between neighbours. Rf is the
     * diamond's outer radius; on a narrow strip it can exceed R. */
    float b = maxf(R * 0.40f, PAD_MIN_TARGET * 0.5f);
    float d = maxf(R - b, (2.0f * b + 2.0f) / 1.41421356f);
    float Rf = maxf(R, d + b);

    float lcx = s->safe_left + EDGE + R;
    float rcx = s->width - s->safe_right - EDGE - Rf;
    /* Low in the strip, where a thumb rests when the phone is held. */
    float cy = s->height - s->safe_bottom - 1.5f * GAP - Rf;

    /* Shoulders and Select/Start: pills in the same strips, never over the picture. */
    float pill_h = maxf(PAD_MIN_TARGET, 40.0f * scale);
    float pill_w = clampf(2.0f * R * 0.9f, 64.0f, 120.0f);
    float y_l2 = s->safe_top + GAP + pill_h * 0.5f;
    float y_l1 = y_l2 + pill_h + GAP;
    float small_w = clampf(64.0f * scale, PAD_MIN_TARGET, 84.0f);
    float y_sel = ((y_l1 + pill_h * 0.5f) + (cy - Rf)) * 0.5f;

    int n = 0;
    out[n++] = mk(PAD_UP | PAD_DOWN | PAD_LEFT | PAD_RIGHT, PAD_KIND_DPAD, lcx, cy, 2 * R, 2 * R, "D-PAD");
    out[n++] = mk(PAD_CROSS,    PAD_KIND_ROUND, rcx,     cy + d, 2 * b, 2 * b, "✕");
    out[n++] = mk(PAD_CIRCLE,   PAD_KIND_ROUND, rcx + d, cy,     2 * b, 2 * b, "○");
    out[n++] = mk(PAD_SQUARE,   PAD_KIND_ROUND, rcx - d, cy,     2 * b, 2 * b, "□");
    out[n++] = mk(PAD_TRIANGLE, PAD_KIND_ROUND, rcx,     cy - d, 2 * b, 2 * b, "△");
    out[n++] = mk(PAD_L2, PAD_KIND_PILL, lcx, y_l2, pill_w, pill_h, "L2");
    out[n++] = mk(PAD_L1, PAD_KIND_PILL, lcx, y_l1, pill_w, pill_h, "L1");
    out[n++] = mk(PAD_R2, PAD_KIND_PILL, rcx, y_l2, pill_w, pill_h, "R2");
    out[n++] = mk(PAD_R1, PAD_KIND_PILL, rcx, y_l1, pill_w, pill_h, "R1");
    out[n++] = mk(PAD_SELECT, PAD_KIND_PILL, lcx, y_sel, small_w, pill_h, "SELECT");
    out[n++] = mk(PAD_START,  PAD_KIND_PILL, rcx, y_sel, small_w, pill_h, "START");
    return n;
}

/* 8-way d-pad. Cardinal sectors are 60° wide and diagonals 30°, so running
 * left/right does not slip into a diagonal by accident. */
static uint32_t dpad_dir(float dx, float dy, float R) {
    float dist = sqrtf(dx * dx + dy * dy);
    if (dist < R * 0.2f) return 0;                       /* centre dead zone */
    float a = atan2f(-dy, dx) * (180.0f / 3.14159265f);  /* 0 = right, 90 = up */
    if (a < 0) a += 360.0f;
    /* nearest diagonal (45, 135, 225, 315) */
    float diag = floorf(a / 90.0f) * 90.0f + 45.0f;
    if (fabsf(a - diag) <= 15.0f) {
        if (diag == 45.0f)  return PAD_UP | PAD_RIGHT;
        if (diag == 135.0f) return PAD_UP | PAD_LEFT;
        if (diag == 225.0f) return PAD_DOWN | PAD_LEFT;
        return PAD_DOWN | PAD_RIGHT;
    }
    if (a < 45.0f || a >= 315.0f) return PAD_RIGHT;
    if (a < 135.0f) return PAD_UP;
    if (a < 225.0f) return PAD_LEFT;
    return PAD_DOWN;
}

uint32_t pad_hit(const pad_control *c, int n, float x, float y) {
    /* d-pad first: generous capture so a rolling thumb keeps steering. */
    for (int i = 0; i < n; i++) {
        if (c[i].kind != PAD_KIND_DPAD) continue;
        float R = c[i].w * 0.5f, dx = x - c[i].cx, dy = y - c[i].cy;
        if (dx * dx + dy * dy <= (R * 1.25f) * (R * 1.25f)) return dpad_dir(dx, dy, R);
    }
    /* face diamond: nearest button, plus its neighbour when the touch sits between them */
    int best = -1, second = -1;
    float d1 = 1e9f, d2 = 1e9f, rb = 0;
    for (int i = 0; i < n; i++) {
        if (c[i].kind != PAD_KIND_ROUND) continue;
        float dx = x - c[i].cx, dy = y - c[i].cy, dd = sqrtf(dx * dx + dy * dy);
        rb = c[i].w * 0.5f;
        if (dd < d1) { second = best; d2 = d1; best = i; d1 = dd; }
        else if (dd < d2) { second = i; d2 = dd; }
    }
    if (best >= 0 && d1 <= rb * 1.35f) {
        uint32_t bits = c[best].bit;
        if (second >= 0 && d2 <= rb * 1.35f && d2 - d1 < rb * 0.4f) bits |= c[second].bit;
        return bits;
    }
    /* pills */
    for (int i = 0; i < n; i++) {
        if (c[i].kind != PAD_KIND_PILL) continue;
        if (fabsf(x - c[i].cx) <= c[i].w * 0.5f + 6.0f && fabsf(y - c[i].cy) <= c[i].h * 0.5f + 4.0f)
            return c[i].bit;
    }
    return 0;
}

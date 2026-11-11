/* Touch gamepad layout and hit testing, in plain C so the same code drives the
 * iOS overlay (ios_platform.mm), the layout drawing (tools/render_pad_layout.py)
 * and the unit tests (tests/test_pad_layout.py). Units are UIKit points.
 *
 * Ergonomics:
 *  - Both thumb clusters sit in the side strips left over by the 4:3 PS1
 *    picture, against the safe-area edge, low enough for a resting thumb, so
 *    nothing covers the game on a phone in landscape.
 *  - The d-pad is ONE control read by angle (8 directions, centre dead zone):
 *    the thumb can roll between directions without lifting.
 *  - Face buttons are a diamond; a touch between two neighbours presses both
 *    (e.g. Cross+Square), like rocking a thumb on a real pad.
 *  - Every target is at least 44 pt (Apple's minimum) and has a forgiving
 *    hit area larger than its drawing.
 */
#ifndef PS1IOS_PAD_LAYOUT_H
#define PS1IOS_PAD_LAYOUT_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Button bits (PlayStation names). */
enum {
    PAD_UP = 1u << 0, PAD_DOWN = 1u << 1, PAD_LEFT = 1u << 2, PAD_RIGHT = 1u << 3,
    PAD_CROSS = 1u << 4, PAD_CIRCLE = 1u << 5, PAD_SQUARE = 1u << 6, PAD_TRIANGLE = 1u << 7,
    PAD_L1 = 1u << 8, PAD_L2 = 1u << 9, PAD_R1 = 1u << 10, PAD_R2 = 1u << 11,
    PAD_SELECT = 1u << 12, PAD_START = 1u << 13,
};

typedef enum { PAD_KIND_DPAD, PAD_KIND_ROUND, PAD_KIND_PILL } pad_kind;

typedef struct {
    uint32_t bit;        /* PAD_* (the d-pad uses PAD_UP|DOWN|LEFT|RIGHT) */
    pad_kind kind;
    float cx, cy;        /* centre */
    float w, h;          /* drawn size (round: w == h == diameter) */
    const char *label;
} pad_control;

typedef struct {
    float width, height;                                   /* view size, landscape */
    float safe_left, safe_right, safe_top, safe_bottom;    /* safe-area insets */
    float scale;                                           /* user size, 0.8 .. 1.3 */
} pad_screen;

#define PAD_MAX_CONTROLS 12
#define PAD_MIN_TARGET 44.0f

/* Fills `out` (at least PAD_MAX_CONTROLS) and returns the number of controls. */
int pad_layout(const pad_screen *s, pad_control *out);

/* Buttons pressed by one touch at (x, y), given a layout from pad_layout(). */
uint32_t pad_hit(const pad_control *c, int n, float x, float y);

/* The 4:3 picture area the layout tries to keep clear (x0, x1). */
void pad_game_area(const pad_screen *s, float *x0, float *x1);

#ifdef __cplusplus
}
#endif
#endif

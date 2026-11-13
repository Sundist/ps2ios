/* ps1-to-ios test ROM: a small, original PS1 program used to test the whole
 * zip -> recompile -> iOS app pipeline without any commercial game data.
 *
 * It draws straight to the GPU: a gradient background, a spinning
 * Gouraud-shaded triangle, a row of bars that pulse, and a box moved by the
 * d-pad whose colour changes with the face buttons (pad read through the
 * BIOS InitPAD/StartPAD driver). Frame pacing uses root counter 1 counting
 * horizontal blanks.
 */
#include <stdint.h>

#ifndef VARIANT
#define VARIANT 1
#endif

#define GP0       (*(volatile uint32_t *)0x1F801810)
#define GP1       (*(volatile uint32_t *)0x1F801814)
#define GPUSTAT   (*(volatile uint32_t *)0x1F801814)
#define T1_VALUE  (*(volatile uint32_t *)0x1F801110)
#define T1_MODE   (*(volatile uint32_t *)0x1F801114)

#define SCREEN_W 320
#define SCREEN_H 240

void InitPAD(void *buf1, int len1, void *buf2, int len2);
void StartPAD(void);
void ChangeClearPAD(int clear);

static volatile uint8_t pad_buf[2][34];

/* 256-entry sine table, values -4096..4096, filled at start-up. */
static int16_t sin_tab[256];

static void make_sin(void) {
    /* quarter wave by a 5th-order polynomial on x in [0, 1]: sin(x*pi/2) */
    for (int i = 0; i < 64; i++) {
        int32_t x = (i * 4096) / 64;                      /* 0..4096 */
        int64_t x2 = (int64_t)x * x >> 12;
        int64_t x3 = x2 * x >> 12;
        int64_t x5 = x3 * x2 >> 12;
        /* sin(pi/2 x) ~= 1.5707963 x - 0.6459641 x^3 + 0.0796926 x^5 */
        int32_t s = (int32_t)((6434 * (int64_t)x - 2646 * x3 + 326 * x5) >> 12);
        if (s > 4096) s = 4096;
        sin_tab[i] = (int16_t)s;
        sin_tab[128 - i] = (int16_t)s;
        sin_tab[128 + i] = (int16_t)-s;
        sin_tab[(256 - i) & 255] = (int16_t)-s;
    }
    sin_tab[64] = 4096;
    sin_tab[192] = -4096;
}
static int isin(int a) { return sin_tab[a & 255]; }
static int icos(int a) { return sin_tab[(a + 64) & 255]; }

static void gpu_wait(void) {
    /* bit 26: ready to receive a command word; bit 28: ready for DMA block */
    for (int n = 0; n < 100000 && !(GPUSTAT & (1u << 26)); n++) {}
}
static void gp0(uint32_t w) { gpu_wait(); GP0 = w; }

static uint32_t xy(int x, int y) { return ((uint32_t)(y & 0x7FF) << 16) | (uint32_t)(x & 0x7FF); }
static uint32_t rgb(int r, int g, int b) { return ((uint32_t)b << 16) | ((uint32_t)g << 8) | (uint32_t)r; }

static void fill(int x, int y, int w, int h, uint32_t col) {
    gp0(0x02000000 | col);
    gp0(xy(x, y));
    gp0(((uint32_t)h << 16) | (uint32_t)((w + 15) & ~15));
}

static void quad_g(int x0, int y0, uint32_t c0, int x1, int y1, uint32_t c1,
                   int x2, int y2, uint32_t c2, int x3, int y3, uint32_t c3) {
    gp0(0x38000000 | c0); gp0(xy(x0, y0));
    gp0(c1); gp0(xy(x1, y1));
    gp0(c2); gp0(xy(x2, y2));
    gp0(c3); gp0(xy(x3, y3));
}

#if VARIANT != 2
static void tri_g(int x0, int y0, uint32_t c0, int x1, int y1, uint32_t c1, int x2, int y2, uint32_t c2) {
    gp0(0x30000000 | c0); gp0(xy(x0, y0));
    gp0(c1); gp0(xy(x1, y1));
    gp0(c2); gp0(xy(x2, y2));
}
#endif

static void rect(int x, int y, int w, int h, uint32_t col) {
    gp0(0x60000000 | col);
    gp0(xy(x, y));
    gp0(((uint32_t)h << 16) | (uint32_t)w);
}

static void gpu_init(void) {
    GP1 = 0x00000000;                                   /* reset */
    GP1 = 0x03000001;                                   /* display off */
    GP1 = 0x06000000 | 0x260 | (0xC60u << 12);          /* horizontal range, 320 px */
    GP1 = 0x07000000 | 16 | ((16 + SCREEN_H) << 10);    /* vertical range, 240 lines */
    GP1 = 0x08000001;                                   /* 320x240, NTSC, 15 bit, progressive */
    GP1 = 0x05000000;                                   /* display start 0,0 */
    gp0(0xE1000000 | 0x400 | 0x200);                    /* draw to display allowed, dither */
    gp0(0xE6000000);                                    /* no mask */
    fill(0, 0, 1024, 512, 0);                           /* clear VRAM */
    GP1 = 0x03000000;                                   /* display on */
}

static void set_draw_buffer(int y0) {
    gp0(0xE3000000 | (uint32_t)(y0 << 10));                         /* area top-left */
    gp0(0xE4000000 | (SCREEN_W - 1) | ((uint32_t)(y0 + SCREEN_H - 1) << 10));
    gp0(0xE5000000 | ((uint32_t)y0 << 11));                         /* offset */
}

/* Wait for one video frame: 263 horizontal blanks on NTSC (counter 1, hblank clock).
 * Bounded, so a timer that does not count can never hang the program. */
static void wait_frame(void) {
    uint32_t start = T1_VALUE & 0xFFFF;
    for (int n = 0; n < 2000000; n++) {
        if (((T1_VALUE - start) & 0xFFFF) >= 263) return;
    }
}

static uint16_t pad_buttons(void) {
    if (pad_buf[0][0] != 0) return 0;                    /* no pad / error */
    return (uint16_t)~(pad_buf[0][2] | (pad_buf[0][3] << 8));
}

enum { B_SELECT = 1 << 0, B_START = 1 << 3, B_UP = 1 << 4, B_RIGHT = 1 << 5, B_DOWN = 1 << 6,
       B_LEFT = 1 << 7, B_L2 = 1 << 8, B_R2 = 1 << 9, B_L1 = 1 << 10, B_R1 = 1 << 11,
       B_TRIANGLE = 1 << 12, B_CIRCLE = 1 << 13, B_CROSS = 1 << 14, B_SQUARE = 1 << 15 };

int main(void) {
    make_sin();
    T1_MODE = 0x0100;                                   /* counter 1: hblank clock, free running */
    gpu_init();
    InitPAD((void *)pad_buf[0], 34, (void *)pad_buf[1], 34);
    StartPAD();
    ChangeClearPAD(1);

    int buffer = 0, frame = 0;
    int bx = 160, by = 170;
    uint32_t box_col = rgb(255, 255, 255);
    for (;;) {
        int y0 = buffer ? SCREEN_H : 0;
        set_draw_buffer(y0);

        /* background: vertical gradient that slowly shifts hue */
        int t = frame & 255;
        int a = frame * 2, r = 70, cx = 160, cy = 100;
#if VARIANT == 2
        /* Variant B (a different disc, used to test running a game the app was
         * not built from): warm colours and a spinning square. */
        uint32_t top = rgb(120, 40 + (isin(t) + 4096) / 200, 20);
        uint32_t bot = rgb(60, 10, 70 + (icos(t) + 4096) / 160);
        quad_g(0, 0, top, SCREEN_W, 0, top, 0, SCREEN_H, bot, SCREEN_W, SCREEN_H, bot);
        quad_g(cx + icos(a) * r / 4096, cy + isin(a) * r / 4096, rgb(255, 230, 60),
               cx + icos(a + 64) * r / 4096, cy + isin(a + 64) * r / 4096, rgb(255, 120, 40),
               cx + icos(a + 192) * r / 4096, cy + isin(a + 192) * r / 4096, rgb(250, 60, 160),
               cx + icos(a + 128) * r / 4096, cy + isin(a + 128) * r / 4096, rgb(120, 60, 255));
#else
        uint32_t top = rgb(20 + (isin(t) + 4096) / 200, 30, 90);
        uint32_t bot = rgb(10, 60 + (icos(t) + 4096) / 160, 70);
        quad_g(0, 0, top, SCREEN_W, 0, top, 0, SCREEN_H, bot, SCREEN_W, SCREEN_H, bot);

        /* spinning Gouraud triangle */
        tri_g(cx + icos(a) * r / 4096, cy + isin(a) * r / 4096, rgb(255, 60, 60),
              cx + icos(a + 85) * r / 4096, cy + isin(a + 85) * r / 4096, rgb(60, 255, 60),
              cx + icos(a + 171) * r / 4096, cy + isin(a + 171) * r / 4096, rgb(60, 120, 255));
#endif

        /* pulsing bars along the bottom */
        for (int i = 0; i < 10; i++) {
            int h = 12 + (isin(frame * 4 + i * 25) + 4096) * 24 / 8192;
            rect(20 + i * 29, SCREEN_H - 10 - h, 20, h, rgb(240, 200 - i * 12, 80 + i * 16));
        }

        /* box moved by the pad */
        uint16_t b = pad_buttons();
        if (b & B_LEFT) bx -= 3;
        if (b & B_RIGHT) bx += 3;
        if (b & B_UP) by -= 3;
        if (b & B_DOWN) by += 3;
        if (bx < 12) bx = 12;
        if (bx > SCREEN_W - 12) bx = SCREEN_W - 12;
        if (by < 12) by = 12;
        if (by > SCREEN_H - 50) by = SCREEN_H - 50;
        if (b & B_CROSS) box_col = rgb(80, 140, 255);
        if (b & B_CIRCLE) box_col = rgb(255, 80, 80);
        if (b & B_SQUARE) box_col = rgb(255, 120, 220);
        if (b & B_TRIANGLE) box_col = rgb(80, 230, 140);
        if (b & B_START) box_col = rgb(255, 255, 255);
        int sz = (b & (B_L1 | B_R1 | B_L2 | B_R2)) ? 16 : 10;
        rect(bx - sz - 2, by - sz - 2, 2 * sz + 4, 2 * sz + 4, rgb(0, 0, 0));
        rect(bx - sz, by - sz, 2 * sz, 2 * sz, box_col);

        /* frame counter as a moving tick at the top */
        rect((frame * 2) % SCREEN_W, 4, 8, 4, rgb(255, 255, 255));

        /* frame counter in binary, 16 boxes (bit 15 on the left): a screenshot
         * taken after a known time gives the number of frames drawn */
        for (int i = 0; i < 16; i++) {
            int on = (frame >> (15 - i)) & 1;
            rect(84 + i * 10, 14, 7, 7, on ? rgb(255, 255, 255) : rgb(40, 40, 40));
        }

        wait_frame();
        GP1 = 0x05000000 | ((uint32_t)y0 << 10);        /* show what was just drawn */
        buffer ^= 1;
        frame++;
    }
}

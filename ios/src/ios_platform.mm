// iOS platform layer: data folder, first-run copy, disc discovery, touch pad.
// The touch pad is a UIKit view over SDL's window that drives an SDL3
// virtual gamepad, so it works with every renderer (Vulkan/MoltenVK or
// software/Metal) and needs no change to the runtime's input code: the
// runtime sees one more gamepad. Layout and hit testing live in pad_layout.c
// (shared with the layout drawing and the unit tests). It hides while a real
// controller is connected (GCController), unless the user turns that off.
#import <UIKit/UIKit.h>
#import <GameController/GameController.h>
#include <SDL3/SDL.h>
#include <string>
#include "ios_platform.h"
#include "pad_layout.h"

static std::string g_data_dir;

static void copy_tree_if_missing(NSString *from, NSString *to) {
    NSFileManager *fm = NSFileManager.defaultManager;
    NSDirectoryEnumerator *en = [fm enumeratorAtPath:from];
    for (NSString *rel in en) {
        NSString *src = [from stringByAppendingPathComponent:rel];
        NSString *dst = [to stringByAppendingPathComponent:rel];
        BOOL dir = NO;
        [fm fileExistsAtPath:src isDirectory:&dir];
        if (dir) {
            [fm createDirectoryAtPath:dst withIntermediateDirectories:YES attributes:nil error:nil];
        } else if (![fm fileExistsAtPath:dst]) {
            [fm copyItemAtPath:src toPath:dst error:nil];
        }
    }
}

static void write_disc_cfg_if_missing(NSString *docs) {
    NSFileManager *fm = NSFileManager.defaultManager;
    NSString *cfg = [docs stringByAppendingPathComponent:@"disc.cfg"];
    if ([fm fileExistsAtPath:cfg]) return;
    NSString *discDir = [docs stringByAppendingPathComponent:@"disc"];
    [fm createDirectoryAtPath:discDir withIntermediateDirectories:YES attributes:nil error:nil];
    NSArray<NSString *> *names = [[fm contentsOfDirectoryAtPath:discDir error:nil]
        sortedArrayUsingSelector:@selector(compare:)];
    for (NSString *ext in @[@"cue", @"chd", @"bin", @"iso"]) {
        for (NSString *n in names) {
            if ([n.pathExtension.lowercaseString isEqualToString:ext]) {
                // Relative paths in disc.cfg resolve against the game folder.
                NSString *rel = [@"disc" stringByAppendingPathComponent:n];
                [rel writeToFile:cfg atomically:YES encoding:NSUTF8StringEncoding error:nil];
                return;
            }
        }
    }
}

extern "C" const char *ps1ios_data_dir(void) {
    if (!g_data_dir.empty()) return g_data_dir.c_str();
    @autoreleasepool {
        NSString *docs = NSSearchPathForDirectoriesInDomains(NSDocumentDirectory, NSUserDomainMask, YES).firstObject;
        NSString *bundled = [NSBundle.mainBundle.resourcePath stringByAppendingPathComponent:@"GameData"];
        copy_tree_if_missing(bundled, docs);
        // Large, re-creatable data must not go to iCloud backup.
        NSURL *mods = [NSURL fileURLWithPath:[docs stringByAppendingPathComponent:@"mods"]];
        [mods setResourceValue:@YES forKey:NSURLIsExcludedFromBackupKey error:nil];
        write_disc_cfg_if_missing(docs);
        g_data_dir = docs.UTF8String;
    }
    return g_data_dir.c_str();
}

// ---------------------------------------------------------------- touch pad

// Settings (Settings app -> this game, from ios/Settings.bundle).
static NSString *const kPadScale = @"pad_scale";                    // 0.8 .. 1.3
static NSString *const kPadOpacity = @"pad_opacity";                // 0.2 .. 1.0
static NSString *const kPadHaptics = @"pad_haptics";                // BOOL
static NSString *const kPadWithController = @"pad_show_with_controller"; // BOOL

static const uint32_t kDpadBits = PAD_UP | PAD_DOWN | PAD_LEFT | PAD_RIGHT;

@interface PS1TouchPad : UIView
@end

@implementation PS1TouchPad {
    SDL_Joystick *_joy;
    pad_control _c[PAD_MAX_CONTROLS];
    int _n;
    NSMapTable<UITouch *, NSNumber *> *_touches;   // touch -> bits it presses
    uint32_t _held;
    UIImpactFeedbackGenerator *_tap;
    UISelectionFeedbackGenerator *_roll;
    BOOL _haptics;
    CGFloat _opacity;
}

- (instancetype)initWithFrame:(CGRect)f {
    if ((self = [super initWithFrame:f])) {
        self.multipleTouchEnabled = YES;
        self.exclusiveTouch = NO;
        self.backgroundColor = UIColor.clearColor;
        self.opaque = NO;
        self.autoresizingMask = UIViewAutoresizingFlexibleWidth | UIViewAutoresizingFlexibleHeight;
        _touches = [NSMapTable strongToStrongObjectsMapTable];
        _tap = [[UIImpactFeedbackGenerator alloc] initWithStyle:UIImpactFeedbackStyleLight];
        _roll = [UISelectionFeedbackGenerator new];
        NSNotificationCenter *nc = NSNotificationCenter.defaultCenter;
        [nc addObserver:self selector:@selector(settingsChanged) name:GCControllerDidConnectNotification object:nil];
        [nc addObserver:self selector:@selector(settingsChanged) name:GCControllerDidDisconnectNotification object:nil];
        [nc addObserver:self selector:@selector(settingsChanged) name:NSUserDefaultsDidChangeNotification object:nil];
        [self settingsChanged];
    }
    return self;
}

- (void)settingsChanged {
    NSUserDefaults *u = NSUserDefaults.standardUserDefaults;
    _haptics = [u boolForKey:kPadHaptics];
    _opacity = MIN(MAX([u doubleForKey:kPadOpacity], 0.2), 1.0);
    BOOL controller = GCController.controllers.count > 0;
    self.hidden = controller && ![u boolForKey:kPadWithController];
    if (self.hidden) [self releaseAll];
    self.alpha = _opacity;
    [self setNeedsLayout];
}

- (void)safeAreaInsetsDidChange {
    [super safeAreaInsetsDidChange];
    [self setNeedsLayout];
}

- (void)layoutSubviews {
    [super layoutSubviews];
    UIEdgeInsets s = self.safeAreaInsets;
    pad_screen scr = {(float)self.bounds.size.width, (float)self.bounds.size.height,
                      (float)s.left, (float)s.right, (float)s.top, (float)s.bottom,
                      (float)[NSUserDefaults.standardUserDefaults doubleForKey:kPadScale]};
    _n = pad_layout(&scr, _c);
    [self setNeedsDisplay];
}

// ------------------------------------------------------------ SDL output

- (BOOL)ensureJoystick {
    if (_joy) return YES;
    if (!(SDL_WasInit(SDL_INIT_JOYSTICK) & SDL_INIT_JOYSTICK)) return NO;
    SDL_VirtualJoystickDesc d;
    SDL_INIT_INTERFACE(&d);
    d.type = SDL_JOYSTICK_TYPE_GAMEPAD;
    d.naxes = SDL_GAMEPAD_AXIS_COUNT;
    d.nbuttons = SDL_GAMEPAD_BUTTON_COUNT;
    d.name = "Touch Pad";
    SDL_JoystickID id = SDL_AttachVirtualJoystick(&d);
    if (!id) return NO;
    _joy = SDL_OpenJoystick(id);
    return _joy != NULL;
}

- (void)sendToSDL {
    if (![self ensureJoystick]) return;
    static const struct { uint32_t bit; SDL_GamepadButton b; } map[] = {
        {PAD_UP, SDL_GAMEPAD_BUTTON_DPAD_UP}, {PAD_DOWN, SDL_GAMEPAD_BUTTON_DPAD_DOWN},
        {PAD_LEFT, SDL_GAMEPAD_BUTTON_DPAD_LEFT}, {PAD_RIGHT, SDL_GAMEPAD_BUTTON_DPAD_RIGHT},
        // PlayStation layout: Cross = South, Circle = East, Square = West, Triangle = North
        {PAD_CROSS, SDL_GAMEPAD_BUTTON_SOUTH}, {PAD_CIRCLE, SDL_GAMEPAD_BUTTON_EAST},
        {PAD_SQUARE, SDL_GAMEPAD_BUTTON_WEST}, {PAD_TRIANGLE, SDL_GAMEPAD_BUTTON_NORTH},
        {PAD_L1, SDL_GAMEPAD_BUTTON_LEFT_SHOULDER}, {PAD_R1, SDL_GAMEPAD_BUTTON_RIGHT_SHOULDER},
        {PAD_SELECT, SDL_GAMEPAD_BUTTON_BACK}, {PAD_START, SDL_GAMEPAD_BUTTON_START},
    };
    for (size_t i = 0; i < sizeof(map) / sizeof(map[0]); i++)
        SDL_SetJoystickVirtualButton(_joy, map[i].b, (_held & map[i].bit) != 0);
    // L2 / R2 are triggers (axes) on an SDL gamepad: fully pressed or released.
    SDL_SetJoystickVirtualAxis(_joy, SDL_GAMEPAD_AXIS_LEFT_TRIGGER, (_held & PAD_L2) ? SDL_JOYSTICK_AXIS_MAX : 0);
    SDL_SetJoystickVirtualAxis(_joy, SDL_GAMEPAD_AXIS_RIGHT_TRIGGER, (_held & PAD_R2) ? SDL_JOYSTICK_AXIS_MAX : 0);
}

// ------------------------------------------------------------ touches

- (void)recompute {
    uint32_t held = 0;
    for (UITouch *t in _touches) held |= [[_touches objectForKey:t] unsignedIntValue];
    uint32_t pressed = held & ~_held;
    if (_haptics && pressed) {
        // A new button: a light tap. Rolling the thumb to a new d-pad direction: a tick.
        if (pressed & ~kDpadBits) [_tap impactOccurredWithIntensity:0.7];
        else [_roll selectionChanged];
    }
    if (held != _held) {
        _held = held;
        [self sendToSDL];   // right away, on the touch event: no frame of extra latency
        [self setNeedsDisplay];
    }
}

- (void)track:(NSSet<UITouch *> *)touches ended:(BOOL)ended {
    for (UITouch *t in touches) {
        if (ended) { [_touches removeObjectForKey:t]; continue; }
        CGPoint p = [t locationInView:self];
        uint32_t bits = pad_hit(_c, _n, (float)p.x, (float)p.y);
        [_touches setObject:@(bits) forKey:t];
    }
    [self recompute];
    CGFloat target = _touches.count ? MIN(1.0, _opacity + 0.3) : _opacity;
    if (fabs(self.alpha - target) > 0.01)
        [UIView animateWithDuration:_touches.count ? 0.05 : 0.3 animations:^{ self.alpha = target; }];
}

- (void)releaseAll {
    [_touches removeAllObjects];
    [self recompute];
}

- (void)touchesBegan:(NSSet<UITouch *> *)t withEvent:(UIEvent *)e {
    if (_haptics) { [_tap prepare]; [_roll prepare]; }
    [self track:t ended:NO];
}
- (void)touchesMoved:(NSSet<UITouch *> *)t withEvent:(UIEvent *)e { [self track:t ended:NO]; }
- (void)touchesEnded:(NSSet<UITouch *> *)t withEvent:(UIEvent *)e { [self track:t ended:YES]; }
- (void)touchesCancelled:(NSSet<UITouch *> *)t withEvent:(UIEvent *)e { [self track:t ended:YES]; }

// Touches that start outside every control fall through to SDL (menus, etc.).
- (UIView *)hitTest:(CGPoint)p withEvent:(UIEvent *)e {
    if (self.hidden || self.alpha < 0.01) return nil;
    for (int i = 0; i < _n; i++) {
        const pad_control *c = &_c[i];
        float rx = c->w * 0.5f * (c->kind == PAD_KIND_DPAD ? 1.25f : 1.35f) + 6;
        float ry = c->h * 0.5f * (c->kind == PAD_KIND_DPAD ? 1.25f : 1.35f) + 6;
        if (fabs(p.x - c->cx) <= rx && fabs(p.y - c->cy) <= ry) return self;
    }
    return nil;
}

// ------------------------------------------------------------ drawing

static void draw_label(NSString *t, CGPoint c, CGFloat size, CGFloat alpha) {
    UIFont *f = [UIFont systemFontOfSize:size weight:UIFontWeightBold];
    NSDictionary *a = @{NSFontAttributeName: f, NSForegroundColorAttributeName: [UIColor colorWithWhite:1 alpha:alpha]};
    CGSize ts = [t sizeWithAttributes:a];
    [t drawAtPoint:CGPointMake(c.x - ts.width / 2, c.y - ts.height / 2) withAttributes:a];
}

- (void)drawRect:(CGRect)rect {
    UIColor *stroke = [UIColor colorWithWhite:1 alpha:0.6];
    for (int i = 0; i < _n; i++) {
        const pad_control *c = &_c[i];
        BOOL on = (_held & c->bit) != 0;
        CGRect r = CGRectMake(c->cx - c->w / 2, c->cy - c->h / 2, c->w, c->h);
        if (c->kind == PAD_KIND_DPAD) {
            CGFloat R = c->w / 2, arm = R * 0.62, len = R * 0.92, hub = arm / 2;
            [[UIColor colorWithWhite:1 alpha:0.07] setFill];
            UIBezierPath *base = [UIBezierPath bezierPathWithOvalInRect:r];
            [base fill];
            [[UIColor colorWithWhite:1 alpha:0.25] setStroke];
            base.lineWidth = 1.5; [base stroke];
            // One cross (union of two bars, filled once), then the held arms on top.
            UIBezierPath *cross = [UIBezierPath bezierPathWithRoundedRect:
                CGRectMake(c->cx - hub, c->cy - len, arm, 2 * len) cornerRadius:arm * 0.25];
            [cross appendPath:[UIBezierPath bezierPathWithRoundedRect:
                CGRectMake(c->cx - len, c->cy - hub, 2 * len, arm) cornerRadius:arm * 0.25]];
            cross.usesEvenOddFillRule = NO;
            [[UIColor colorWithWhite:1 alpha:0.18] setFill];
            [cross fill];
            struct { uint32_t bit; CGRect rc; NSString *glyph; CGPoint g; } arms[] = {
                {PAD_UP,    CGRectMake(c->cx - hub, c->cy - len, arm, len - hub), @"▲", CGPointMake(c->cx, c->cy - len * 0.62)},
                {PAD_DOWN,  CGRectMake(c->cx - hub, c->cy + hub, arm, len - hub), @"▼", CGPointMake(c->cx, c->cy + len * 0.62)},
                {PAD_LEFT,  CGRectMake(c->cx - len, c->cy - hub, len - hub, arm), @"◀", CGPointMake(c->cx - len * 0.62, c->cy)},
                {PAD_RIGHT, CGRectMake(c->cx + hub, c->cy - hub, len - hub, arm), @"▶", CGPointMake(c->cx + len * 0.62, c->cy)},
            };
            for (auto &a : arms) {
                BOOL armOn = (_held & a.bit) != 0;
                if (armOn) {
                    [[UIColor colorWithWhite:1 alpha:0.42] setFill];
                    [[UIBezierPath bezierPathWithRoundedRect:a.rc cornerRadius:arm * 0.25] fill];
                }
                draw_label(a.glyph, a.g, arm * 0.42, armOn ? 1.0 : 0.85);
            }
            continue;
        }
        if (on) r = CGRectInset(r, c->w * 0.03, c->h * 0.03);   // pressed: slightly smaller
        UIBezierPath *p = c->kind == PAD_KIND_ROUND
            ? [UIBezierPath bezierPathWithOvalInRect:r]
            : [UIBezierPath bezierPathWithRoundedRect:r cornerRadius:r.size.height / 2];
        [[UIColor colorWithWhite:1 alpha:on ? 0.5 : 0.16] setFill];
        [p fill];
        [stroke setStroke];
        p.lineWidth = 1.5;
        [p stroke];
        NSString *t = [NSString stringWithUTF8String:c->label];
        CGFloat size = c->kind == PAD_KIND_ROUND ? c->h * 0.44 : MIN(c->h * 0.36, c->w * 0.2);
        draw_label(t, CGPointMake(c->cx, c->cy), size, on ? 1.0 : 0.9);
    }
}
@end

// Attach the pad to SDL's window as soon as it becomes visible. No runtime
// code calls into this: the static initialiser registers the observer.
__attribute__((constructor)) static void ps1ios_install_touch_pad(void) {
    // iOS forbids loading code made at run time (no tcc + dlopen of overlay
    // shards): overlays come only from the ahead-of-time build; the rest runs
    // in psxrecomp's interpreter.
    setenv("PSX_OVERLAY_AUTOCOMPILE_OFF", "1", 1);
    // Dim the home indicator and defer the system edge swipes, so a thumb on
    // the pad near a screen edge is not taken by iOS (SDL hint, read from env).
    setenv("SDL_IOS_HIDE_HOME_INDICATOR", "2", 0);
    [NSUserDefaults.standardUserDefaults registerDefaults:@{
        kPadScale: @1.0, kPadOpacity: @0.6, kPadHaptics: @YES, kPadWithController: @NO}];
    [NSNotificationCenter.defaultCenter addObserverForName:UIWindowDidBecomeVisibleNotification
        object:nil queue:NSOperationQueue.mainQueue usingBlock:^(NSNotification *n) {
            UIWindow *w = n.object;
            if (!w.rootViewController) return;
            UIView *root = w.rootViewController.view;
            for (UIView *v in root.subviews)
                if ([v isKindOfClass:PS1TouchPad.class]) return;
            [root addSubview:[[PS1TouchPad alloc] initWithFrame:root.bounds]];
        }];
}

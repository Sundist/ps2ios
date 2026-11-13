// iOS platform layer: data folder, first-run copy, disc discovery, touch pad.
// The touch pad is a UIKit view over SDL's window that drives an SDL3
// virtual gamepad, so it works with every renderer (Vulkan/MoltenVK or
// software/Metal) and needs no change to the runtime's input code: the
// runtime sees one more gamepad. Layout and hit testing live in pad_layout.c
// (shared with the layout drawing and the unit tests). It hides while a real
// controller is connected (GCController), unless the user turns that off.
#import <UIKit/UIKit.h>
#import <QuartzCore/QuartzCore.h>
#import <GameController/GameController.h>
#include <SDL3/SDL.h>
#include <string>
#include "ios_platform.h"
#include "pad_layout.h"
#include "disc_probe.h"
#include "game_config.h"

static std::string g_data_dir;

// Copies a file or folder tree. Existing files are replaced only when
// `overwrite` is set (files that ship with the app), never otherwise (saves,
// settings, the user's disc).
static void copy_tree(NSString *from, NSString *to, BOOL overwrite) {
    NSFileManager *fm = NSFileManager.defaultManager;
    BOOL isDir = NO;
    if (![fm fileExistsAtPath:from isDirectory:&isDir]) return;
    if (!isDir) {
        if ([fm fileExistsAtPath:to]) {
            if (!overwrite) return;
            [fm removeItemAtPath:to error:nil];
        }
        [fm createDirectoryAtPath:to.stringByDeletingLastPathComponent withIntermediateDirectories:YES attributes:nil error:nil];
        [fm copyItemAtPath:from toPath:to error:nil];
        return;
    }
    [fm createDirectoryAtPath:to withIntermediateDirectories:YES attributes:nil error:nil];
    for (NSString *rel in [fm enumeratorAtPath:from]) {
        NSString *src = [from stringByAppendingPathComponent:rel];
        NSString *dst = [to stringByAppendingPathComponent:rel];
        BOOL d = NO;
        [fm fileExistsAtPath:src isDirectory:&d];
        if (d) {
            [fm createDirectoryAtPath:dst withIntermediateDirectories:YES attributes:nil error:nil];
        } else if (![fm fileExistsAtPath:dst] || overwrite) {
            [fm removeItemAtPath:dst error:nil];
            [fm copyItemAtPath:src toPath:dst error:nil];
        }
    }
}

// What the psxrecomp build stages beside the executable (inside the .app on
// iOS) and the runtime reads from its game folder (Documents on iOS).
static NSArray<NSString *> *bundled_runtime_items(void) {
    return @[@"game.toml", @"game_options.toml", @"assets", @"bios", @"mods", @"licenses",
             @"psx_game_version.txt"];
}

// Refreshes the shipped files in Documents once per app build (keyed by the
// executable's modification date), so an update brings new game files while
// saves and settings stay.
static void sync_bundle(NSString *docs) {
    NSFileManager *fm = NSFileManager.defaultManager;
    NSString *res = NSBundle.mainBundle.resourcePath;
    NSDate *built = [fm attributesOfItemAtPath:NSBundle.mainBundle.executablePath error:nil].fileModificationDate;
    NSString *stamp = [NSString stringWithFormat:@"%.0f", built.timeIntervalSince1970];
    NSString *stampPath = [docs stringByAppendingPathComponent:@".ps1ios_bundle_stamp"];
    NSString *old = [NSString stringWithContentsOfFile:stampPath encoding:NSUTF8StringEncoding error:nil];
    BOOL refresh = ![old isEqualToString:stamp];
    for (NSString *item in bundled_runtime_items())
        copy_tree([res stringByAppendingPathComponent:item], [docs stringByAppendingPathComponent:item], refresh);
    copy_tree([res stringByAppendingPathComponent:@"GameData"], docs, refresh);
    if (refresh) [stamp writeToFile:stampPath atomically:YES encoding:NSUTF8StringEncoding error:nil];
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

// ---------------------------------------------------------------- universal player
//
// A universal build (GameData/ps1ios_universal in the bundle) is not tied to
// the disc it was built from. It runs whatever disc is in Documents/disc: the
// runtime is told about that disc through game.toml, and PSX_FORCE_INTERP makes
// all game code run in psxrecomp's interpreter (no code compiled for another
// game is ever used). iOS allows an interpreter; it does not allow generating
// native code on the phone.

static BOOL ps1ios_is_universal(void) {
    NSString *flag = [NSBundle.mainBundle.resourcePath stringByAppendingPathComponent:@"GameData/ps1ios_universal"];
    return [NSFileManager.defaultManager fileExistsAtPath:flag];
}

// Disc images in Documents/disc a game can start from: every .cue, .chd and
// .iso, and every .bin/.img no cue sheet names.
static NSArray<NSString *> *ps1ios_discs(NSString *discDir) {
    NSFileManager *fm = NSFileManager.defaultManager;
    NSArray<NSString *> *names = [[fm contentsOfDirectoryAtPath:discDir error:nil]
        sortedArrayUsingSelector:@selector(localizedCaseInsensitiveCompare:)];
    NSMutableSet<NSString *> *tracks = [NSMutableSet set];
    NSMutableArray<NSString *> *out = [NSMutableArray array];
    for (NSString *n in names) {
        if (![n.pathExtension.lowercaseString isEqualToString:@"cue"]) continue;
        [out addObject:n];
        NSString *text = [NSString stringWithContentsOfFile:[discDir stringByAppendingPathComponent:n]
                                                   encoding:NSISOLatin1StringEncoding error:nil];
        for (NSString *other in names)
            if (other != n && [text rangeOfString:other options:NSCaseInsensitiveSearch].location != NSNotFound)
                [tracks addObject:other];
    }
    for (NSString *n in names) {
        NSString *e = n.pathExtension.lowercaseString;
        if ([e isEqualToString:@"chd"] || [e isEqualToString:@"iso"] ||
            (([e isEqualToString:@"bin"] || [e isEqualToString:@"img"]) && ![tracks containsObject:n]))
            [out addObject:n];
    }
    return out;
}

// More than one game in Documents/disc: ask which one (a native alert; SDL shows
// it without needing its video subsystem). The choice is remembered and offered first.
static NSString *ps1ios_choose_disc(NSArray<NSString *> *discs) {
    if (discs.count == 0) return nil;
    if (discs.count == 1) return discs[0];
    NSUserDefaults *u = NSUserDefaults.standardUserDefaults;
    NSString *last = [u stringForKey:@"last_disc"];
    NSMutableArray<NSString *> *order = [discs mutableCopy];
    if (last && [order containsObject:last]) { [order removeObject:last]; [order insertObject:last atIndex:0]; }
    const int n = (int)MIN(order.count, (NSUInteger)8);
    SDL_MessageBoxButtonData buttons[8];
    std::string labels[8];
    for (int i = 0; i < n; i++) {
        labels[i] = order[i].stringByDeletingPathExtension.UTF8String;
        buttons[i].flags = i == 0 ? SDL_MESSAGEBOX_BUTTON_RETURNKEY_DEFAULT : 0;
        buttons[i].buttonID = i;
        buttons[i].text = labels[i].c_str();
    }
    SDL_MessageBoxData box = {};
    box.flags = SDL_MESSAGEBOX_INFORMATION;
    box.title = "Choose a game";
    box.message = order.count > 8 ? "Showing the first 8 discs in Documents/disc." : "Discs in Documents/disc";
    box.numbuttons = n;
    box.buttons = buttons;
    int picked = 0;
    if (!SDL_ShowMessageBox(&box, &picked) || picked < 0 || picked >= n) picked = 0;
    [u setObject:order[picked] forKey:@"last_disc"];
    return order[picked];
}

static void ps1ios_prepare_universal(NSString *docs) {
    NSFileManager *fm = NSFileManager.defaultManager;
    NSString *discDir = [docs stringByAppendingPathComponent:@"disc"];
    [fm createDirectoryAtPath:discDir withIntermediateDirectories:YES attributes:nil error:nil];
    NSString *disc = ps1ios_choose_disc(ps1ios_discs(discDir));
    if (!disc) {
        NSLog(@"ps1ios: universal player: no disc in Documents/disc");
        SDL_ShowSimpleMessageBox(SDL_MESSAGEBOX_INFORMATION, "No game yet",
            "Copy your PS1 disc image (.cue + .bin, .chd, .bin or .iso) into this app's \"disc\" folder "
            "with the Files app, then open the app again.", NULL);
        return;
    }
    NSString *rel = [@"disc" stringByAppendingPathComponent:disc];
    [rel writeToFile:[docs stringByAppendingPathComponent:@"disc.cfg"] atomically:YES
            encoding:NSUTF8StringEncoding error:nil];

    // Describe this disc to the runtime: start from the bundled game.toml each time.
    NSString *path = [discDir stringByAppendingPathComponent:disc];
    char track[2048];
    if ([disc.pathExtension.lowercaseString isEqualToString:@"cue"]) {
        if (!ps1_cue_first_track(path.fileSystemRepresentation, track, sizeof track)) track[0] = 0;
    } else {
        snprintf(track, sizeof track, "%s", path.fileSystemRepresentation);
    }
    ps1_disc_info info;
    char err[128] = "";
    if (!track[0] || !ps1_disc_probe(track, &info, err, sizeof err)) {
        // e.g. a .chd (compressed, not read here): the runtime still mounts it,
        // and warns once that the serial differs from its game.toml.
        NSLog(@"ps1ios: universal player: %@ not identified (%s); game.toml left as shipped", disc, err);
        return;
    }
    NSString *shipped = [NSBundle.mainBundle.resourcePath stringByAppendingPathComponent:@"GameData/game.toml"];
    NSString *toml = [NSString stringWithContentsOfFile:shipped encoding:NSUTF8StringEncoding error:nil];
    if (!toml) return;
    std::string patched = ps1ios_game_toml_for_disc(toml.UTF8String, info, rel.UTF8String);
    [[NSString stringWithUTF8String:patched.c_str()] writeToFile:[docs stringByAppendingPathComponent:@"game.toml"]
                                                      atomically:YES encoding:NSUTF8StringEncoding error:nil];
    NSLog(@"ps1ios: universal player: %@ -> %s (%s), entry 0x%08X, load 0x%08X, text 0x%X", disc,
          info.serial[0] ? info.serial : "no serial", info.boot, info.entry_pc, info.load_address, info.text_size);
}

extern "C" const char *ps1ios_data_dir(void) {
    if (!g_data_dir.empty()) return g_data_dir.c_str();
    @autoreleasepool {
        NSString *docs = NSSearchPathForDirectoriesInDomains(NSDocumentDirectory, NSUserDomainMask, YES).firstObject;
        sync_bundle(docs);
        // Large, re-creatable data must not go to iCloud backup.
        NSURL *mods = [NSURL fileURLWithPath:[docs stringByAppendingPathComponent:@"mods"]];
        [mods setResourceValue:@YES forKey:NSURLIsExcludedFromBackupKey error:nil];
        if (ps1ios_is_universal()) ps1ios_prepare_universal(docs);
        else write_disc_cfg_if_missing(docs);
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

// Self-test mode (PS1IOS_PAD_DEMO): the iOS simulator always reports an MFi
// "Gamepad"; the test treats it as absent so the touch pad is player 1, as on
// an iPhone with no controller connected.
static BOOL g_ignore_controllers;
static CFTimeInterval g_start_time;

@interface PS1TouchPad : UIView
- (void)demoHold:(uint32_t)bits;
- (BOOL)ensureJoystick;
- (void)logInputDevices;
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
    uint32_t _demo;     // buttons held by the PS1IOS_PAD_DEMO self-test
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
    BOOL controller = !g_ignore_controllers && GCController.controllers.count > 0;
    self.hidden = controller && ![u boolForKey:kPadWithController];
    if (self.hidden) {
        [self releaseAll];
        // Take the touch pad out of SDL entirely, so psxrecomp moves player 1
        // to the real controller (it rebinds when its device is removed).
        [self detachJoystick];
    } else {
        [self ensureJoystick];
    }
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
    NSLog(@"ps1ios: touch pad virtual gamepad id %u %s", (unsigned)id, _joy ? "open" : SDL_GetError());
    return _joy != NULL;
}

- (void)detachJoystick {
    if (!_joy) return;
    SDL_JoystickID id = SDL_GetJoystickID(_joy);
    SDL_CloseJoystick(_joy);
    _joy = NULL;
    SDL_DetachVirtualJoystick(id);
    NSLog(@"ps1ios: touch pad virtual gamepad %u detached (a controller is connected)", (unsigned)id);
}

- (void)logInputDevices {
    for (GCController *c in GCController.controllers)
        NSLog(@"ps1ios: GCController '%@' (%@)", c.vendorName, c.productCategory);
    if (!(SDL_WasInit(SDL_INIT_JOYSTICK) & SDL_INIT_JOYSTICK)) return;
    int n = 0;
    SDL_JoystickID *ids = SDL_GetJoysticks(&n);
    for (int i = 0; ids && i < n; i++)
        NSLog(@"ps1ios: SDL joystick %u '%s' gamepad=%d virtual=%d", (unsigned)ids[i],
              SDL_GetJoystickNameForID(ids[i]) ?: "?", SDL_IsGamepad(ids[i]), SDL_IsJoystickVirtual(ids[i]));
    SDL_free(ids);
    NSLog(@"ps1ios: touch pad hidden=%d alpha=%.2f frame=%@", self.hidden, self.alpha, NSStringFromCGRect(self.frame));
}

- (void)sendToSDL {
    if (self.hidden || ![self ensureJoystick]) return;
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
    held |= _demo;
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

// Self-test (PS1IOS_PAD_DEMO=1): hold buttons as if touched, to check the whole
// input path (overlay -> SDL virtual gamepad -> psxrecomp -> the game) in CI.
- (void)demoHold:(uint32_t)bits {
    _demo = bits;
    [self recompute];
    NSLog(@"ps1ios: pad demo holding 0x%x (joystick %s)", bits, _joy ? "attached" : "not attached");
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
    if (g_ignore_controllers) {
        // Self-test only: real time since the app started, in tenths of a second, as 16
        // binary boxes (bit 15 on the left) in the bottom-left corner. With the test ROM's
        // frame counter in the same screenshot this gives the game's real frame rate.
        uint32_t ds = (uint32_t)((CACurrentMediaTime() - g_start_time) * 10.0);
        CGFloat y = self.bounds.size.height - 12;
        for (int i = 0; i < 16; i++) {
            [((ds >> (15 - i)) & 1) ? UIColor.whiteColor : [UIColor colorWithWhite:0.15 alpha:1] setFill];
            UIRectFill(CGRectMake(30 + i * 9, y, 7, 7));
        }
    }
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

static PS1TouchPad *g_pad;
static BOOL g_demo_started;

static UIWindow *ps1ios_game_window(void) {
    UIWindow *best = nil;
    for (UIScene *sc in UIApplication.sharedApplication.connectedScenes) {
        if (![sc isKindOfClass:UIWindowScene.class]) continue;
        for (UIWindow *w in ((UIWindowScene *)sc).windows) {
            if (w.isKeyWindow) return w;
            if (!best && !w.hidden) best = w;
        }
    }
    return best;
}

static void ps1ios_attach_pad(void) {
    UIWindow *w = ps1ios_game_window();
    if (!w) return;
    UIView *host = w.rootViewController.view ?: w;
    if (!g_pad) g_pad = [[PS1TouchPad alloc] initWithFrame:host.bounds];
    if (g_pad.superview != host) {
        [g_pad removeFromSuperview];
        g_pad.frame = host.bounds;
        [host addSubview:g_pad];
        NSLog(@"ps1ios: touch pad attached to %@ %@ (hidden=%d)", NSStringFromClass(host.class),
              NSStringFromCGRect(host.bounds), g_pad.hidden);
    } else if (host.subviews.lastObject != g_pad) {
        [host bringSubviewToFront:g_pad];
    }
}

// The pad is attached from a timer started at launch. No runtime code calls
// into this file for it: the static initialiser registers the observer.
__attribute__((constructor)) static void ps1ios_install_touch_pad(void) {
    // iOS forbids loading code made at run time (no tcc + dlopen of overlay
    // shards): overlays come only from the ahead-of-time build; the rest runs
    // in psxrecomp's interpreter.
    setenv("PSX_OVERLAY_AUTOCOMPILE_OFF", "1", 1);
    // Universal player: all game code runs in the interpreter (see above).
    if (ps1ios_is_universal()) setenv("PSX_FORCE_INTERP", "1", 1);
    if (getenv("PS1IOS_PAD_DEMO")) {
        g_ignore_controllers = YES;
        g_start_time = CACurrentMediaTime();
        setenv("SDL_JOYSTICK_MFI", "0", 1);   // hide the simulator's MFi "Gamepad" from SDL
    }
    // Dim the home indicator and defer the system edge swipes, so a thumb on
    // the pad near a screen edge is not taken by iOS (SDL hint, read from env).
    setenv("SDL_IOS_HIDE_HOME_INDICATOR", "2", 0);
    [NSUserDefaults.standardUserDefaults registerDefaults:@{
        kPadScale: @1.0, kPadOpacity: @0.6, kPadHaptics: @YES, kPadWithController: @NO}];
    [NSNotificationCenter.defaultCenter addObserverForName:UIApplicationDidFinishLaunchingNotification
        object:nil queue:NSOperationQueue.mainQueue usingBlock:^(NSNotification *n) {
            // SDL creates its window and Metal view after launch and may add views
            // on top later, so (re)attach the pad and keep it in front.
            NSDate *start = [NSDate date];
            __block int ticks = 0;
            if (g_ignore_controllers)   // self-test clock: redraw 20 times a second
                [NSTimer scheduledTimerWithTimeInterval:0.05 repeats:YES block:^(NSTimer *t) {
                    [g_pad setNeedsDisplay];
                }];
            [NSTimer scheduledTimerWithTimeInterval:0.5 repeats:YES block:^(NSTimer *t) {
                ps1ios_attach_pad();
                // Present the touch pad to SDL as soon as its joystick layer is up,
                // so psxrecomp sees it when it binds player 1.
                if (g_pad && !g_pad.hidden) [g_pad ensureJoystick];
                if (++ticks == 20 && g_pad) [g_pad logInputDevices];
                if (g_pad && getenv("PS1IOS_PAD_DEMO") && !g_demo_started && -start.timeIntervalSinceNow > 15) {
                    g_demo_started = YES;
                    [g_pad demoHold:PAD_RIGHT | PAD_CROSS];
                }
            }];
        }];
}

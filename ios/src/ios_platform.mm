// iOS platform layer: data folder, first-run copy, disc discovery, touch pad.
// The touch pad is a UIKit view over SDL's window that drives an SDL3
// virtual gamepad, so it works with every renderer (Vulkan/MoltenVK or
// software/Metal) and needs no change to the runtime's input code: the
// runtime sees one more gamepad. It hides while a real controller is
// connected (GCController), as NX2Apple's touch layer does.
#import <UIKit/UIKit.h>
#import <GameController/GameController.h>
#include <SDL3/SDL.h>
#include <string>
#include "ios_platform.h"

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

@interface PS1TouchPad : UIView
@end

@implementation PS1TouchPad {
    SDL_Joystick *_joy;
    NSMutableDictionary<NSValue *, NSNumber *> *_touches; // touch -> button id
    NSArray<NSDictionary *> *_buttons;                    // {id, rect, title}
    int _dpad;                                            // bitmask held via d-pad touches
}

static const int kDpadUp = 1000, kDpadDown = 1001, kDpadLeft = 1002, kDpadRight = 1003;

- (instancetype)initWithFrame:(CGRect)f {
    if ((self = [super initWithFrame:f])) {
        self.multipleTouchEnabled = YES;
        self.backgroundColor = UIColor.clearColor;
        self.autoresizingMask = UIViewAutoresizingFlexibleWidth | UIViewAutoresizingFlexibleHeight;
        _touches = [NSMutableDictionary new];
        [NSNotificationCenter.defaultCenter addObserver:self selector:@selector(controllersChanged)
            name:GCControllerDidConnectNotification object:nil];
        [NSNotificationCenter.defaultCenter addObserver:self selector:@selector(controllersChanged)
            name:GCControllerDidDisconnectNotification object:nil];
        [self controllersChanged];
    }
    return self;
}

- (void)controllersChanged {
    // Real pad connected -> hide the touch pad (but keep the virtual one idle).
    self.hidden = GCController.controllers.count > 0;
}

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

- (void)layoutSubviews {
    [super layoutSubviews];
    CGRect b = self.bounds;
    UIEdgeInsets s = self.safeAreaInsets;
    CGFloat r = MIN(b.size.height * 0.11, 46.0);   // button radius (pt)
    CGFloat L = s.left + 24, R = b.size.width - s.right - 24, B = b.size.height - s.bottom - 18;
    CGPoint dc = CGPointMake(L + r * 2.3, B - r * 2.3);            // d-pad centre
    CGPoint fc = CGPointMake(R - r * 2.3, B - r * 2.3);            // face centre
    auto btn = ^NSDictionary *(int bid, CGPoint c, CGFloat rr, NSString *t) {
        return @{@"id": @(bid), @"rect": [NSValue valueWithCGRect:CGRectMake(c.x - rr, c.y - rr, rr * 2, rr * 2)], @"title": t};
    };
    _buttons = @[
        btn(kDpadUp,    CGPointMake(dc.x, dc.y - r * 1.5), r, @"▲"),
        btn(kDpadDown,  CGPointMake(dc.x, dc.y + r * 1.5), r, @"▼"),
        btn(kDpadLeft,  CGPointMake(dc.x - r * 1.5, dc.y), r, @"◀"),
        btn(kDpadRight, CGPointMake(dc.x + r * 1.5, dc.y), r, @"▶"),
        // PS layout: Cross = SOUTH, Circle = EAST, Square = WEST, Triangle = NORTH
        btn(SDL_GAMEPAD_BUTTON_SOUTH, CGPointMake(fc.x, fc.y + r * 1.5), r, @"✕"),
        btn(SDL_GAMEPAD_BUTTON_EAST,  CGPointMake(fc.x + r * 1.5, fc.y), r, @"○"),
        btn(SDL_GAMEPAD_BUTTON_WEST,  CGPointMake(fc.x - r * 1.5, fc.y), r, @"□"),
        btn(SDL_GAMEPAD_BUTTON_NORTH, CGPointMake(fc.x, fc.y - r * 1.5), r, @"△"),
        btn(SDL_GAMEPAD_BUTTON_LEFT_SHOULDER,  CGPointMake(L + r, s.top + r + 12), r * 0.8, @"L1"),
        btn(SDL_GAMEPAD_BUTTON_RIGHT_SHOULDER, CGPointMake(R - r, s.top + r + 12), r * 0.8, @"R1"),
        btn(SDL_GAMEPAD_BUTTON_BACK,  CGPointMake(b.size.width * 0.5 - r * 1.2, B - r * 0.5), r * 0.55, @"SEL"),
        btn(SDL_GAMEPAD_BUTTON_START, CGPointMake(b.size.width * 0.5 + r * 1.2, B - r * 0.5), r * 0.55, @"STA"),
    ];
    [self setNeedsDisplay];
}

- (int)buttonAt:(CGPoint)p {
    for (NSDictionary *d in _buttons) {
        CGRect rc = CGRectInset([d[@"rect"] CGRectValue], -10, -10);  // forgiving hit area
        if (CGRectContainsPoint(rc, p)) return [d[@"id"] intValue];
    }
    return -1;
}

- (void)apply {
    if (![self ensureJoystick]) return;
    NSSet *held = [NSSet setWithArray:_touches.allValues];
    for (int bid = 0; bid < SDL_GAMEPAD_BUTTON_COUNT; bid++) {
        bool down = [held containsObject:@(bid)];
        if (bid == SDL_GAMEPAD_BUTTON_DPAD_UP)    down = [held containsObject:@(kDpadUp)];
        if (bid == SDL_GAMEPAD_BUTTON_DPAD_DOWN)  down = [held containsObject:@(kDpadDown)];
        if (bid == SDL_GAMEPAD_BUTTON_DPAD_LEFT)  down = [held containsObject:@(kDpadLeft)];
        if (bid == SDL_GAMEPAD_BUTTON_DPAD_RIGHT) down = [held containsObject:@(kDpadRight)];
        SDL_SetJoystickVirtualButton(_joy, bid, down);
    }
    [self setNeedsDisplay];
}

- (void)track:(NSSet<UITouch *> *)touches ended:(BOOL)ended {
    for (UITouch *t in touches) {
        NSValue *k = [NSValue valueWithNonretainedObject:t];
        if (ended) { [_touches removeObjectForKey:k]; continue; }
        int bid = [self buttonAt:[t locationInView:self]];
        if (bid >= 0) _touches[k] = @(bid); else [_touches removeObjectForKey:k];
    }
    [self apply];
}
- (void)touchesBegan:(NSSet<UITouch *> *)t withEvent:(UIEvent *)e { [self track:t ended:NO]; }
- (void)touchesMoved:(NSSet<UITouch *> *)t withEvent:(UIEvent *)e { [self track:t ended:NO]; }
- (void)touchesEnded:(NSSet<UITouch *> *)t withEvent:(UIEvent *)e { [self track:t ended:YES]; }
- (void)touchesCancelled:(NSSet<UITouch *> *)t withEvent:(UIEvent *)e { [self track:t ended:YES]; }

// Touches outside the buttons fall through to SDL (menus that use touch/mouse).
- (UIView *)hitTest:(CGPoint)p withEvent:(UIEvent *)e {
    return (!self.hidden && [self buttonAt:p] >= 0) ? self : nil;
}

- (void)drawRect:(CGRect)rect {
    NSSet *held = [NSSet setWithArray:_touches.allValues];
    for (NSDictionary *d in _buttons) {
        CGRect rc = [d[@"rect"] CGRectValue];
        BOOL on = [held containsObject:d[@"id"]];
        UIBezierPath *p = [UIBezierPath bezierPathWithOvalInRect:rc];
        [[UIColor colorWithWhite:1 alpha:on ? 0.38 : 0.14] setFill];
        [[UIColor colorWithWhite:1 alpha:0.55] setStroke];
        p.lineWidth = 2;
        [p fill]; [p stroke];
        NSString *t = d[@"title"];
        UIFont *f = [UIFont systemFontOfSize:rc.size.height * (t.length > 1 ? 0.28 : 0.42) weight:UIFontWeightSemibold];
        NSDictionary *a = @{NSFontAttributeName: f, NSForegroundColorAttributeName: [UIColor colorWithWhite:1 alpha:0.85]};
        CGSize ts = [t sizeWithAttributes:a];
        [t drawAtPoint:CGPointMake(CGRectGetMidX(rc) - ts.width / 2, CGRectGetMidY(rc) - ts.height / 2) withAttributes:a];
    }
}
@end

// Attach the pad to SDL's window as soon as it becomes visible. No runtime
// code calls into this: the static initialiser registers the observer.
__attribute__((constructor)) static void ps1ios_install_touch_pad(void) {
    // iOS forbids loading code made at run time (no tcc + dlopen of overlay
    // shards): overlays come only from the ahead-of-time build
    // (aot/overlays.json -> generated/overlays_static.c).
    setenv("PSX_OVERLAY_AUTOCOMPILE_OFF", "1", 1);
    [NSNotificationCenter.defaultCenter addObserverForName:UIWindowDidBecomeVisibleNotification
        object:nil queue:NSOperationQueue.mainQueue usingBlock:^(NSNotification *n) {
            UIWindow *w = n.object;
            if (!w.rootViewController) return;
            for (UIView *v in w.rootViewController.view.subviews)
                if ([v isKindOfClass:PS1TouchPad.class]) return;
            UIView *root = w.rootViewController.view;
            PS1TouchPad *pad = [[PS1TouchPad alloc] initWithFrame:root.bounds];
            [root addSubview:pad];
        }];
}

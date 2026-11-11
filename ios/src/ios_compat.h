/* Force-included into every psx-runtime source on iOS (see ios/ios.cmake).
 *
 * iOS has no process spawning: system() is declared unavailable in the iOS
 * SDK, so any call to it fails to compile. psxrecomp calls it only on
 * desktop-only paths (running tools/prepare_disc.py, mkdir in the debug
 * server). On iOS those report failure (-1) instead. */
#ifndef PS1IOS_COMPAT_H
#define PS1IOS_COMPAT_H
#if defined(__APPLE__)
#include <TargetConditionals.h>
#if TARGET_OS_IPHONE
#include <stdlib.h>
#ifdef __cplusplus
#include <cstdlib>
#endif
static inline int ps1ios_system(const char *cmd) { (void)cmd; return -1; }
#define system ps1ios_system
#ifdef __cplusplus
namespace std { using ::ps1ios_system; }
#endif
#endif
#endif
#endif

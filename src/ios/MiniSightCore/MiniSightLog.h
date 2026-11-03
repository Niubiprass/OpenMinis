#ifndef MINISIGHT_LOG_H
#define MINISIGHT_LOG_H
#import <Foundation/Foundation.h>

/// Async, bounded local diagnostics. Disabled by default. No credential ever
/// passes through here; callers log status/counters only.
#ifdef __cplusplus
extern "C" {
#endif
void MSDiagConfigure(BOOL enabled, NSString * _Nullable container);
void MSDiag(NSString * _Nonnull format, ...) NS_FORMAT_FUNCTION(1, 2);
#ifdef __cplusplus
}
#endif
#endif

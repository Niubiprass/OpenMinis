#ifndef MINISIGHT_LOG_H
#define MINISIGHT_LOG_H
#import <Foundation/Foundation.h>

/// Async, bounded local diagnostics; callable on any thread. With a valid
/// container, basic MSDiagEvent records are ALWAYS ON. enabled controls only
/// detailed legacy MSDiag/MSDiagMessage records (off by default).
/// Only status, counters and static ASCII identifiers are allowed. Never pass
/// credentials, endpoint URLs, prompts/personas, names, messages or audio content.
/// Files: Documents/MiniSight/diagnostic-{app,plugin}.log (+ .1), mode 0600.
/// Each line: UTC time, pid, process, per-process runId, seq, event=<JSON>.
#ifdef __cplusplus
extern "C" {
#endif
void MSDiagConfigure(BOOL enabled, NSString * _Nullable container);
void MSDiag(NSString * _Nonnull format, ...) NS_FORMAT_FUNCTION(1, 2);
void MSDiagMessage(NSString * _Nonnull message);
/// feature/stage/result are fixed ASCII enums (README).
/// Unknown fields and unsafe values are dropped, never stringified.
void MSDiagEvent(NSString * _Nonnull feature, NSString * _Nonnull stage,
                 NSString * _Nonnull result,
                 NSDictionary<NSString *, id> * _Nullable fields);
/// Observed fixed-key numeric values only; pending never means applied.
void MSDiagSettingsSnapshot(NSString * _Nonnull stage, NSString * _Nonnull source,
                            NSDictionary<NSString *, id> * _Nonnull preferences);
#ifdef __cplusplus
}
#endif
#endif

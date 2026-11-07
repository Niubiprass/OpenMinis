#import "MiniSightLog.h"
#include <stdatomic.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <errno.h>
#include <math.h>

static const NSUInteger MSDiagMaxBytes = 200 * 1024;
static atomic_bool MSDiagEnabled, MSDiagAvailable;
static atomic_ulong MSDiagConfigGeneration, MSDiagDetailGeneration;
static NSLock *MSDiagConfigLock;
static NSString *MSDiagContainer, *MSDiagRunID, *MSDiagProcess, *MSDiagFile;
static dispatch_queue_t MSDiagQueue;
static NSDateFormatter *MSDiagDate;
static NSSet *MSDiagFeatures, *MSDiagStages, *MSDiagResults, *MSDiagKeys;
static NSUInteger MSDiagPending;
static unsigned long long MSDiagSequence;

// Static ASCII identifiers only, not a general-purpose string logger.
static BOOL MSDiagIdentifier(id value) {
    if (![value isKindOfClass:NSString.class]) return NO;
    NSString *s = value;
    if (!s.length || s.length > 80) return NO;
    for (NSUInteger i = 0; i < s.length; i++) {
        unichar c = [s characterAtIndex:i];
        if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
              (c >= '0' && c <= '9') || c == '.' || c == '_' || c == '-')) return NO;
    }
    NSString *lower = s.lowercaseString;
    return ![lower hasPrefix:@"sk-"] && ![lower hasPrefix:@"sk_"] &&
           ![lower hasPrefix:@"bearer"] && ![lower containsString:@"apikey"] &&
           ![lower containsString:@"api_key"] && ![lower containsString:@"token"];
}

static NSString *MSDiagRequest(id value) {
    if (![value isKindOfClass:NSString.class] || [value length] > 80) return nil;
    NSArray *parts = [value componentsSeparatedByString:@"/"];
    if (parts.count == 1) parts = [value componentsSeparatedByString:@"."];
    if (parts.count > 2) return nil;
    NSUUID *uuid = [[NSUUID alloc] initWithUUIDString:parts.firstObject];
    if (!uuid) return nil;
    if (parts.count == 1) return uuid.UUIDString;
    NSString *generation = parts[1];
    if (!generation.length || generation.length > 15) return nil;
    for (NSUInteger i = 0; i < generation.length; i++)
        if ([generation characterAtIndex:i] < '0' || [generation characterAtIndex:i] > '9') return nil;
    return [NSString stringWithFormat:@"%@.%@", uuid.UUIDString, generation];
}

static BOOL MSDiagEnum(NSString *key, NSString *value) {
    static NSDictionary<NSString *, NSSet<NSString *> *> *allowed; static dispatch_once_t once;
    dispatch_once(&once, ^{ allowed = @{
        @"action": [NSSet setWithArray:@[@"none", @"interact", @"input", @"voice", @"menu", @"record", @"conversation"]],
        @"old": [NSSet setWithArray:@[@"none", @"interact", @"input", @"voice", @"menu", @"record", @"conversation", @"lively", @"quiet", @"off", @"natural", @"dark", @"light", @"above", @"below", @"system", @"send", @"return", @"0", @"1", @"2", @"3"]],
        @"new": [NSSet setWithArray:@[@"none", @"interact", @"input", @"voice", @"menu", @"record", @"conversation", @"lively", @"quiet", @"off", @"natural", @"dark", @"light", @"above", @"below", @"system", @"send", @"return", @"0", @"1", @"2", @"3"]],
        @"route": [NSSet setWithArray:@[@"idle", @"user", @"controller", @"approval", @"pet", @"bubble", @"chat", @"none", @"allow", @"deny", @"stopped", @"pet_off_or_not_pet_style", @"burst", @"reply"]],
        @"setting": [NSSet setWithArray:@[@"ai_adjust", @"ai_connection", @"ai_persona", @"minisight.activity", @"minisight.activity.interval", @"minisight.ai.adjust", @"minisight.ai.adjustments", @"minisight.ai.nickname", @"minisight.ai.permissions", @"minisight.ai.persona", @"minisight.ai.supplier", @"minisight.asset.source", @"minisight.bottomGap", @"minisight.chat.height", @"minisight.chat.theme", @"minisight.chat.tintAlpha", @"minisight.chat.tintHex", @"minisight.darkMode", @"minisight.diagnostics", @"minisight.dialogue.dwell", @"minisight.dialogue.return", @"minisight.dialogue.scale", @"minisight.dialogue.textScale", @"minisight.dragResponse", @"minisight.frameLimit", @"minisight.gesture.double", @"minisight.gesture.long", @"minisight.gesture.single", @"minisight.gravity", @"minisight.gravity.shake", @"minisight.gravity.strength", @"minisight.interaction", @"minisight.longPress", @"minisight.mode", @"minisight.pet.costume", @"minisight.pet.tint", @"minisight.petSize", @"minisight.petSound", @"minisight.proactive", @"minisight.proactive.interval", @"minisight.quick.enabled", @"minisight.quick.lines", @"minisight.quick.order", @"minisight.quick.position", @"minisight.record", @"minisight.renderer", @"minisight.settings.revision", @"minisight.shown", @"minisight.style", @"minisight.voice.input", @"minisight.voice.reply", @"minisight.voice.snore", @"pet", @"shown"]],
        @"source": [NSSet setWithArray:@[@"app", @"app_double_tap", @"app_local", @"bubble_tap", @"floating_bubbles", @"keyboard_dictation", @"menu_toggle", @"pet_second_tap", @"photos", @"plugin", @"plugin_double_tap", @"proactive", @"settings", @"user_drag"]],
        @"reason": [NSSet setWithArray:@[@"allow", @"deny", @"sent", @"write_failed", @"oversized_command", @"plugin_no_reply", @"snapshot_verified", @"snapshot_write_failed", @"pet_unavailable", @"visible_ack", @"no_visible_ack", @"timeout", @"empty_transcript", @"recognizer_unavailable", @"cancelled", @"microphone_busy", @"voice_timeout", @"second_request", @"accelerometer_error", @"accelerometer_fallback", @"already_recording", @"already_sending", @"app_burst", @"app_listening", @"approval_visible", @"asset_verification", @"atlas_decoded", @"attachment_missing", @"capture_callback", @"capture_error", @"capture_requested", @"catalog_changed", @"chat_already_visible", @"clear_conversation", @"controller_state", @"current_generation", @"darwin_notification", @"destination", @"destroy", @"device_motion", @"device_motion_error", @"disabled", @"empty_input", @"encoding_incomplete", @"engine", @"file_publish", @"first_responder", @"first_sample", @"first_sample_timeout", @"first_video_frame", @"hard_deadline", @"hidden", @"host_configured", @"host_teardown", @"invalid_response", @"long_press", @"long_press_disabled", @"manual_disabled", @"missing_anchor", @"missing_host_scene", @"missing_or_invalid_atlas", @"model_request", @"no_app_reply", @"not_burst", @"not_recording", @"not_visible_or_sending", @"open_destination", @"permission", @"pet_hidden", @"pet_host_configured", @"pet_unavailable_capsule_fallback", @"plugin_burst", @"quarantined", @"request_app", @"revision_retry", @"revision_visible", @"runtime_snapshot", @"scene_background", @"scene_mismatch", @"sources_exhausted", @"stale_generation", @"stop_or_encoding", @"system", @"system_unavailable", @"teardown", @"timer", @"transport_rejected", @"transport_started", @"unknown", @"user", @"user_menu", @"verified_file", @"write_request", @"writer_failed", @"writer_init", @"wrong_renderer"]],
        @"renderer": [NSSet setWithArray:@[@"0", @"1", @"2"]], @"mode": [NSSet setWithArray:@[@"0", @"1", @"2"]],
        @"style": [NSSet setWithArray:@[@"0", @"1", @"2", @"3"]],
        @"field": [NSSet setWithArray:@[@"connection", @"endpoint"]],
        @"domain": [NSSet setWithArray:@[@"chat", @"runtime", @"settings", @"voice"]],
        @"issue": [NSSet setWithArray:@[@"0", @"1", @"2", @"3", @"4", @"5", @"6", @"7", @"8", @"9"]],
        @"finish": [NSSet setWithArray:@[@"content_filter", @"error", @"function_call", @"length", @"none", @"other", @"stop", @"tool_calls", @"unknown"]],
        @"version": [NSSet setWithArray:@[@"0.8.1"]]
    }; });
    return [allowed[key] containsObject:value];
}

static id MSDiagValue(NSString *key, id value) {
    if ([key isEqualToString:@"request"] && [value isKindOfClass:NSString.class]) return MSDiagRequest(value);
    if ([value isKindOfClass:NSNumber.class]) {
        double n = [value doubleValue];
        return isfinite(n) && fabs(n) <= 9007199254740991.0 ? value : nil;
    }
    if (!MSDiagIdentifier(value)) return nil;
    // revision may be a monotonic number or an app-generated UUID.
    if ([key isEqualToString:@"revision"]) return [[NSUUID alloc] initWithUUIDString:value] ? value : nil;
    return MSDiagEnum(key, value) ? value : nil;
    // Counters, flags and values not explicitly enumerated above are numeric.

}

static void MSDiagSetup(void) {
    static dispatch_once_t once;
    dispatch_once(&once, ^{
        MSDiagConfigLock = [NSLock new];
        MSDiagQueue = dispatch_queue_create("com.openminis.minisight.diagnostic", DISPATCH_QUEUE_SERIAL);
        atomic_init(&MSDiagEnabled, false);
        atomic_init(&MSDiagAvailable, false);
        atomic_init(&MSDiagConfigGeneration, 0);
        atomic_init(&MSDiagDetailGeneration, 0);
        MSDiagRunID = NSUUID.UUID.UUIDString;
        NSString *process = NSProcessInfo.processInfo.processName;
        MSDiagProcess = MSDiagIdentifier(process) ? [process copy] : @"unknown";
        MSDiagFile = [process isEqualToString:@"SpringBoard"] ? @"diagnostic-plugin.log" : @"diagnostic-app.log";
        MSDiagDate = [NSDateFormatter new];
        MSDiagDate.locale = [[NSLocale alloc] initWithLocaleIdentifier:@"en_US_POSIX"];
        MSDiagDate.timeZone = [NSTimeZone timeZoneForSecondsFromGMT:0];
        MSDiagDate.dateFormat = @"yyyy-MM-dd'T'HH:mm:ss.SSS'Z'";
        MSDiagFeatures = [NSSet setWithArray:@[@"chat", @"settings", @"runtime", @"voice", @"ai", @"ai_test", @"assets", @"recording", @"gravity", @"drag", @"activity", @"screen", @"ownership", @"gesture", @"bubble", @"approval"]];
        MSDiagStages = [NSSet setWithArray:@[@"save", @"receive", @"apply", @"show", @"layout", @"send", @"reply", @"display", @"close", @"skip", @"build", @"entry", @"editor", @"keyboard", @"composer", @"state", @"visibility", @"hide", @"begin", @"end", @"readback", @"publish", @"request", @"cancel", @"config", @"network", @"callback", @"parse", @"finish", @"ready", @"error", @"sample", @"stop", @"start", @"load", @"click", @"response", @"change", @"configure", @"deliver", @"interruption", @"rotate", @"reload", @"identity", @"route", @"answer", @"single", @"double", @"long", @"install", @"picker", @"remove", @"local", @"source"]];
        MSDiagResults = [NSSet setWithArray:@[@"ok", @"failed", @"skipped", @"cancelled", @"pending", @"unsupported", @"allow", @"deny", @"open", @"source"]];
        MSDiagKeys = [NSSet setWithArray:@[@"setting", @"source", @"reason", @"request", @"revision", @"generation", @"issue", @"count", @"chars", @"duration_ms", @"renderer", @"visible", @"sending", @"keyboard", @"below", @"x", @"y", @"w", @"h", @"enabled", @"mode", @"style", @"field", @"code", @"domain", @"saved", @"readback", @"sequence", @"value", @"present", @"roll", @"samples", @"http", @"bytes", @"reasoning", @"finish", @"valid", @"executing", @"active", @"version", @"action", @"route", @"old", @"new"]];
    });
}

void MSDiagConfigure(BOOL enabled, NSString *container) {
    MSDiagSetup();
    [MSDiagConfigLock lock];
    BOOL available = container.length > 0;
    BOOL active = enabled && available;
    if (![MSDiagContainer isEqualToString:container]) atomic_fetch_add(&MSDiagConfigGeneration, 1);
    if (atomic_load(&MSDiagEnabled) != active) atomic_fetch_add(&MSDiagDetailGeneration, 1);
    MSDiagContainer = [container copy];
    atomic_store(&MSDiagAvailable, available);
    atomic_store(&MSDiagEnabled, active);
    [MSDiagConfigLock unlock];
}

// The persistent sidecar lock survives rename, serializing rotation + append even
// for multiple same-role processes. Never lock the log inode that is rotated.
static void MSDiagAppend(NSData *data, NSString *container) {
    NSString *dir = [container stringByAppendingPathComponent:@"Documents/MiniSight"];
    NSFileManager *fm = NSFileManager.defaultManager;
    if (![fm createDirectoryAtPath:dir withIntermediateDirectories:YES attributes:nil error:nil]) return;
    NSString *path = [dir stringByAppendingPathComponent:MSDiagFile];
    NSString *old = [path stringByAppendingString:@".1"];
    // Legacy diagnostic.log / diagnostic.log.1 remain readable; never append to them.
    NSString *lockPath = [path stringByAppendingString:@".lock"];
    int lockFD = open(lockPath.fileSystemRepresentation, O_CREAT | O_RDWR | O_NOFOLLOW | O_CLOEXEC, 0600);
    if (lockFD < 0) return;
    fchmod(lockFD, 0600);
    if (flock(lockFD, LOCK_EX) != 0) { close(lockFD); return; }
    int fd = open(path.fileSystemRepresentation, O_CREAT | O_WRONLY | O_APPEND | O_NOFOLLOW | O_CLOEXEC, 0600);
    if (fd >= 0) {
        struct stat st;
        if (fstat(fd, &st) != 0 || !S_ISREG(st.st_mode)) { close(fd); fd = -1; }
        else {
            fchmod(fd, 0600);
            if ((unsigned long long)st.st_size + data.length > MSDiagMaxBytes) {
                close(fd); fd = -1;
                // POSIX rename replaces .1 atomically under the sidecar lock.
                if (rename(path.fileSystemRepresentation, old.fileSystemRepresentation) == 0)
                    fd = open(path.fileSystemRepresentation, O_CREAT | O_WRONLY | O_APPEND | O_NOFOLLOW | O_CLOEXEC, 0600);
            }
        }
    }
    if (fd >= 0) {
        fchmod(fd, 0600);
        const uint8_t *bytes = data.bytes;
        NSUInteger offset = 0;
        while (offset < data.length) {
            ssize_t n = write(fd, bytes + offset, data.length - offset);
            if (n < 0 && errno == EINTR) continue;
            if (n <= 0) break;
            offset += (NSUInteger)n;
        }
        close(fd);
    }
    flock(lockFD, LOCK_UN);
    close(lockFD);
}

static void MSDiagEnqueue(NSDictionary *event, BOOL detailed) {
    [MSDiagConfigLock lock];
    if (!atomic_load(&MSDiagAvailable) || (detailed && !atomic_load(&MSDiagEnabled)) || MSDiagPending >= 256) {
        [MSDiagConfigLock unlock]; return;
    }
    unsigned long epoch = atomic_load(&MSDiagConfigGeneration);
    unsigned long detailEpoch = atomic_load(&MSDiagDetailGeneration);
    NSString *container = [MSDiagContainer copy];
    unsigned long long seq = ++MSDiagSequence;
    NSDate *time = NSDate.date;
    ++MSDiagPending;
    // Submission under the lock preserves sequence order across producer threads.
    dispatch_async(MSDiagQueue, ^{
        @autoreleasepool {
            NSData *json = [NSJSONSerialization dataWithJSONObject:event options:0 error:nil];
            if (json.length && json.length <= 6144) {
                NSString *body = [[NSString alloc] initWithData:json encoding:NSUTF8StringEncoding];
                NSString *line = [NSString stringWithFormat:@"%@ pid=%d process=%@ runId=%@ seq=%llu event=%@\n",
                    [MSDiagDate stringFromDate:time], getpid(), MSDiagProcess, MSDiagRunID, seq, body];
                NSData *data = [line dataUsingEncoding:NSUTF8StringEncoding];
                // Container changes invalidate all queued events. Disabling
                // details invalidates only legacy records, never basic events.
                // No config lock across file I/O/flock: main-thread producers
                // only enqueue. One already-started append may finish during a
                // container/detail change; queued later records are invalidated.
                if (atomic_load(&MSDiagAvailable) && epoch == atomic_load(&MSDiagConfigGeneration) &&
                    (!detailed || (atomic_load(&MSDiagEnabled) && detailEpoch == atomic_load(&MSDiagDetailGeneration))))
                    MSDiagAppend(data, container);
            }
            [MSDiagConfigLock lock];
            --MSDiagPending;
            [MSDiagConfigLock unlock];
        }
    });
    [MSDiagConfigLock unlock];
}

void MSDiagEvent(NSString *feature, NSString *stage, NSString *result, NSDictionary<NSString *, id> *fields) {
    MSDiagSetup();
    if (!atomic_load(&MSDiagAvailable) || ![MSDiagFeatures containsObject:feature] ||
        ![MSDiagStages containsObject:stage] || ![MSDiagResults containsObject:result]) return;
    NSMutableDictionary *safe = [NSMutableDictionary dictionary];
    if ([fields isKindOfClass:NSDictionary.class]) {
        // Iterate the whitelist (bounded), never enumerate or describe unknown data.
        for (NSString *key in MSDiagKeys) {
            id value = MSDiagValue(key, fields[key]);
            if (value) safe[key] = [value copy];
        }
    }
    MSDiagEnqueue(@{@"v": @1, @"feature": [feature copy], @"stage": [stage copy],
                    @"result": [result copy], @"fields": safe}, NO);
}

void MSDiagMessage(NSString *message) {
    if (message.length) MSDiag(@"%@", message);
}

void MSDiag(NSString *format, ...) {
    MSDiagSetup();
    if (!atomic_load(&MSDiagEnabled) || !format.length) return;
    va_list args;
    va_start(args, format);
    NSString *body = [[NSString alloc] initWithFormat:format arguments:args];
    va_end(args);
    if (body.length > 2048) body = [body substringToIndex:2048];
    // ABI compatibility, without persisting free-form legacy messages. Extract
    // only known stages and typed counters/identifiers; no description/error text.
    static NSRegularExpression *head, *pairs;
    static NSSet *stages;
    static NSDictionary *aliases;
    static dispatch_once_t once;
    dispatch_once(&once, ^{
        head = [NSRegularExpression regularExpressionWithPattern:@"^(?:client=[A-Fa-f0-9-]{36} )?(chat|settings|runtime|voice|ai|recorder|gravity|activity|screen|front|plugin)\\b(?: ([A-Za-z_-]+))?" options:0 error:nil];
        pairs = [NSRegularExpression regularExpressionWithPattern:@"(?:^| )([A-Za-z_]+)=([A-Za-z0-9_./-]+)(?= |$)" options:0 error:nil];
        stages = [NSSet setWithArray:@[@"save", @"receive", @"apply", @"show", @"layout", @"send", @"send-entry", @"reply", @"display", @"close", @"skip", @"cancel", @"handle", @"begin", @"deadline", @"config", @"network", @"callback", @"parse", @"finish", @"state", @"result", @"container", @"request", @"opening"]];
        aliases = @{@"ui_generation": @"generation", @"rows": @"count", @"text_len": @"chars", @"contentlen": @"chars", @"errorCode": @"code", @"status": @"code", @"http": @"code"};
    });
    NSTextCheckingResult *match = [head firstMatchInString:body options:0 range:NSMakeRange(0, body.length)];
    if (!match) return;
    NSString *feature = [body substringWithRange:[match rangeAtIndex:1]];
    NSString *stage = @"status";
    if ([match rangeAtIndex:2].location != NSNotFound) {
        NSString *candidate = [body substringWithRange:[match rangeAtIndex:2]];
        if ([stages containsObject:candidate]) stage = candidate;
    }
    NSMutableDictionary *fields = [NSMutableDictionary dictionary];
    NSString *result = @"pending";
    for (NSTextCheckingResult *pair in [pairs matchesInString:body options:0 range:NSMakeRange(0, body.length)]) {
        NSString *key = [body substringWithRange:[pair rangeAtIndex:1]];
        NSString *raw = [body substringWithRange:[pair rangeAtIndex:2]];
        if (([key isEqualToString:@"success"] && [raw isEqualToString:@"0"]) ||
            ([key isEqualToString:@"kind"] && [raw isEqualToString:@"error"])) result = @"failed";
        else if ([key isEqualToString:@"kind"] && [raw isEqualToString:@"cancelled"]) result = @"cancelled";
        else if (([key isEqualToString:@"success"] && [raw isEqualToString:@"1"]) ||
                 ([stage isEqualToString:@"display"] && [key isEqualToString:@"kind"] && [raw isEqualToString:@"answer"])) result = @"ok";
        key = aliases[key] ?: key;
        if (![MSDiagKeys containsObject:key]) continue;
        NSScanner *scanner = [NSScanner scannerWithString:raw];
        double number;
        id value = [scanner scanDouble:&number] && scanner.isAtEnd ? @(number) : raw;
        value = MSDiagValue(key, value);
        if (value) fields[key] = value;
    }
    if ([stage isEqualToString:@"cancel"]) result = @"cancelled";
    if ([feature isEqualToString:@"ai"] && [stage isEqualToString:@"finish"] &&
        [fields[@"issue"] isKindOfClass:NSNumber.class])
        result = [fields[@"issue"] integerValue] == 0 ? @"ok" : @"failed";
    MSDiagEnqueue(@{@"v": @1, @"legacy": @YES, @"feature": feature,
                    @"stage": stage, @"result": result, @"fields": fields}, YES);
}


void MSDiagSettingsSnapshot(NSString *stage, NSString *source, NSDictionary<NSString *, id> *preferences) {
    if (![preferences isKindOfClass:NSDictionary.class]) return;
    id revision = preferences[@"minisight.settings.revision"];
    for (NSString *key in @[@"minisight.renderer", @"minisight.style", @"minisight.mode",
        @"minisight.petSize", @"minisight.gravity", @"minisight.record", @"minisight.longPress",
        @"minisight.diagnostics", @"minisight.chat.height", @"minisight.chat.theme",
        @"minisight.chat.tintHex", @"minisight.chat.tintAlpha"]) {
        id raw = preferences[key];
        NSMutableDictionary *fields = [@{@"setting": key, @"source": source ?: @"unknown",
            @"present": @(raw != nil)} mutableCopy];
        if (revision) fields[@"revision"] = revision;
        if ([raw isKindOfClass:NSNumber.class]) fields[@"value"] = raw;
        else if ([key isEqualToString:@"minisight.chat.tintHex"] &&
                 [raw isKindOfClass:NSString.class] && [raw length] == 6) {
            NSCharacterSet *invalid = [[NSCharacterSet characterSetWithCharactersInString:@"0123456789abcdefABCDEF"] invertedSet];
            if ([raw rangeOfCharacterFromSet:invalid].location == NSNotFound) {
                unsigned int rgb = 0;
                if ([[NSScanner scannerWithString:raw] scanHexInt:&rgb]) fields[@"value"] = @(rgb);
            }
        }
        MSDiagEvent(@"settings", stage, @"pending", fields);
    }
}

#import "MiniSightRuntimeConfig.h"
#import "MiniSightResources.h"

@implementation MiniSightRuntimeConfig
+ (instancetype)shared {
    static MiniSightRuntimeConfig *shared;
    static dispatch_once_t once;
    dispatch_once(&once, ^{ shared = [MiniSightRuntimeConfig new]; });
    return shared;
}

- (void)reloadWithContainer:(NSString *)container {
    NSString *path = [container stringByAppendingPathComponent:@"Library/Preferences/com.openminis.app.plist"];
    NSDictionary *preferences = path ? [NSDictionary dictionaryWithContentsOfFile:path] : nil;
    [self reloadWithContainer:container preferences:
        [MiniSightResources mergedPreferencesWithContainer:container preferences:preferences]];
}

- (void)reloadWithContainer:(NSString *)container preferences:(NSDictionary<NSString *,id> *)preferences {
    // Pass Resources' immutable merged preferences here for the same generation
    // used by visibility/rendering. Never wait for runtime.json to exist first.
    NSDictionary *merged = preferences ?: [MiniSightResources mergedPreferencesWithContainer:container preferences:nil];
    NSMutableDictionary *json = [NSMutableDictionary dictionary];
    NSDictionary *fields = MiniSightResources.runtimeFields;
    for (NSString *key in fields) {
        id value = merged[key];
        if (value && ![value isKindOfClass:NSNull.class]) json[fields[key]] = value;
    }
    _valid = json.count > 0;
    _activity = [json[@"activity"] isKindOfClass:NSString.class]
        ? [@[@"lively", @"quiet", @"off"] indexOfObject:json[@"activity"]] : 0;
    if (_activity == NSNotFound) _activity = 0;
    _activityInterval = [json[@"activityInterval"] doubleValue] > 0 ? [json[@"activityInterval"] doubleValue] : 7;
    _frameLimit = [json[@"frameLimit"] integerValue];
    _dragResponse = json[@"dragResponse"] ? [json[@"dragResponse"] boolValue] : YES;
    _interaction = json[@"interaction"] ? [json[@"interaction"] boolValue] : YES;
    _sound = [json[@"sound"] boolValue];
    _bottomGap = [json[@"bottomGap"] doubleValue];
    _tint = [json[@"tint"] isKindOfClass:NSString.class] ? json[@"tint"] : @"natural";
    _costume = [json[@"costume"] isKindOfClass:NSString.class] ? json[@"costume"] : @"";
    _quick = json[@"quick"] ? [json[@"quick"] boolValue] : YES;
    _bubbleScale = [json[@"bubbleScale"] doubleValue] > 0 ? [json[@"bubbleScale"] doubleValue] : 1;
    _textScale = [json[@"textScale"] doubleValue] > 0 ? [json[@"textScale"] doubleValue] : 1;
    _dwell = [json[@"dwell"] doubleValue] > 0 ? [json[@"dwell"] doubleValue] : 1;
    NSString *mode = [json[@"darkMode"] isKindOfClass:NSString.class] ? json[@"darkMode"] : @"system";
    _darkMode = [@[@"system", @"light", @"dark"] indexOfObject:mode];
    if (_darkMode == NSNotFound) _darkMode = 0;
    _proactive = [json[@"proactive"] boolValue];
    _proactiveInterval = [json[@"proactiveInterval"] doubleValue] > 0 ? [json[@"proactiveInterval"] doubleValue] : 30;
    _returnKey = [json[@"returnKey"] isKindOfClass:NSString.class] ? json[@"returnKey"] : @"send";
    _voiceReply = [json[@"voiceReply"] boolValue];
    _snore = [json[@"snore"] isKindOfClass:NSString.class] ? json[@"snore"] : @"off";
    _quickPosition = [json[@"quickPosition"] isKindOfClass:NSString.class] ? json[@"quickPosition"] : @"above";
    id order = json[@"quickOrder"];
    _quickOrder = [order isKindOfClass:NSArray.class] ? order :
        ([order isKindOfClass:NSString.class] && [order length] ? [order componentsSeparatedByString:@","] : @[@"greet", @"wave", @"jump", @"pat", @"walk"]);
    _quickLines = [json[@"quickLines"] isKindOfClass:NSDictionary.class] ? json[@"quickLines"] : @{};
    _revision = [json[@"revision"] isKindOfClass:NSString.class] ? json[@"revision"] : @"";
    _gravityShake = json[@"gravityShake"] ? [json[@"gravityShake"] boolValue] : YES;
    _gravityStrength = [json[@"gravityStrength"] doubleValue] > 0 ? [json[@"gravityStrength"] doubleValue] : 1;
    _downloadSource = [json[@"downloadSource"] isKindOfClass:NSString.class] ? json[@"downloadSource"] : @"";
    _supplier = [json[@"supplier"] isKindOfClass:NSString.class] ? json[@"supplier"] : @"";
    _persona = [json[@"persona"] isKindOfClass:NSString.class] ? json[@"persona"] : @"";
    _nickname = [json[@"nickname"] isKindOfClass:NSString.class] ? json[@"nickname"] : @"";
    _aiAdjust = [json[@"aiAdjust"] boolValue];
    _aiPermissions = [json[@"aiPermissions"] isKindOfClass:NSString.class] ? json[@"aiPermissions"] : @"all";
    _adjustments = [json[@"adjustments"] isKindOfClass:NSArray.class] ? json[@"adjustments"] : @[];
    _proactive = [json[@"proactive"] boolValue];
    _singleTap = [json[@"singleTap"] isKindOfClass:NSString.class] ? json[@"singleTap"] : @"interact";
    _doubleTap = [json[@"doubleTap"] isKindOfClass:NSString.class] ? json[@"doubleTap"] : @"voice";
    _longPress = [json[@"longPress"] isKindOfClass:NSString.class] ? json[@"longPress"] : @"menu";
}

- (instancetype)init {
    if ((self = [super init])) {
        _activityInterval = 7; _dragResponse = YES; _interaction = YES;
        _tint = @"natural"; _costume = @""; _quick = YES;
        _bubbleScale = 1; _textScale = 1; _dwell = 1;
        _gravityStrength = 1; _gravityShake = YES;
        _supplier = @"deepseek"; _persona = @""; _nickname = @""; _revision = @"";
        _singleTap = @"interact"; _doubleTap = @"voice"; _longPress = @"menu";
        _returnKey = @"send"; _snore = @"off"; _quickPosition = @"above";
        _aiPermissions = @""; _adjustments = @[]; _quickOrder = @[]; _quickLines = @{};
    }
    return self;
}
@end

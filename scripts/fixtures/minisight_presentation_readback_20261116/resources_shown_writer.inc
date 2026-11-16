// Literal production write/readback/notify methods.
+ (void)writeShown:(BOOL)shown container:(NSString *)container {
    [self writeShown:shown container:container completion:nil];
}

+ (void)writeShown:(BOOL)shown container:(NSString *)container completion:(void (^)(BOOL))completion {
    [self writeShown:shown container:container verifiedReadback:^(BOOL verified, NSString *previousIdentity) {
        (void)previousIdentity; if (completion) completion(verified);
    }];
}

+ (void)writeShown:(BOOL)shown container:(NSString *)container verifiedReadback:(void (^)(BOOL, NSString *))completion {
    NSString *target = [container copy];
    dispatch_async(MSResourceQueue(), ^{
        NSString *previousIdentity = MSMusicShownEvidence(target, nil)[@"_minisightShownIdentity"] ?: @"";
        BOOL verified = MSMusicWriteShownVerified(shown, target);
        // save -> exact readback -> notification; failure is reported, never announced as ON.
        if (verified) MSBridgePost(@"com.openminis.minisight.settings");
        dispatch_async(dispatch_get_main_queue(), ^{ if (completion) completion(verified, previousIdentity); });
    });
}

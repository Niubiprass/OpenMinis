// Appended to verbatim Tweak helpers; Foundation only, synthetic snapshots.
int main(void) { @autoreleasepool {
    double now=NSDate.date.timeIntervalSince1970;
    NSMutableDictionary *s=[@{@"progressAvailable":@YES,@"motionRate":@1,@"motionTime":@20.25,@"time":@(now-.5),@"rhythmGeneration":@7,@"generation":@99} mutableCopy];
    double measured=MiniSightSnapshotMeasuredPosition(s);
    assert(measured>=20.75 && measured<21.25);
    assert(MiniSightSnapshotMusicToken(s)==7);
    for (id bad in @[@NO,@1,@0,@"true",NSNull.null]) {
        s[@"progressAvailable"]=bad; assert(isnan(MiniSightSnapshotMeasuredPosition(s)));
    }
    [s removeObjectForKey:@"progressAvailable"]; assert(isnan(MiniSightSnapshotMeasuredPosition(s)));
    s[@"progressAvailable"]=@YES;
    for (NSString *key in @[@"motionRate",@"motionTime",@"time"]) {
        id saved=s[key];
        for (id bad in @[@YES,@"1",@(NAN),@(INFINITY),NSNull.null]) {
            s[key]=bad; assert(isnan(MiniSightSnapshotMeasuredPosition(s)));
        }
        [s removeObjectForKey:key]; assert(isnan(MiniSightSnapshotMeasuredPosition(s))); s[key]=saved;
    }
    s[@"time"]=@(now-5.1); assert(isnan(MiniSightSnapshotMeasuredPosition(s)));
    s[@"time"]=@(now+2); assert(isnan(MiniSightSnapshotMeasuredPosition(s)));
    s[@"time"]=@(now); s[@"motionRate"]=@2;
    assert(isnan(MiniSightSnapshotMeasuredPosition(s)) && MiniSightSnapshotMusicToken(s)==7);
    // rate two suppresses seek evidence, NOT the independent music token/enabled input.
    s[@"motionRate"]=@1;
    for (NSNumber *bad in @[@(-1),@3601]) { s[@"motionTime"]=bad; assert(isnan(MiniSightSnapshotMeasuredPosition(s))); }
    s[@"motionTime"]=@3599.9; s[@"time"]=@(now-1); assert(isnan(MiniSightSnapshotMeasuredPosition(s)));
    for (id bad in @[@YES,@0,@(-1),@1.5,@(NAN),@(INFINITY),@9007199254740992.0,@"7",NSNull.null]) {
        s[@"rhythmGeneration"]=bad; assert(MiniSightSnapshotMusicToken(s)==0);
    }
    [s removeObjectForKey:@"rhythmGeneration"]; assert(MiniSightSnapshotMusicToken(s)==99);
    s[@"generation"]=@YES; assert(MiniSightSnapshotMusicToken(s)==0);
    [s removeObjectForKey:@"generation"]; assert(MiniSightSnapshotMusicToken(s)==0);
    puts("NATIVE PASS: verbatim Tweak measured-position and token helpers");
    return 0;
} }

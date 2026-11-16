#import "MiniSightNameWakeState.h"
- (void)publishContainer:(NSString *)container revision:(NSString *)revision unlocked:(BOOL)unlocked allowed:(BOOL)allowed busy:(BOOL)busy {
    NSAssert(NSThread.isMainThread, @"Name wake host state is main-thread owned");
    container = [container copy]; revision = [revision copy] ?: @"";
    NSDictionary *entry = MSNameWakeStateMessage(self.host, revision, unlocked, allowed, busy,
        NSProcessInfo.processInfo.systemUptime);
    __block NSUInteger ticket; @synchronized (self) { ticket = ++_stateTicket; }
    dispatch_async(_queue, ^{
        @synchronized (self) { if (ticket != self->_stateTicket) return; }
        if (!MSNWClockFresh(NSProcessInfo.processInfo.systemUptime, [entry[@"clock"] doubleValue], 4)) return;
        BOOL verified = MSNWWriteVerified(container, @"namewake-state.json", entry);
        @synchronized (self) { if (ticket != self->_stateTicket) return; }
        if (verified) MSBridgePost(MSNWStateNote);
    });
}

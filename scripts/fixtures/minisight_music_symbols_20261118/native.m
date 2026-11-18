// Real dlsym/dladdr + loaded CoreFoundation Mach-O, never MediaRemote/device/network.
// Normal macOS arm64/x86_64 runs do NOT prove iOS arm64e/PAC or private MR ABI.
#import <Foundation/Foundation.h>
#import <CoreFoundation/CoreFoundation.h>
#define MINISIGHT_BRIDGE_IO_H
static BOOL MSBridgeWrite(NSString *container, NSString *name, NSDictionary *value) { return YES; }
static NSDictionary *MSBridgeRead(NSString *container, NSString *name, NSUInteger limit) { return nil; }
static void MSBridgePost(NSString *name) {}
#define MINISIGHT_MUSIC_MONITOR_TEST 1
#import "MiniSightMusicMonitor.m"

static void Check(BOOL ok, const char *message) { if (!ok) { fprintf(stderr, "FAIL: %s\n", message); exit(1); } }
static BOOL CachedImageHasNonzeroTextOffset(void *symbol) {
    const void *address = symbol;
#if __has_feature(ptrauth_calls)
    address = ptrauth_strip(address, ptrauth_key_function_pointer);
#endif
    Dl_info info;
    if (!dladdr(address, &info)) return NO;
    const struct mach_header_64 *header = info.dli_fbase;
    if (!header || header->magic != MH_MAGIC_64 || !(header->flags & MH_DYLIB_IN_CACHE)) return NO;
    const uint8_t *p = (const uint8_t *)(header + 1), *end = p + header->sizeofcmds;
    while (p + sizeof(struct load_command) <= end) {
        const struct load_command *lc = (const void *)p;
        if (lc->cmdsize < sizeof(*lc) || lc->cmdsize > (size_t)(end - p)) return NO;
        if (lc->cmd == LC_SEGMENT_64 && lc->cmdsize >= sizeof(struct segment_command_64)) {
            const struct segment_command_64 *seg = (const void *)p;
            if (strncmp(seg->segname, SEG_TEXT, sizeof(seg->segname)) == 0) return seg->fileoff != 0;
        }
        p += lc->cmdsize;
    }
    return NO;
}
int main(void) { @autoreleasepool {
    void *handle = dlopen("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation", RTLD_LAZY | RTLD_LOCAL);
    Check(handle != NULL, "CoreFoundation handle");
    void *rawCode = dlsym(handle, "CFStringGetTypeID");
    Check(rawCode != NULL, "public code export");
    if (!CachedImageHasNonzeroTextOffset(rawCode)) {
        fputs("NATIVE SKIP: host lacks the required real shared-cache nonzero-fileoff image\n", stderr);
        return 77;
    }
    void *code = MSMusicSymbol(handle, "CFStringGetTypeID", YES);
    Check(code != NULL && code == rawCode, "cached code resolved");
    // Invoke the original dlsym result returned by production, never a stripped pointer.
    Check(((CFTypeID (*)(void))code)() == CFStringGetTypeID(), "resolved function callable");
    void *data = MSMusicSymbol(handle, "kCFRunLoopDefaultMode", NO);
    Check(data != NULL && data == dlsym(handle, "kCFRunLoopDefaultMode"), "cached data slot resolved");
    CFStringRef value = *(CFStringRef *)data;
    Check(value != NULL && CFGetTypeID(value) == CFStringGetTypeID(), "documented public CFString object ABI");
    Check(CFEqual(value, kCFRunLoopDefaultMode), "resolved data value");
    Check(MSMusicSymbol(handle, "CFStringGetTypeID", NO) == NULL, "code denied as data");
    Check(MSMusicSymbol(handle, "kCFRunLoopDefaultMode", YES) == NULL, "data denied as code");
    Check(MSMusicSymbol(handle, "MiniSightNonexistentFixtureSymbol", YES) == NULL, "missing symbol denied");
    MiniSightMusicMonitor *monitor = [MiniSightMusicMonitor new];
    NSTimeInterval before = NSDate.date.timeIntervalSince1970;
    [monitor publishLine:nil playing:NO force:YES];
    NSTimeInterval stamp = [monitor.snapshot[@"time"] doubleValue];
    Check(stamp >= before && stamp <= NSDate.date.timeIntervalSince1970, "bridge writer uses wall epoch not uptime");
    dispatch_sync([monitor valueForKey:@"bridgeQueue"], ^{});
#if __has_feature(ptrauth_calls)
    puts("PAC compiler path: enabled on THIS host; not proof of target MediaRemote ABI");
#else
    puts("PAC runtime: NOT COVERED (host is not a ptrauth_calls build)");
#endif
    puts("NATIVE PASS: real shared-cache image, callable code, public CFString data, wrong-kind denial, epoch writer");
    dlclose(handle);
    return 0;
} }

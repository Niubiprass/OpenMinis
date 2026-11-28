#ifndef MINISIGHT_COMPANION_ACTIONS_H
#define MINISIGHT_COMPANION_ACTIONS_H
#import <Foundation/Foundation.h>
#import <CoreFoundation/CoreFoundation.h>
#import <dispatch/dispatch.h>
#import <CommonCrypto/CommonDigest.h>
#import <dlfcn.h>
#import <fcntl.h>
#import <sys/stat.h>
#import <unistd.h>
#import <errno.h>
#include <stdbool.h>

// Read-only private artwork supplement. It never selects a different pet,
// writes metadata/preferences, copies files, downloads or publishes artwork.
static inline bool MSCompanionEligible(bool sameImage, bool schemaOK, bool single,
    int layout, int variant, bool explicitPack, bool usingDefault) {
    return sameImage && schemaOK && single && layout == 3 && variant == 0 && !explicitPack && !usingDefault;
}
static NSString *MSCompanionRoot(void) {
    static NSString *cached;
    static NSObject *lock; static dispatch_once_t once;
    dispatch_once(&once, ^{ lock = [NSObject new]; });
    @synchronized (lock) {
        NSFileManager *fm = NSFileManager.defaultManager;
        if (cached.length && [fm fileExistsAtPath:cached]) return cached;
        // Own loaded image wins; App has no injected image and uses the same
        // existing-root ranking as the preference resolver, once then cached.
        Dl_info image;
        if (dladdr((const void *)&MSCompanionRoot, &image) && image.dli_fname) {
            NSString *path = [NSString stringWithUTF8String:image.dli_fname];
            NSRange r = [path rangeOfString:@"/Library/MobileSubstrate/DynamicLibraries/MiniSight.dylib" options:NSBackwardsSearch];
            if (r.location != NSNotFound && r.location+r.length == path.length) {
                NSString *root = [path substringToIndex:r.location];
                if (([root containsString:@"/.jbroot-"] || [root isEqual:@"/var/jb"] || [root isEqual:@"/private/var/jb"]) &&
                    [fm fileExistsAtPath:root]) { cached=root; return cached; }
            }
        }
        NSString *base=@"/var/mobile/Containers/Shared/AppGroup";
        NSInteger best=0; NSDate *date=NSDate.distantPast;
        for (NSString *name in [fm contentsOfDirectoryAtPath:base error:nil]) {
            if (![name hasPrefix:@".jbroot-"]) continue;
            NSString *root=[base stringByAppendingPathComponent:name];
            NSInteger score=[fm fileExistsAtPath:[root stringByAppendingPathComponent:@"Library/MobileSubstrate/DynamicLibraries/MiniSight.dylib"]] ? 3 :
                [fm fileExistsAtPath:[root stringByAppendingPathComponent:@"Library/MobileSubstrate"]] ? 2 :
                [fm fileExistsAtPath:[root stringByAppendingPathComponent:@"usr/lib"]] ? 1 : 0;
            NSDate *modified=[fm attributesOfItemAtPath:root error:nil][NSFileModificationDate] ?: NSDate.distantPast;
            if (score>best || (score>0 && score==best && [modified compare:date]==NSOrderedDescending)) {
                cached=root;best=score;date=modified;
            }
        }
        if (!cached.length && [fm fileExistsAtPath:@"/var/jb/usr/lib"]) cached=@"/var/jb";
        return cached;
    }
}
// Same descriptor-relative no-symlink policy as the existing ActionLibrary.
static int MSCompanionDirectory(NSString *path) {
    if (![path hasPrefix:@"/"]) return -1;
    if ([path hasPrefix:@"/var/"] || [path isEqual:@"/var"]) path=[@"/private" stringByAppendingString:path];
    int fd=open("/",O_RDONLY|O_DIRECTORY|O_CLOEXEC|O_NOFOLLOW);
    if (fd<0) return -1;
    for (NSString *part in [[path substringFromIndex:1] componentsSeparatedByString:@"/"]) {
        if (!part.length || [part isEqual:@"."] || [part isEqual:@".."]) { close(fd);return -1; }
        int next=openat(fd,part.fileSystemRepresentation,O_RDONLY|O_DIRECTORY|O_CLOEXEC|O_NOFOLLOW|O_NONBLOCK);
        close(fd);if(next<0)return -1;fd=next;
    }
    return fd;
}
static NSData *MSCompanionRead(int dir,const char *name,size_t maximum) {
    int fd=openat(dir,name,O_RDONLY|O_CLOEXEC|O_NOFOLLOW|O_NONBLOCK);if(fd<0)return nil;
    struct stat st;
    if(fstat(fd,&st)||!S_ISREG(st.st_mode)||st.st_size<=0||(uint64_t)st.st_size>maximum){close(fd);return nil;}
    NSMutableData *data=[NSMutableData dataWithLength:(NSUInteger)st.st_size];size_t n=0;
    while(n<data.length){ssize_t got=read(fd,(char *)data.mutableBytes+n,data.length-n);if(got<0&&errno==EINTR)continue;if(got<=0)break;n+=(size_t)got;}
    struct stat end;BOOL stable=!fstat(fd,&end)&&end.st_dev==st.st_dev&&end.st_ino==st.st_ino&&end.st_size==st.st_size&&
        end.st_mtimespec.tv_sec==st.st_mtimespec.tv_sec&&end.st_mtimespec.tv_nsec==st.st_mtimespec.tv_nsec&&
        end.st_ctimespec.tv_sec==st.st_ctimespec.tv_sec&&end.st_ctimespec.tv_nsec==st.st_ctimespec.tv_nsec;
    close(fd);return stable&&n==data.length ? data : nil;
}
static NSString *MSCompanionSHA(NSData *data) {
    unsigned char sum[CC_SHA256_DIGEST_LENGTH];CC_SHA256(data.bytes,(CC_LONG)data.length,sum);
    NSMutableString *s=[NSMutableString stringWithCapacity:64];for(unsigned i=0;i<sizeof(sum);++i)[s appendFormat:@"%02x",sum[i]];return s;
}
// Identity contains inode/size/mtime/ctime: atomic replacement or an in-place
// rewrite invalidates the cache. Never cache an absent/invalid file as success.
static NSString *MSCompanionFileIdentity(int dir,const char *name) {
    struct stat st;
    if(fstatat(dir,name,&st,AT_SYMLINK_NOFOLLOW)||!S_ISREG(st.st_mode)||st.st_size<=0)return nil;
    return [NSString stringWithFormat:@"%llu:%llu:%lld:%lld:%ld:%lld:%ld",
        (unsigned long long)st.st_dev,(unsigned long long)st.st_ino,(long long)st.st_size,
        (long long)st.st_mtimespec.tv_sec,st.st_mtimespec.tv_nsec,
        (long long)st.st_ctimespec.tv_sec,st.st_ctimespec.tv_nsec];
}
static NSString *MSCompanionManifest(NSString *container,NSDictionary *metadata,BOOL usingDefault) {
    NSString *character=@"480321efe41a1878b50edf6c4d7dde77a4fc1dbd5508926677ab74ef80921723";
    if (![metadata isKindOfClass:NSDictionary.class] || !container.length) return nil;
    for (NSString *field in @[@"schema", @"layoutVersion", @"selectedVariant"]) {
        id number=metadata[field];
        if (number && (![number isKindOfClass:NSNumber.class] || CFGetTypeID((__bridge CFTypeRef)number)==CFBooleanGetTypeID())) return nil;
    }
    if (![metadata[@"layoutVersion"] isEqual:@3] ||
        (metadata[@"selectedVariant"] && ![metadata[@"selectedVariant"] isEqual:@0])) return nil;
    if (!MSCompanionEligible([metadata[@"sha256"] isEqual:character], [metadata[@"schema"] isEqual:@1],
        [metadata[@"sourceKind"] isEqual:@"singleImage"], [metadata[@"layoutVersion"] intValue],
        [metadata[@"selectedVariant"] intValue], metadata[@"actionPack"] != nil, usingDefault)) return nil;
    NSString *root=MSCompanionRoot();if(!root.length)return nil;
    NSString *path=[root stringByAppendingPathComponent:@"Library/Application Support/MiniSight/CompanionActions/current-blue-maid-supplement-v1"];
    int dir=MSCompanionDirectory(path);if(dir<0)return nil;
    int current=MSCompanionDirectory([container stringByAppendingPathComponent:@"Documents/MiniSight"]);
    if(current<0){close(dir);return nil;}
    NSString *imageID=MSCompanionFileIdentity(current,"pet.png");
    NSString *bindingID=MSCompanionFileIdentity(dir,"binding.json");
    NSString *manifestID=MSCompanionFileIdentity(dir,"actions.json");
    if(!imageID||!bindingID||!manifestID){close(current);close(dir);return nil;}
    NSString *identity=[@[path,container,imageID,bindingID,manifestID] componentsJoinedByString:@"|"];
    static NSString *cachedIdentity,*cachedManifest;
    static NSObject *cacheLock;static dispatch_once_t cacheOnce;
    dispatch_once(&cacheOnce,^{cacheLock=[NSObject new];});
    @synchronized(cacheLock){
        if([cachedIdentity isEqual:identity]){close(current);close(dir);return cachedManifest;}
    }
    NSData *binding=MSCompanionRead(dir,"binding.json",8192);
    NSData *manifest=MSCompanionRead(dir,"actions.json",1024*1024);close(dir);
    NSData *png=MSCompanionRead(current,"pet.png",16*1024*1024);close(current);
    NSDictionary *b=binding?[NSJSONSerialization JSONObjectWithData:binding options:0 error:nil]:nil;
    NSDictionary *m=manifest?[NSJSONSerialization JSONObjectWithData:manifest options:0 error:nil]:nil;
    if (![b isKindOfClass:NSDictionary.class]||![m isKindOfClass:NSDictionary.class]||
        ![b[@"schema"] isEqual:@1]||![b[@"character_sha256"] isEqual:character]||
        ![b[@"pack_manifest_sha256"] isEqual:MSCompanionSHA(manifest)]||
        ![b[@"pack_id"] isKindOfClass:NSString.class]||![m[@"id"] isKindOfClass:NSString.class]||
        ![b[@"pack_id"] isEqual:m[@"id"]]||![[NSUUID alloc] initWithUUIDString:b[@"pack_id"]]) return nil;
    // Verify the actual current image, not just a possibly stale JSON SHA.
    if(!png||![MSCompanionSHA(png) isEqual:character])return nil;
    // Full clip/frame schema + safe frame decoding remain owned by ActionLibrary.
    NSString *result=[path stringByAppendingPathComponent:@"actions.json"];
    @synchronized(cacheLock){cachedIdentity=identity;cachedManifest=result;}
    return result;
}
#endif

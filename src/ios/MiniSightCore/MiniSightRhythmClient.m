#import "MiniSightRhythmClient.h"
#import "MiniSightRhythmReceivePolicy.h"
#import "MiniSightPet.h"
#import "MiniSightLog.h"
#import <objc/runtime.h>
#import <QuartzCore/QuartzCore.h>
#include <arpa/inet.h>
#include <fcntl.h>
#include <sys/socket.h>
#include <unistd.h>
#include <errno.h>
#ifndef MINISIGHT_ENABLE_RHYTHM_TRANSPORT
#define MINISIGHT_ENABLE_RHYTHM_TRANSPORT 0
#endif
#if MINISIGHT_ENABLE_RHYTHM_TRANSPORT != 0 && MINISIGHT_ENABLE_RHYTHM_TRANSPORT != 1
#error MINISIGHT_ENABLE_RHYTHM_TRANSPORT_must_be_0_or_1
#endif
#if MINISIGHT_ENABLE_RHYTHM_TRANSPORT && (!MINISIGHT_ENABLE_RHYTHM_CAPTURE || !MINISIGHT_RHYTHM_LIVE_BUILD)
#error LIVE_transport_requires_paired_capture_and_explicit_LIVE_build
#endif
BOOL MiniSightRhythmLiveTransportCompiled(void) { return MINISIGHT_ENABLE_RHYTHM_TRANSPORT != 0; }
@interface MiniSightRhythmClient () {
    int _socket;
    uint64_t _session,_requestSequence,_server;
    double _renewAt;
    MSRhythmReceiveState _received;
    NSTimer *_timer;
    BOOL _cleared;
}
- (void)drain;
@property(nonatomic,copy) BOOL (^eligibilityHandler)(void);
@end
@implementation MiniSightRhythmClient
- (instancetype)init { if((self=[super init]))_socket=-1;return self; }
- (void)clearOnce { if(!_cleared){_cleared=YES;if(_clearHandler)_clearHandler();} }
- (void)sendLease:(BOOL)subscribe {
    if(_socket<0)return;
    uint8_t packet[40];size_t length=MSRhythmRequest(packet,sizeof(packet),subscribe,_session,_server,++_requestSequence);
    struct sockaddr_in a={0};a.sin_len=sizeof(a);a.sin_family=AF_INET;a.sin_port=htons(MS_RHYTHM_PORT);a.sin_addr.s_addr=htonl(INADDR_LOOPBACK);
    if(length)(void)sendto(_socket,packet,length,0,(const struct sockaddr*)&a,sizeof(a));
}
- (void)configureEnabled:(BOOL)enabled {
    NSAssert(NSThread.isMainThread,@"rhythm receiver must be main-thread");
    // No sockets, subscription, or audio service demand in the default candidate.
    if(!enabled||!MiniSightRhythmLiveTransportCompiled()){[self stop];return;}
    if(_timer)return;
    _socket=socket(AF_INET,SOCK_DGRAM,IPPROTO_UDP);
    if(_socket<0){[self clearOnce];return;}
    int flags=fcntl(_socket,F_GETFL,0);
    struct sockaddr_in a={0};a.sin_len=sizeof(a);a.sin_family=AF_INET;a.sin_addr.s_addr=htonl(INADDR_LOOPBACK);
    if(flags<0||fcntl(_socket,F_SETFL,flags|O_NONBLOCK)<0||bind(_socket,(const struct sockaddr*)&a,sizeof(a))<0){[self stop];return;}
    arc4random_buf(&_session,sizeof(_session));if(!_session)_session=1;
    _requestSequence=_server=0;_renewAt=0;_cleared=NO;MSRhythmReceiveResetState(&_received);
    __weak typeof(self) weakSelf=self;
    _timer=[NSTimer timerWithTimeInterval:1./60. repeats:YES block:^(NSTimer*t){(void)t;[weakSelf drain];}];
    [NSRunLoop.mainRunLoop addTimer:_timer forMode:NSRunLoopCommonModes];
    [self drain];
}
- (void)drain {
    if(_socket<0)return;
    if(_eligibilityHandler && !_eligibilityHandler()){[self stop];return;}
    double now=CACurrentMediaTime();
    if(now>=_renewAt){[self sendLease:YES];_renewAt=now+5.;}
    MSRhythmFrame latest={0};BOOL have=NO;
    for(unsigned count=0;count<16;++count){
        uint8_t data[1025];struct sockaddr_in a={0};socklen_t len=sizeof(a);
        ssize_t n=recvfrom(_socket,data,sizeof(data),0,(struct sockaddr*)&a,&len);
        if(n<0){if(errno==EINTR)continue;break;}
        if(len!=sizeof(a)||a.sin_family!=AF_INET||a.sin_addr.s_addr!=htonl(INADDR_LOOPBACK)||a.sin_port!=htons(MS_RHYTHM_PORT))continue;
        MSRhythmEnvelope envelope={0};MSRhythmFrame frame={0};
        if(!MSRhythmDecodePacket(data,(size_t)n,_session,&envelope,&frame))continue;
        int decision=MSRhythmReceive(&_received,&envelope,&frame,now);
        if(decision==MSRhythmReceiveReject)continue;
        if(_server!=envelope.server){
            uint64_t owner=0;arc4random_buf(&owner,sizeof(owner));if(!owner)owner=1;
            if(_sessionHandler)_sessionHandler(owner);
        }
        _server=envelope.server;
        if(decision==MSRhythmReceiveReset){have=NO;[self clearOnce];continue;}
        // Latest-value mailbox: buffered beats never become a burst of actions.
        latest=frame;have=YES;
    }
    if(have){_cleared=NO;if(_updateHandler)_updateHandler(latest,now);}
    else if(!MSRhythmReceiveFresh(&_received,now))[self clearOnce];
}
- (void)stop {
    [_timer invalidate];_timer=nil;
    if(_socket>=0){[self sendLease:NO];close(_socket);_socket=-1;}
    _session=_server=_requestSequence=0;MSRhythmReceiveResetState(&_received);[self clearOnce];
}
- (void)dealloc { [_timer invalidate];if(_socket>=0)close(_socket); }
@end
@interface MSRhythmPetBinding : NSObject
@property(nonatomic,weak) MiniSightPetView *pet;
@property(nonatomic,strong) MiniSightRhythmClient *client;
@property(nonatomic) NSUInteger token;
@property(nonatomic) BOOL enabled;
@property(nonatomic) double lastPosition,lastPositionAt;
@property(nonatomic) BOOL hasPosition;
@property(nonatomic) NSUInteger inputEvidenceMode;
@end
@implementation MSRhythmPetBinding
- (void)dealloc { [_client stop]; }
@end
static char MSRhythmPetBindingKey;
static BOOL MSRhythmPetInputEligible(MiniSightPetView *pet) {
    // Keep existing owner vetoes until parent separates daily and music owners.
    // Lyrics text itself is never tested; lyricsSuppressed is the attention gate.
    return pet && pet.musicPlaying && pet.window && !pet.window.hidden &&
        !pet.hidden && pet.alpha > .01 && pet.roamPace > 0 && !pet.roamingPaused &&
        !pet.interactionActive && !pet.activityActive && !pet.lyricsSuppressed &&
        !UIAccessibilityIsReduceMotionEnabled();
}
void MiniSightRhythmConfigurePet(MiniSightPetView *pet,BOOL enabled,NSUInteger token) {
    // Compatibility entry has NO measured position. Never infer seeks from
    // interpolated/default-zero musicPosition or metadata tick clocks.
    MiniSightRhythmConfigurePetWithPosition(pet,enabled,token,NAN);
}
void MiniSightRhythmConfigurePetWithPosition(MiniSightPetView *pet,BOOL enabled,NSUInteger token,double position) {
    NSCAssert(NSThread.isMainThread,@"rhythm host wiring must be main-thread");
    if(!pet)return;
    MSRhythmPetBinding *binding=objc_getAssociatedObject(pet,&MSRhythmPetBindingKey);
    if(!binding){
        binding=[MSRhythmPetBinding new];binding.pet=pet;binding.client=[MiniSightRhythmClient new];
        __weak MSRhythmPetBinding *weakBinding=binding;
        binding.client.eligibilityHandler=^BOOL {
            MSRhythmPetBinding *current=weakBinding;
            return current.enabled && MSRhythmPetInputEligible(current.pet);
        };
        binding.client.updateHandler=^(MSRhythmFrame frame,double receivedAt){
            MSRhythmPetBinding *current=weakBinding;
            if(current.enabled&&current.pet)[current.pet applyRhythmFrame:frame receivedAt:receivedAt];
        };
        binding.client.clearHandler=^{[weakBinding.pet clearRhythm];};
        binding.client.sessionHandler=^(uint64_t owner){[weakBinding.pet resetRhythmForSession:owner];};
        objc_setAssociatedObject(pet,&MSRhythmPetBindingKey,binding,OBJC_ASSOCIATION_RETAIN_NONATOMIC);
    }
    // Host eligibility is rechecked independently of metadata availability.
    enabled = enabled && token > 0 && MSRhythmPetInputEligible(pet);
    NSUInteger inputMode = enabled ? (MiniSightRhythmLiveTransportCompiled() ? 2u : 1u) : 0u;
    if (binding.inputEvidenceMode != inputMode) {
        binding.inputEvidenceMode = inputMode;
        MSDiagEvent(@"pet", @"state", @"ok", @{@"source": ([NSProcessInfo.processInfo.processName isEqualToString:@"SpringBoard"] ? @"plugin" : @"app"), @"reason": @"rhythm_transport_mode",
            @"input_mode": @(inputMode), @"input_ready": @NO, @"enabled": @(enabled)});
    }
    double now=CACurrentMediaTime();
    if(!isfinite(position)||position<0)position=NAN;
    BOOL seek=enabled&&binding.enabled&&binding.hasPosition&&isfinite(position)&&
        fabs(position-(binding.lastPosition+fmax(0.,now-binding.lastPositionAt)))>.8;
    if(binding.token!=token||binding.enabled!=enabled||seek){[binding.client stop];[pet clearRhythm];}
    binding.token=token;binding.enabled=enabled;
    binding.hasPosition=enabled&&isfinite(position);binding.lastPosition=position;binding.lastPositionAt=now;
    pet.rhythmFollowing=YES; // No data means ordinary life, never a fabricated beat.
    [binding.client configureEnabled:enabled];
}

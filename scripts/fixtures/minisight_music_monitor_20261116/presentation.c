#include "MiniSightMusicPresentationPolicy.h"
#include <assert.h>
#include <stdio.h>
int main(void) {
    MSMusicPresentation s = {0};
    s.shownKnown=s.shown=s.lyrics=s.motion=s.petStyle=s.windowExists=s.petExists=s.frameVisible=true;
    s.screenKnown=s.lockKnown=s.unlocked=s.containerKnown=true;
    s.windowAlpha=s.renderedAlpha=s.petAlpha=1;
    assert(MSMusicPresentationReason(s)==MSMusicGateOpen);
    s.renderedAlpha=0; assert(MSMusicPresentationReason(s)==MSMusicGateTransparent);
    s.renderedAlpha=1; assert(MSMusicPresentationReason(s)==MSMusicGateOpen);
    s.lyrics=false; assert(MSMusicPresentationReason(s)==MSMusicGateOpen);
    s.motion=false; assert(MSMusicPresentationReason(s)==MSMusicGateDisabled);
    s.motion=true; s.screenKnown=false; assert(MSMusicPresentationReason(s)==MSMusicGateScreenUnknown);
    s.screenKnown=true; s.lockKnown=false; assert(MSMusicPresentationReason(s)==MSMusicGateLockUnknown);
    s.lockKnown=true; s.unlocked=false; assert(MSMusicPresentationReason(s)==MSMusicGateLocked);
    s.unlocked=true; s.shown=false; assert(MSMusicPresentationReason(s)==MSMusicGateUserHidden);
    s.shown=true; s.appOwned=true; assert(MSMusicPresentationReason(s)==MSMusicGateAppUnverified);
    s.appFrontmost=true; s.windowExists=false; s.windowHidden=true; s.petExists=false;
    assert(MSMusicPresentationReason(s)==MSMusicGateOpen); /* App owns actual local visibility */
    s.unlocked=false; assert(MSMusicPresentationReason(s)==MSMusicGateLocked);
    s.unlocked=true; s.screenKnown=false; assert(MSMusicPresentationReason(s)==MSMusicGateScreenUnknown);
    s.screenKnown=true; s.appOwned=false; s.windowExists=true; s.windowHidden=false; s.petExists=true;
    s.frameVisible=false; assert(MSMusicPresentationReason(s)==MSMusicGateOffscreen);
    s.frameVisible=true; s.petAlpha=NAN; assert(MSMusicPresentationReason(s)==MSMusicGateTransparent);
    s.petAlpha=1; s.shownKnown=false; assert(MSMusicPresentationReason(s)==MSMusicGateShownUnknown);
    uint64_t epoch=0, oldRead=MSMusicNextEpoch(&epoch), hide=MSMusicNextEpoch(&epoch);
    assert(!MSMusicEpochIsCurrent(epoch,oldRead)); assert(MSMusicEpochIsCurrent(epoch,hide));
    uint64_t show=MSMusicNextEpoch(&epoch); assert(!MSMusicEpochIsCurrent(epoch,hide));
    assert(MSMusicEpochIsCurrent(epoch,show));
    assert(!MSMusicShownMayReleaseHidden(true,true,false,false,true,false)); /* old ON after failed hide */
    assert(!MSMusicShownMayReleaseHidden(true,true,true,true,true,true)); /* pending hide always wins */
    assert(!MSMusicShownMayReleaseHidden(false,true,false,true,true,true)); /* no file proof */
    assert(MSMusicShownMayReleaseHidden(true,true,false,true,false,false)); /* OFF -> ON observed */
    assert(MSMusicShownMayReleaseHidden(true,true,false,false,true,true)); /* distinct atomic ON */
    puts("PORTABLE PASS: production gate, fade/recovery, switches, unknown/locked shutdown, App proxy, explicit hide transaction and latest epochs");
    return 0;
}

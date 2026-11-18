// Direct production C geometry checks; NOT a simulation of Show/Follow globals.
// Native exact-function fixture separately owns those state/cache regressions.
#include <stdio.h>
#include <stdlib.h>
static long MSBubbleEdgeCases(void) {
    long n=0;
#define EDGE_CHECK(x) do { n++; if (!(x)) { fprintf(stderr,"FAIL C bubble line %d: %s\n",__LINE__,#x); exit(1); } } while(0)
    MSLayout legacy=MSLayoutMake(390,844,47,34,0,0,8,56,61,7,52);
    MSLayout pet=legacy;
    pet.centers=MSBodyCenterBounds(390,844,pet.body,2);
    MSPoint top=MSLayoutClamp(pet,(MSPoint){30,0}), middle={30,400};
    MSSize intent={160,52};
    MSRect box=MSLayoutBubble(pet,top,intent);
    EDGE_CHECK(!MSLayoutBubbleFits(pet,top,box));
    EDGE_CHECK(fabs(top.y-32.5)<.001);
    box=MSLayoutBubble(pet,middle,intent);
    EDGE_CHECK(MSLayoutBubbleFits(pet,middle,box));
    EDGE_CHECK(box.w==160 && box.h==52);
    MSSize texts[]={{260,216},{104,34},{160,52}};
    for (unsigned i=0;i<3;i++) {
        box=MSLayoutBubble(pet,top,texts[i]);
        EDGE_CHECK(!MSLayoutBubbleFits(pet,top,box));
        box=MSLayoutBubble(pet,middle,texts[i]);
        EDGE_CHECK(MSLayoutBubbleFits(pet,middle,box));
        EDGE_CHECK(box.w==texts[i].w && box.h==texts[i].h);
    }
    MSLayout narrow=MSLayoutMake(120,844,47,34,0,0,8,56,61,7,52);
    MSRect clipped=MSLayoutBubble(narrow,middle,intent);
    EDGE_CHECK(clipped.w<160);
    box=MSLayoutBubble(pet,middle,intent);
    EDGE_CHECK(box.w==160 && box.h==52);
    // Demonstrate WHY bounds must not become the next intent (not a mutation test).
    MSRect lost=MSLayoutBubble(pet,middle,(MSSize){clipped.w,clipped.h});
    EDGE_CHECK(lost.w!=intent.w);
    lost=MSLayoutBubble(pet,middle,(MSSize){0,0});
    EDGE_CHECK(lost.w==1 && lost.h==1);
    MSLayout rotated=MSLayoutMake(844,390,47,34,0,0,8,56,61,7,52);
    MSPoint stationary={130,200};
    box=MSLayoutBubble(rotated,stationary,intent);
    EDGE_CHECK(MSLayoutBubbleFits(rotated,stationary,box));
    rotated.safe.y=180;
    box=MSLayoutBubble(rotated,stationary,intent);
    EDGE_CHECK(!MSLayoutBubbleFits(rotated,stationary,box));
    MSLayout approval=MSLayoutMake(390,844,47,34,0,0,8,56,61,7,124);
    MSPoint a=MSLayoutAnchorForBubble(approval,top,(MSSize){180,140});
    box=MSLayoutBubble(approval,a,(MSSize){180,140});
    EDGE_CHECK(a.y>top.y);
    EDGE_CHECK(MSLayoutBubbleFits(approval,a,box));
    EDGE_CHECK(box.h>=40+30 && box.w>=180);
    EDGE_CHECK(approval.centers.y>pet.centers.y);
    MSLayout capsule=MSLayoutMake(390,844,47,34,0,0,8,132,36,7,52);
    a=MSLayoutAnchorForBubble(capsule,top,intent);
    box=MSLayoutBubble(capsule,a,intent);
    EDGE_CHECK(a.y>top.y && MSLayoutBubbleFits(capsule,a,box));
#undef EDGE_CHECK
    return n;
}

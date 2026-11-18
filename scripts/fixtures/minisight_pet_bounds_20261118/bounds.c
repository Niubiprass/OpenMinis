#include "MiniSightGeometry.h"
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
static unsigned checks;
#define CHECK(v) do { ++checks; if (!(v)) { fprintf(stderr,"FAIL bounds line %d\n",__LINE__); return 1; } } while(0)
int main(void) {
    const double e=1.e-7;
    const double sizes[][2]={{390,844},{844,390},{320,568},{568,320},{430,932}};
    for (unsigned s=0;s<sizeof(sizes)/sizeof(sizes[0]);++s) {
        double w=sizes[s][0],h=sizes[s][1];
        for (int bw=20;bw<=180;bw+=4) for (int bh=20;bh<=200;bh+=5) {
            MSSize body={(double)bw,(double)bh};
            MSRect b=MSBodyCenterBounds(w,h,body,2.);
            CHECK(fabs(b.x-bw*.5-2.)<e && fabs(b.y-bh*.5-2.)<e);
            CHECK(fabs(b.x+b.w+bw*.5-(w-2.))<e);
            CHECK(fabs(b.y+b.h+bh*.5-(h-2.))<e);
            for (int side=0;side<4;++side) {
                MSPoint a=MSClampCenter(b,(MSPoint){side&1?w+900:-900,side&2?h+900:-900});
                CHECK(a.x-bw*.5>=-e && a.x+bw*.5<=w+e);
                CHECK(a.y-bh*.5>=-e && a.y+bh*.5<=h+e);
                CHECK(a.y-MSJumpHeight(b,a,26.)>=b.y-e);
                MSPoint z=MSClampCenter(b,(MSPoint){w-a.x,h-a.y});
                for (int i=0;i<=10;++i) {
                    MSPoint p=MSMotionPoint(a,z,i/10.);
                    CHECK(p.x>=b.x-e && p.x<=b.x+b.w+e && p.y>=b.y-e && p.y<=b.y+b.h+e);
                }
            }
        }
    }
    // Actual affine corners: drag/flight/tilt/pivot effects must not cross an edge,
    // even with gravity disabled. Normal interior transforms remain unchanged.
    for (int side=0;side<4;++side) for (int turn=-80;turn<=80;turn+=2) {
        double angle=turn*.02, sx=1.08, sy=1.035;
        MSPoint center={side&1?360:30,side&2?811:33};
        MSVisualTransform t={cos(angle)*sx,sin(angle)*sx,-sin(angle)*sy,cos(angle)*sy,15,-20};
        MSVisualTransform f=MSPetFitVisualTransform((MSRect){0,0,390,844},center,(MSSize){56,61},t);
        for (int corner=0;corner<4;++corner) {
            double x=corner&1?28:-28,y=corner&2?30.5:-30.5;
            double rx=center.x+f.a*x+f.c*y+f.tx,ry=center.y+f.b*x+f.d*y+f.ty;
            CHECK(rx>=2-e && rx<=388+e && ry>=2-e && ry<=842+e);
        }
        MSVisualTransform middle=MSPetFitVisualTransform((MSRect){0,0,390,844},(MSPoint){195,422},(MSSize){56,61},t);
        CHECK(middle.a==t.a && middle.b==t.b && middle.c==t.c && middle.d==t.d);
        CHECK(fabs(middle.tx-t.tx)<e && fabs(middle.ty-t.ty)<e);
    }
    MSVisualTransform big=MSPetFitVisualTransform((MSRect){0,0,30,20},(MSPoint){15,10},(MSSize){100,100},(MSVisualTransform){1,0,0,1,0,0});
    CHECK(fabs(big.a-.16)<e && fabs(big.d-.16)<e);
    // Finite collapsed range if a transient viewport is smaller than the body.
    MSRect small=MSBodyCenterBounds(30,20,(MSSize){60,80},2.);
    CHECK(small.x==15 && small.y==10 && small.w==0 && small.h==0);
    MSRect invalid=MSBodyCenterBounds(NAN,INFINITY,(MSSize){NAN,INFINITY},NAN);
    CHECK(isfinite(invalid.x) && isfinite(invalid.y) && isfinite(invalid.w) && isfinite(invalid.h));
    printf("PASS actual MSBodyCenterBounds: %u checks; edges/rotation/motion/invalid viewport\n",checks);
    return 0;
}

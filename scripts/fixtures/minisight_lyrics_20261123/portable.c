/* The runner prepends the verbatim production C policy, not an ObjC port. */
#include <stdio.h>
static unsigned checks;
#define CHECK(x) do { ++checks; if (!(x)) { fprintf(stderr,"FAIL portable line %d: %s\n",__LINE__,#x); return 1; } } while (0)
static double TimeAt(const void *p, size_t i) { return ((const double *)p)[i]; }
int main(void) {
    CHECK(MSLyricsDurationOK(1) && MSLyricsDurationOK(3600));
    CHECK(!MSLyricsDurationOK(0) && !MSLyricsDurationOK(3601));
    CHECK(!MSLyricsDurationOK(NAN) && !MSLyricsDurationOK(INFINITY));
    double markers[] = {1.,3.,10.};
    CHECK(MSLyricsMarkerIndex(0,60,3,markers,TimeAt)==SIZE_MAX);
    CHECK(MSLyricsMarkerIndex(1,60,3,markers,TimeAt)==0);
    CHECK(MSLyricsMarkerIndex(3,60,3,markers,TimeAt)==1);
    CHECK(MSLyricsMarkerIndex(59,60,3,markers,TimeAt)==2);
    CHECK(MSLyricsMarkerIndex(60,60,3,markers,TimeAt)==SIZE_MAX);
    CHECK(MSLyricsMarkerIndex(NAN,60,3,markers,TimeAt)==SIZE_MAX);
    CHECK(MSLyricsMarkerIndex(3,60,4097,markers,TimeAt)==SIZE_MAX);
    CHECK(MSLyricsMarkerIndex(3,60,3,NULL,TimeAt)==SIZE_MAX);
    CHECK(MSLyricsMarkerIndex(3,60,3,markers,NULL)==SIZE_MAX);
    long statuses[] = {0,200,302,400,401,404,429,500,503};
    for (unsigned failed=0;failed<2;failed++) for(unsigned search=0;search<2;search++)
        for(unsigned attempted=0;attempted<2;attempted++) for(unsigned unsynced=0;unsynced<2;unsynced++)
            for(unsigned i=0;i<sizeof(statuses)/sizeof(*statuses);i++) {
                bool want=!failed&&!search&&!attempted&&(statuses[i]==404||(statuses[i]==200&&unsynced));
                CHECK(MSLyricsShouldSearch(failed,statuses[i],search,attempted,unsynced)==want);
                /* Once attempted, even another empty 200 or 404 cannot recurse. */
                CHECK(!MSLyricsShouldSearch(failed,statuses[i],search,true,unsynced));
            }
    for(unsigned failed=0;failed<2;failed++) for(unsigned timeline=0;timeline<2;timeline++)
        for(unsigned search=0;search<2;search++) for(unsigned rejected=0;rejected<2;rejected++)
            for(unsigned i=0;i<sizeof(statuses)/sizeof(*statuses);i++) {
                bool want=!failed&&(timeline||(search&&(statuses[i]==404||(statuses[i]==200&&!rejected))));
                CHECK(MSLyricsShouldCache(failed,timeline,search,statuses[i],rejected)==want);
            }
    double durations[] = {58,62,60}; size_t equivalent[] = {0,1,2};
    unsigned orders[][3]={{0,1,2},{0,2,1},{1,0,2},{1,2,0},{2,0,1},{2,1,0}};
    for(unsigned i=0;i<6;i++) {
        double d[3]; size_t e[3];
        for(unsigned j=0;j<3;j++) { d[j]=durations[orders[i][j]];e[j]=equivalent[orders[i][j]]; }
        size_t index=MSLyricsClosestCandidate(d,e,3,60);
        CHECK(index!=SIZE_MAX && d[index]==60);
    }
    double tie[]={59,61};size_t distinct[]={0,1};
    CHECK(MSLyricsClosestCandidate(tie,distinct,2,60)==SIZE_MAX);
    double duplicate[]={60,60};size_t same[]={0,0};
    CHECK(MSLyricsClosestCandidate(duplicate,same,2,60)==0);
    CHECK(MSLyricsClosestCandidate(duplicate,distinct,2,60)==SIZE_MAX);
    double bad[]={62.001,NAN,INFINITY,0};size_t one[]={0};
    for(unsigned i=0;i<4;i++) CHECK(MSLyricsClosestCandidate(&bad[i],one,1,60)==SIZE_MAX);
    CHECK(MSLyricsClosestCandidate(durations,equivalent,21,60)==SIZE_MAX);
    CHECK(MSLyricsClosestCandidate(NULL,equivalent,3,60)==SIZE_MAX);
    CHECK(MSLyricsClosestCandidate(durations,NULL,3,60)==SIZE_MAX);
    CHECK(MSLyricsDispatchReady(14.999,15));
    CHECK(!MSLyricsDispatchReady(15,15) && !MSLyricsDispatchReady(16,15));
    CHECK(!MSLyricsDispatchReady(NAN,15) && !MSLyricsDispatchReady(1,INFINITY));
    printf("PORTABLE PASS: %u checks; verbatim production C only (not Foundation transport)\n",checks);
    return 0;
}

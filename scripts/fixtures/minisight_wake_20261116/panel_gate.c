#include "MiniSightNameWakeGate.h"
#include <stdio.h>
#include <stdlib.h>

static unsigned checks;
static void verify(bool value, bool expected, const char *message) {
    ++checks;
    if (value != expected) { fprintf(stderr, "FAIL %s\n", message); exit(1); }
}
int main(void) {
    const uint64_t ids[] = {0, 1, 42, UINT64_MAX};
    for (unsigned a=0; a<4; ++a) for (unsigned b=0; b<4; ++b)
    for (unsigned c=0; c<4; ++c) for (unsigned flags=0; flags<64; ++flags) {
        bool pending = flags & 1, visible = flags & 2, sending = flags & 4;
        bool editing = flags & 8, voicePending = flags & 16, voiceListening = flags & 32;
        bool onlyOriginal = a > 0 && a == b && a == c;
        bool onlyFreePanel = flags == 3;
        verify(MSNameWakeMayStartInput(ids[a], ids[b], ids[c], pending, visible,
            sending, editing, voicePending, voiceListening),
            onlyOriginal && onlyFreePanel, "matrix identity+ownership");
    }
    verify(MSNameWakeMayStartInput(42,42,43,true,true,false,false,false,false),false,"reopened panel");
    verify(MSNameWakeMayStartInput(42,0,42,false,true,false,false,false,false),false,"cancelled response");
    verify(MSNameWakeMayStartInput(42,42,42,true,true,false,true,false,false),false,"keyboard takeover");
    verify(MSNameWakeMayStartInput(42,42,42,false,true,false,false,true,false),false,"consumed once");
    printf("PASS production name-panel C gate: %u checks; no UIKit/audio execution\n", checks);
    return 0;
}

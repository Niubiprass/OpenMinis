#include "MiniSightMusicPlayerABI.h"
#include <assert.h>
#include <stdio.h>
int main(void) {
    assert(MSMusicPIDABIForTypes("@",3,"@",":","i","q") == MSMusicPIDABIInt);
    assert(MSMusicPIDABIForTypes("@",3,"@",":","q","q") == MSMusicPIDABINSInteger);
    assert(MSMusicPIDABIForTypes("@",3,"@",":","l","l") == MSMusicPIDABINSInteger);
    assert(MSMusicPIDABIForTypes("@",3,"@",":","i","i") == MSMusicPIDABIInt);
    const char *bad[] = {"f", "d", "@", "@?", "#", "^i", "I", "Q", "s", "B", "ri", "", "ii", NULL};
    for (size_t i=0; i<sizeof(bad)/sizeof(*bad); ++i)
        assert(MSMusicPIDABIForTypes("@",3,"@",":",bad[i],"q") == MSMusicPIDABIRejected);
    assert(!MSMusicPIDABIForTypes("d",3,"@",":","i","q"));
    assert(!MSMusicPIDABIForTypes("@?",3,"@",":","i","q"));
    assert(!MSMusicPIDABIForTypes("@",2,"@",":","i","q"));
    assert(!MSMusicPIDABIForTypes("@",4,"@",":","i","q"));
    assert(!MSMusicPIDABIForTypes("@",3,"#",":","i","q"));
    assert(!MSMusicPIDABIForTypes("@",3,"@","@","i","q"));
    assert(!MSMusicPIDABIForTypes(NULL,3,"@",":","i","q"));
    assert(!MSMusicPIDABIForTypes("@",3,NULL,":","i","q"));
    assert(!MSMusicPIDABIForTypes("@",3,"@",NULL,"i","q"));
    assert(!MSMusicPIDABIForTypes("@",3,"@",":","q",NULL));
    assert(!MSMusicPIDABIForTypes("@",3,"@",":","q","l"));
    puts("PORTABLE PASS: production PID ABI classifier int/pid_t + NSInteger, rejected float/object/pointer/unsigned/wrong signatures");
    return 0;
}

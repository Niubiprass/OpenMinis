/* Tests the unchanged production MSMusicSymbol body with constructed Mach-O
 * layouts. This proves the fileoff predicate defect, NOT dyld/MR/PAC ABI.
 * Layout/flags correspond to Apple's public mach-o/loader.h (64-bit).
 */
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef int BOOL;
#define YES 1
#define NO 0
typedef const void *CFStringRef;
#ifndef __has_feature
#define __has_feature(x) 0
#endif
#define MH_MAGIC_64 0xfeedfacf
#define LC_SEGMENT_64 0x19
#define SEG_TEXT "__TEXT"
#define S_ATTR_PURE_INSTRUCTIONS 0x80000000u
#define S_ATTR_SOME_INSTRUCTIONS 0x00000400u
#define VM_PROT_READ 1
#define VM_PROT_EXECUTE 4
struct mach_header_64 { uint32_t magic, cputype, cpusubtype, filetype, ncmds, sizeofcmds, flags, reserved; };
struct load_command { uint32_t cmd, cmdsize; };
struct segment_command_64 { uint32_t cmd, cmdsize; char segname[16]; uint64_t vmaddr, vmsize, fileoff, filesize; int32_t maxprot, initprot; uint32_t nsects, flags; };
struct section_64 { char sectname[16], segname[16]; uint64_t addr, size; uint32_t offset, align, reloff, nreloc, flags, reserved1, reserved2, reserved3; };
_Static_assert(sizeof(struct mach_header_64) == 32, "Mach-O header layout");
_Static_assert(sizeof(struct segment_command_64) == 72, "Mach-O segment layout");
_Static_assert(sizeof(struct section_64) == 80, "Mach-O section layout");
struct Image { struct mach_header_64 header; struct segment_command_64 text; struct section_64 code; struct segment_command_64 data; struct section_64 constant; unsigned char payload[128]; };
static struct Image image;
typedef struct { const char *dli_fname; void *dli_fbase; const char *dli_sname; void *dli_saddr; } Dl_info;
static void *dlsym(void *handle, const char *name) {
    (void)handle;
    if (!strcmp(name, "code")) return image.payload;
    if (!strcmp(name, "data")) return image.payload + 64;
    if (!strcmp(name, "truncated")) return image.payload + 64 + 8 - sizeof(CFStringRef) + 1;
    return NULL;
}
static int dladdr(const void *address, Dl_info *info) { (void)address; info->dli_fbase = &image; return 1; }
/* PRODUCTION_SYMBOL_FUNCTION */
static void check(int good, const char *name) { if (!good) { fprintf(stderr, "FAIL: %s\n", name); exit(1); } }
static void reset(uint64_t fileoff) {
    memset(&image, 0, sizeof(image));
    image.header.magic = MH_MAGIC_64; image.header.ncmds = 2;
    image.header.sizeofcmds = offsetof(struct Image, payload) - sizeof(image.header);
    image.text.cmd = image.data.cmd = LC_SEGMENT_64;
    image.text.cmdsize = image.data.cmdsize = sizeof(image.text) + sizeof(image.code);
    strcpy(image.text.segname, SEG_TEXT); strcpy(image.data.segname, "__DATA_CONST");
    image.text.vmaddr = 0x180000000; image.data.vmaddr = image.text.vmaddr + 4096;
    image.text.vmsize = image.data.vmsize = 4096;
    image.text.fileoff = fileoff; image.data.fileoff = fileoff + 4096;
    image.text.filesize = image.data.filesize = 4096;
    image.text.initprot = VM_PROT_READ | VM_PROT_EXECUTE; image.data.initprot = VM_PROT_READ;
    image.text.nsects = image.data.nsects = 1;
    image.code.addr = image.text.vmaddr + offsetof(struct Image, payload); image.code.size = 8;
    image.code.flags = S_ATTR_PURE_INSTRUCTIONS | S_ATTR_SOME_INSTRUCTIONS;
    image.constant.addr = image.code.addr + 64; image.constant.size = 8;
}
int main(void) {
    void *handle = &image;
    reset(0); check(MSMusicSymbol(handle, "code", YES) == image.payload, "ordinary image code accepted");
    check(MSMusicSymbol(handle, "data", NO) == image.payload + 64, "ordinary image data accepted");
    reset(0x128000); check(MSMusicSymbol(handle, "code", YES) == image.payload, "shared-cache nonzero fileoff code accepted");
    check(MSMusicSymbol(handle, "data", NO) == image.payload + 64, "shared-cache nonzero fileoff data accepted");
    check(!MSMusicSymbol(handle, "data", YES), "data cannot be called as code");
    check(!MSMusicSymbol(handle, "code", NO), "code cannot be dereferenced as data");
    check(!MSMusicSymbol(handle, "truncated", NO), "complete pointer slot required");
    check(!MSMusicSymbol(handle, "missing", YES), "missing export rejected");
    check(!MSMusicSymbol(NULL, "code", YES), "missing handle rejected");
    image.text.initprot = VM_PROT_READ;
    check(!MSMusicSymbol(handle, "code", YES), "non-executable code rejected");
    reset(0x128000); image.data.initprot |= VM_PROT_EXECUTE;
    check(!MSMusicSymbol(handle, "data", NO), "executable data rejected");
    reset(0x128000); image.data.initprot = 0;
    check(!MSMusicSymbol(handle, "data", NO), "unreadable data rejected");
    reset(0x128000); strcpy(image.text.segname, "__TEXT_BAD");
    check(!MSMusicSymbol(handle, "code", YES), "missing exact text segment rejected");
    reset(0x128000); strcpy(image.data.segname, SEG_TEXT);
    check(!MSMusicSymbol(handle, "code", YES), "duplicate text segment rejected");
    reset(0x128000); image.text.cmdsize = 0;
    check(!MSMusicSymbol(handle, "code", YES), "malformed load command rejected");
    reset(0x128000); image.text.nsects = 100;
    check(!MSMusicSymbol(handle, "code", YES), "section count overflow rejected");
    puts("PORTABLE PASS: production symbol resolver; 16 layout/kind guards; no ABI claim");
    return 0;
}

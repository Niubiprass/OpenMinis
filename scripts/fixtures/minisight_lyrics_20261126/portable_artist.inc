/* Verbatim production matcher: normalized UTF-8 atoms, not Foundation execution. */
static bool Artist(const char *credit, const char *const *names, size_t count) {
    const uint8_t *parts[21]; size_t lengths[21];
    if (count > 21) return false;
    for (size_t i = 0; i < count; ++i) { parts[i] = (const uint8_t *)names[i]; lengths[i] = strlen(names[i]); }
    return MSLyricsArtistIdentity((const uint8_t *)credit, strlen(credit), parts, lengths, count);
}
static int ArtistIdentityTests(void) {
    const char *duo[] = {"alice", "bob"};
    const char *solo[] = {"alice"};
    const char *soloPunctuation[] = {"ac/dc"};
    const char *embedded[] = {"earth, wind & fire", "bob"};
    const char *duplicates[] = {"alice", "alice"};
    const char *spaced[] = {"alice smith", "bob jones"};
    const char *cjk[] = {"合成歌手甲", "合成歌手乙"};
    const char *yes[] = {"alice/bob", "alice / bob", "bob/alice", "alice、bob", "bob 、 alice", "alice&bob", "bob & alice", "alice bob"};
    for (size_t i = 0; i < sizeof(yes)/sizeof(*yes); ++i) CHECK(Artist(yes[i], duo, 2));
    const char *no[] = {"alice", "bob", "alice/bob/cat", "alice/alice", "bob alice", "alice bob cat", "alicebob", "ali/bob", "alice/bobby", "/alice/bob", "alice//bob", "alice/&bob", "alice/bob/", "alice, bob", "alice;bob", "alice feat. bob", "alice + bob"};
    for (size_t i = 0; i < sizeof(no)/sizeof(*no); ++i) CHECK(!Artist(no[i], duo, 2));
    CHECK(Artist("alice", solo, 1) && !Artist("alice/bob", solo, 1));
    CHECK(Artist("ac/dc", soloPunctuation, 1) && !Artist("ac / dc", soloPunctuation, 1));
    CHECK(!Artist("alice/alice", duplicates, 2));
    CHECK(!Artist("earth, wind & fire / bob", embedded, 2));
    CHECK(!Artist("earth, wind / fire & bob", embedded, 2));
    CHECK(Artist("bob jones / alice smith", spaced, 2));
    CHECK(Artist("alice smith bob jones", spaced, 2));
    CHECK(Artist("earth, wind & fire bob", embedded, 2)); // Original complete-list exact form, not split.
    CHECK(!Artist("alice smith bob", spaced, 2));
    CHECK(!Artist("alice/smith bob jones", spaced, 2));
    CHECK(Artist("合成歌手乙、合成歌手甲", cjk, 2));
    CHECK(!Artist("合成歌手甲合成歌手乙", cjk, 2));
    const char *trio[] = {"alice", "bob", "cat"};
    CHECK(Artist("cat & alice、bob", trio, 3));
    CHECK(!Artist("alice/bob", trio, 3));
    const uint8_t *parts[] = {(const uint8_t *)"a", (const uint8_t *)"b"}; size_t lengths[] = {1, 1};
    CHECK(!MSLyricsArtistIdentity(NULL, 1, parts, lengths, 2));
    CHECK(!MSLyricsArtistIdentity((const uint8_t *)"a/b", 0, parts, lengths, 2));
    CHECK(!MSLyricsArtistIdentity((const uint8_t *)"a/b", 2049, parts, lengths, 2));
    CHECK(!MSLyricsArtistIdentity((const uint8_t *)"a/b", 3, NULL, lengths, 2));
    CHECK(!MSLyricsArtistIdentity((const uint8_t *)"a/b", 3, parts, NULL, 2));
    CHECK(!MSLyricsArtistIdentity((const uint8_t *)"a/b", 3, parts, lengths, 0));
    CHECK(!MSLyricsArtistIdentity((const uint8_t *)"a/b", 3, parts, lengths, 21));
    const uint8_t *bad[] = {NULL}; size_t zero[] = {0}; size_t huge[] = {2049};
    CHECK(!MSLyricsArtistIdentity((const uint8_t *)"a", 1, bad, lengths, 1));
    CHECK(!MSLyricsArtistIdentity((const uint8_t *)"a", 1, parts, zero, 1));
    CHECK(!MSLyricsArtistIdentity((const uint8_t *)"a", 1, parts, huge, 1));
    CHECK(MSLyricsArtistSeparator((const uint8_t *)"\xe3\x80", 2) == 0);
    printf("ARTIST POLICY PASS: explicit complete sets; punctuation/duplicate/subset guards (not Foundation)\n");
    return 0;
}

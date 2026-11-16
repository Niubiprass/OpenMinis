+ (NSDictionary<NSString *, id> *)shownEvidenceWithContainer:(NSString *)container {
    return MSMusicShownEvidence(container, nil);
}
+ (BOOL)saveShown:(BOOL)shown container:(NSString *)container {
    return MSMusicWriteShownVerified(shown, container);
}

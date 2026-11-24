// Included inside MSHFServer after gAnalyzer is defined. All calls are made on
// the serial control queue, never AudioUnitRender. No PCM is exported here.
void ResetRhythmState() {
    gAnalyzer.rhythmClock.Break();
    if (gAnalyzer.rhythmAnalyzer) MSRhythmAnalyzerReset(gAnalyzer.rhythmAnalyzer);
}

void DestroyRhythmState() {
    if (gAnalyzer.rhythmAnalyzer) {
        MSRhythmAnalyzerDestroy(gAnalyzer.rhythmAnalyzer);
        gAnalyzer.rhythmAnalyzer = nullptr;
    }
    gAnalyzer.rhythmClock.Break();
}

static void ProduceRhythmFrame(bool active, bool stale, float rms, float peak,
                               MSRhythmFrame *out) {
    auto &clock = gAnalyzer.rhythmClock;
    const bool finite = std::isfinite(rms) && std::isfinite(peak) &&
                        rms >= 0 && peak >= rms && peak <= 8 &&
                        clock.sampleRate >= 8000 && clock.sampleRate <= 192000;
    const bool silence = !active || stale || (finite && rms <= 1.0e-5f);
    const bool eligible = !silence && finite &&
        !gAnalyzer.nonFiniteInputPending && clock.samples >= kAnalysisFrames &&
        gAnalyzer.rollingCount >= kAnalysisFrames;
    if ((!eligible && (silence || !finite || gAnalyzer.nonFiniteInputPending)) &&
        !clock.invalid) ResetRhythmState();
    *out = {};
    out->epoch = clock.epoch;
    out->sequence = clock.sequence;
    out->sampleTime = clock.Time();
    out->rms = finite ? rms : 0;
    out->peak = finite ? peak : 0;
    if (silence) out->flags |= MSRhythmFlagSilence;
    if (peak >= 0.999f) out->flags |= MSRhythmFlagClipping;
    if (clock.discontinuity || !finite || gAnalyzer.nonFiniteInputPending)
        out->flags |= MSRhythmFlagDiscontinuity;
    if (!clock.Fresh()) return; // polling cannot emit a repeated Beat/Valid
    clock.Consume();
    out->sequence = clock.sequence;
    if (!eligible) {
        clock.invalid = true;
        return;
    }
    if (!gAnalyzer.rhythmAnalyzer)
        gAnalyzer.rhythmAnalyzer = MSRhythmAnalyzerCreate();
    if (!gAnalyzer.rhythmAnalyzer) {
        out->flags |= MSRhythmFlagDiscontinuity;
        return;
    }
    if (clock.pendingReset) {
        MSRhythmAnalyzerReset(gAnalyzer.rhythmAnalyzer);
        clock.pendingReset = false;
    }
    MSRhythmFrame analyzed{};
    bool ok = MSRhythmAnalyzerProcess(gAnalyzer.rhythmAnalyzer,
        gAnalyzer.rhythmMagnitude, kRhythmBinCount, clock.epoch, clock.sequence,
        clock.Time(), clock.sampleRate, rms, peak, &analyzed);
    if (ok && MSRhythmFrameSane(&analyzed)) *out = analyzed;
    else out->flags |= MSRhythmFlagDiscontinuity;
    // A reset frame is explicitly INVALID even if the wrapper has a cached
    // estimate. The consumer must discard prior phase before a later frame.
    if (clock.discontinuity || !ok) {
        out->flags &= ~(MSRhythmFlagValid | MSRhythmFlagBeat);
        out->flags |= MSRhythmFlagDiscontinuity;
        out->period = out->phase = out->confidence = 0;
    }
    clock.invalid = false;
    clock.ClearDiscontinuity();
}

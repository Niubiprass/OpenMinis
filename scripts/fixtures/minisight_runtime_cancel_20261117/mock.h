#ifndef CANCEL_FIXTURE_MOCK_H
#define CANCEL_FIXTURE_MOCK_H
#include <stdint.h>
/* Test-only C API stand-in. Forward declarations import as OpaquePointer. */
typedef struct SherpaOnnxKeywordSpotter SherpaOnnxKeywordSpotter;
typedef struct SherpaOnnxOnlineStream SherpaOnnxOnlineStream;
typedef struct { int32_t sample_rate, feature_dim; } SherpaOnnxFeatureConfig;
typedef struct { const char *encoder, *decoder, *joiner; } SherpaOnnxTransducerConfig;
typedef struct {
  SherpaOnnxTransducerConfig transducer;
  const char *tokens;
  int32_t num_threads;
  const char *provider;
  int32_t debug;
} SherpaOnnxModelConfig;
typedef struct {
  SherpaOnnxFeatureConfig feat_config;
  SherpaOnnxModelConfig model_config;
  int32_t max_active_paths, num_trailing_blanks;
  float keywords_score, keywords_threshold;
  const char *keywords_buf;
  int32_t keywords_buf_size;
} SherpaOnnxKeywordSpotterConfig;
typedef struct { const char *keyword; } SherpaOnnxKeywordResult;
int32_t SherpaOnnxMiniSightRuntimeIsCompatible(void);
const SherpaOnnxKeywordSpotter *SherpaOnnxCreateKeywordSpotter(const SherpaOnnxKeywordSpotterConfig *);
const SherpaOnnxOnlineStream *SherpaOnnxCreateKeywordStream(const SherpaOnnxKeywordSpotter *);
void SherpaOnnxDestroyKeywordSpotter(const SherpaOnnxKeywordSpotter *);
void SherpaOnnxDestroyOnlineStream(const SherpaOnnxOnlineStream *);
void SherpaOnnxOnlineStreamAcceptWaveform(const SherpaOnnxOnlineStream *, int32_t, const float *, int32_t);
int32_t SherpaOnnxIsKeywordStreamReady(const SherpaOnnxKeywordSpotter *, const SherpaOnnxOnlineStream *);
void SherpaOnnxDecodeKeywordStream(const SherpaOnnxKeywordSpotter *, const SherpaOnnxOnlineStream *);
const SherpaOnnxKeywordResult *SherpaOnnxGetKeywordResult(const SherpaOnnxKeywordSpotter *, const SherpaOnnxOnlineStream *);
void SherpaOnnxDestroyKeywordResult(const SherpaOnnxKeywordResult *);
void SherpaOnnxResetKeywordStream(const SherpaOnnxKeywordSpotter *, const SherpaOnnxOnlineStream *);
void CancelMockReset(void);
int32_t CancelMockCount(int32_t kind);
int32_t CancelMockDestroyed(int32_t kind, int32_t index);
int32_t CancelMockInvalidDestroy(void);
int32_t CancelMockAcceptCount(void);
void CancelMockSetMode(int32_t mode);
void CancelFixtureConstructorBarrier(void);
#endif

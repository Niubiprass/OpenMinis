#include "mock.h"
#include <assert.h>
#include <pthread.h>
#include <stdlib.h>
#include <string.h>
/* Retain tombstones until reset: diagnose wrong-kind/double/parent-first destroy. */
struct SherpaOnnxKeywordSpotter { int index, destroyed; };
struct SherpaOnnxOnlineStream { int index, destroyed; const SherpaOnnxKeywordSpotter *parent; };
static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
static SherpaOnnxKeywordSpotter *models[64];
static SherpaOnnxOnlineStream *streams[64];
static int nm, ns, invalid, accepts, mode;
void CancelMockReset(void) {
  pthread_mutex_lock(&lock);
  for (int i=0;i<ns;i++) { assert(streams[i]->destroyed==1); free(streams[i]); }
  for (int i=0;i<nm;i++) { assert(models[i]->destroyed==1); free(models[i]); }
  nm=ns=invalid=accepts=mode=0;
  pthread_mutex_unlock(&lock);
}
void CancelMockSetMode(int32_t x) { pthread_mutex_lock(&lock); mode=x; pthread_mutex_unlock(&lock); }
int32_t SherpaOnnxMiniSightRuntimeIsCompatible(void) { return 1; }
const SherpaOnnxKeywordSpotter *SherpaOnnxCreateKeywordSpotter(const SherpaOnnxKeywordSpotterConfig *c) {
  assert(c && c->feat_config.sample_rate==16000 && c->feat_config.feature_dim==80);
  assert(c->model_config.num_threads==1 && !strcmp(c->model_config.provider,"cpu"));
  assert(c->keywords_buf && (int)strlen(c->keywords_buf)==c->keywords_buf_size);
  pthread_mutex_lock(&lock);
  assert(nm<64);
  SherpaOnnxKeywordSpotter *p=calloc(1,sizeof(*p)); assert(p);
  p->index=nm; models[nm++]=p;
  pthread_mutex_unlock(&lock);
  CancelFixtureConstructorBarrier(); /* pause INSIDE constructor, after allocation */
  return p;
}
const SherpaOnnxOnlineStream *SherpaOnnxCreateKeywordStream(const SherpaOnnxKeywordSpotter *p) {
  pthread_mutex_lock(&lock); assert(p && !p->destroyed);
  if (mode==1) { pthread_mutex_unlock(&lock); return NULL; }
  assert(ns<64);
  SherpaOnnxOnlineStream *s=calloc(1,sizeof(*s)); assert(s);
  s->index=ns; s->parent=p; streams[ns++]=s;
  pthread_mutex_unlock(&lock); return s;
}
void SherpaOnnxDestroyKeywordSpotter(const SherpaOnnxKeywordSpotter *p) {
  pthread_mutex_lock(&lock); int found=0;
  for(int i=0;i<nm;i++) if(models[i]==p) {
    found=1; if(p->destroyed) invalid++; models[i]->destroyed++;
    for(int j=0;j<ns;j++) if(streams[j]->parent==p && !streams[j]->destroyed) invalid++;
  }
  if(!found) invalid++;
  pthread_mutex_unlock(&lock);
}
void SherpaOnnxDestroyOnlineStream(const SherpaOnnxOnlineStream *p) {
  pthread_mutex_lock(&lock); int found=0;
  for(int i=0;i<ns;i++) if(streams[i]==p) {
    found=1; if(p->destroyed || p->parent->destroyed) invalid++; streams[i]->destroyed++;
  }
  if(!found) invalid++;
  pthread_mutex_unlock(&lock);
}
int32_t CancelMockCount(int32_t kind) { pthread_mutex_lock(&lock); int v=kind?ns:nm; pthread_mutex_unlock(&lock); return v; }
int32_t CancelMockDestroyed(int32_t kind,int32_t i) {
  pthread_mutex_lock(&lock); assert(i>=0 && i<(kind?ns:nm));
  int v=kind?streams[i]->destroyed:models[i]->destroyed; pthread_mutex_unlock(&lock); return v;
}
int32_t CancelMockInvalidDestroy(void) { pthread_mutex_lock(&lock); int v=invalid; pthread_mutex_unlock(&lock); return v; }
int32_t CancelMockAcceptCount(void) { pthread_mutex_lock(&lock); int v=accepts; pthread_mutex_unlock(&lock); return v; }
void SherpaOnnxOnlineStreamAcceptWaveform(const SherpaOnnxOnlineStream *p,int32_t rate,const float *samples,int32_t n) {
  pthread_mutex_lock(&lock); assert(p && !p->destroyed && !p->parent->destroyed && rate==16000 && samples && n>0); accepts++; pthread_mutex_unlock(&lock);
}
int32_t SherpaOnnxIsKeywordStreamReady(const SherpaOnnxKeywordSpotter *p,const SherpaOnnxOnlineStream *s) { (void)p; (void)s; return 0; }
void SherpaOnnxDecodeKeywordStream(const SherpaOnnxKeywordSpotter *p,const SherpaOnnxOnlineStream *s) { (void)p; (void)s; abort(); }
const SherpaOnnxKeywordResult *SherpaOnnxGetKeywordResult(const SherpaOnnxKeywordSpotter *p,const SherpaOnnxOnlineStream *s) { (void)p; (void)s; abort(); }
void SherpaOnnxDestroyKeywordResult(const SherpaOnnxKeywordResult *p) { (void)p; abort(); }
void SherpaOnnxResetKeywordStream(const SherpaOnnxKeywordSpotter *p,const SherpaOnnxOnlineStream *s) { (void)p; (void)s; abort(); }

#ifndef MINISIGHT_ASSET_FALLBACK_POLICY_H
#define MINISIGHT_ASSET_FALLBACK_POLICY_H
#include <stdbool.h>
/* Renderer recovery only, not permission to show or change the selected art. */
static inline bool MSAssetNeedsHostRebuild(bool resourceFresh, bool petStyle,
    bool hostBuilt, bool hasPet, bool hasAtlas) {
    return resourceFresh && petStyle && hostBuilt && !hasPet && hasAtlas;
}
#endif

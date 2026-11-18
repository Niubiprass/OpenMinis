// MiniSightLayout.h —— 宿主侧布局（纯 C，可被 tests/layout_test.c 直接编译验证）
//
// 核心约定：
//   * UIWindow 永远是整屏固定 frame，任何拖动/走动都只改子视图（宠物/胶囊/气泡）的
//     center，绝不改 window.center —— 窗口一旦被移出屏幕，子视图的“局部合法坐标”
//     换到屏幕坐标就是越界，之前 0.3.2 的越界就是这么来的。
//   * 宠物/胶囊的中心只能落在 centers 这个可行范围内；centers 由安全区 + 身体尺寸 +
//     气泡抬头空间一起算出，所以“看起来在屏幕上”和“气泡放得下”是同一个约束。
//   * 气泡永远在身体正上方；上方放不下时先让身体整体下移（仍在 centers 内），
//     绝不翻到脚下、也不硬夹到屏幕边缘去遮住身体。
#ifndef MINISIGHT_LAYOUT_H
#define MINISIGHT_LAYOUT_H
#include "MiniSightGeometry.h"

typedef struct {
    MSRect safe;      // 可用区域：屏幕去掉安全区 + 最小留白
    MSRect centers;   // 身体中心允许落点（已含气泡抬头空间与身体半径）
    MSSize body;      // 身体尺寸（宠物或胶囊）
    double gap;       // 气泡与身体顶部的间距
    double headroom;  // 为气泡预留的高度（不含 gap）
} MSLayout;

static inline MSLayout MSLayoutMake(double screenW, double screenH,
                                    double top, double bottom, double left, double right,
                                    double edge, double bodyW, double bodyH,
                                    double gap, double headroom) {
    MSLayout L;
    double e = fmax(0., MSFinite(edge, 0.));
    L.body = (MSSize){fmax(1., MSFinite(bodyW, 1.)), fmax(1., MSFinite(bodyH, 1.))};
    L.gap = fmax(0., MSFinite(gap, 0.));
    L.headroom = fmax(0., MSFinite(headroom, 0.));
    L.safe = MSSafeRect(screenW, screenH,
                        MSFinite(top, 0.) + e, MSFinite(bottom, 0.) + e,
                        MSFinite(left, 0.) + e, MSFinite(right, 0.) + e);
    L.centers = MSCenterBounds(L.safe, L.body, L.gap + L.headroom);
    return L;
}

/// 身体中心的合法化
static inline MSPoint MSLayoutClamp(MSLayout L, MSPoint p) {
    return MSClampCenter(L.centers, p);
}

/// 身体矩形（中心在 anchor）—— 只用于测试与尾巴定位
static inline MSRect MSLayoutBody(MSLayout L, MSPoint anchor) {
    return (MSRect){anchor.x - L.body.w * .5, anchor.y - L.body.h * .5, L.body.w, L.body.h};
}

/// 为气泡让位后的身体中心：放得下就原样；放不下就整体下移，仍夹在 centers 内。
/// 返回点保证身体不越界；气泡若因屏幕过矮仍放不下，由调用方按 safe 顶部处理。
static inline MSPoint MSLayoutAnchorForBubble(MSLayout L, MSPoint anchor, MSSize bubble) {
    MSPoint a = MSClampCenter(L.centers, anchor);
    double bh = fmax(0., MSFinite(bubble.h, 0.));
    double need = a.y - L.body.h * .5 - L.gap - bh;
    if (need < L.safe.y) {
        double want = L.safe.y + L.gap + bh + L.body.h * .5;
        a.y = MSClamp(want, L.centers.y, L.centers.y + L.centers.h);
    }
    return a;
}

/// Ordinary pet bubbles never push a freely dragged pet away from an edge.
/// Hide a bubble that cannot fit; approval prompts use the legacy relocation.
static inline int MSLayoutBubbleFits(MSLayout L, MSPoint anchor, MSRect box) {
    double top = anchor.y - L.body.h * .5;
    return isfinite(box.x) && isfinite(box.y) && isfinite(box.w) && isfinite(box.h) &&
        box.w > 0. && box.h > 0. && box.x >= L.safe.x && box.y >= L.safe.y &&
        box.x + box.w <= L.safe.x + L.safe.w + .001 &&
        box.y + box.h <= fmin(L.safe.y + L.safe.h, top - L.gap) + .001;
}

/// 气泡矩形：永远在身体上方，横向夹在 safe 内，尺寸上限为 safe
static inline MSRect MSLayoutBubble(MSLayout L, MSPoint anchor, MSSize bubble) {
    return MSBubbleAbove(L.safe, anchor, L.body, bubble, L.gap);
}

#endif

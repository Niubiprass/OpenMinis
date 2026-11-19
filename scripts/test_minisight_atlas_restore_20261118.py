#!/usr/bin/env python3
"""Portable source/mutation gates + literal production Pet excerpts for macOS CI.
No UIKit execution on iSH. --require-native delegates to the fail-closed effects
runner (11 original groups plus atlas groups and runtime mutations). No network.
"""
import argparse
from pathlib import Path
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent
METHODS = [
    '- (void)setImage:', '- (instancetype)initWithSprite:',
    '- (NSInteger)frameCountForRow:', '- (void)setVariantIndex:',
    '- (NSInteger)variantIndex', '- (void)setSpriteLayout:',
    '- (NSInteger)spriteLayout', '- (void)applySpriteFrame',
    '- (void)restorePosterFrame', '- (void)ensureGravityLayer',
    '- (void)updateGravityLayerGeometry', '- (NSString *)actionManifestPath',
    '- (void)setActionManifestPath:',
]


def core_path(root):
    core = root / 'src/ios/MiniSightCore'
    return core if core.is_dir() else root


def method(text, signature):
    # Definitions only; never pick the private forward declarations.
    start = re.search(r'^' + re.escape(signature) + r'[^\n]*\{', text, re.M)
    if not start:
        raise AssertionError('missing production method: ' + signature)
    opening = text.index('{', start.start())
    depth = 1
    i = opening + 1
    while depth:
        if text[i] == '{': depth += 1
        if text[i] == '}': depth -= 1
        i += 1
    return text[start.start():i]


def validate(pet, effects, header):
    assert '@dynamic image;' in pet, 'getter must remain inherited'
    assert not re.search(r'-\s*\(UIImage\s*\*\)\s*image\s*\{', pet), 'atlas getter reintroduced'
    assert '- (void)restorePosterFrame;' in header
    setter = method(pet, '- (void)setImage:')
    assert '_sheet == image' not in setter, 'same-image repair skipped'
    for body in (setter, method(pet, '- (void)restorePosterFrame')):
        assert '[super setImage:nil]' in body and 'self.layer.contents = nil' in body
        assert '_lastSpriteRect = CGRectNull' in body and '[self applySpriteFrame]' in body
    assert not re.search(r'contents\s*=.*(?:_sheet|image|poster)\.CGImage', pet), 'raw atlas published'
    crop = method(pet, '- (void)applySpriteFrame')
    assert 'CGImageCreateWithImageInRect(_sheet.CGImage, pixels)' in crop
    assert '_effects.hasActions' in crop and '_gravityLayer.contents' in crop
    assert 'BOOL actionPoster = effectiveLayout == 1 && _effects.actionManifestPath.length > 0;' in crop
    assert 'if (!actionPoster && effectiveLayout <= 1' in crop, 'action poster ratio damaged'
    assert '_lastSpriteRect = cell ? pixels : CGRectNull' in crop, 'failed crop cached'
    restore = method(effects, '- (void)restorePoster')
    assert '_ownsSprite = NO;' in restore and '[_pet restorePosterFrame];' in restore
    assert '_pet.image' not in effects and '_sprite.contents =' not in restore, 'driver owns raw poster'
    assert '[self restorePoster]' in method(effects, '- (void)setRunning:')
    assert '[self restorePoster]' in method(effects, '- (void)setActionManifestPath:')
    for signature in METHODS: method(pet, signature)


def mutations(pet, effects):
    # Each unsafe source is independently checked; production files are untouched.
    return {
        'getter': (pet.replace('@dynamic image;', '@dynamic image;\n- (UIImage *)image { return _sheet; }'), effects),
        'setter-whole-atlas': (pet.replace('_gravityLayer.contentsScale = image.scale;', '_gravityLayer.contentsScale = image.scale;\n    _gravityLayer.contents = (__bridge id)image.CGImage;'), effects),
        'same-image-early-return': (pet.replace('if (!image.CGImage) return;', 'if (!image.CGImage || _sheet == image) return;'), effects),
        'restore-cache-not-invalidated': (pet.replace(method(pet, '- (void)restorePosterFrame'), method(pet, '- (void)restorePosterFrame').replace('_lastSpriteRect = CGRectNull;', '')), effects),
        'poster-ratio-miscrop': (pet.replace('if (!actionPoster && effectiveLayout <= 1', 'if (effectiveLayout <= 1'), effects),
        'failed-crop-cached': (pet.replace('_lastSpriteRect = cell ? pixels : CGRectNull;', '_lastSpriteRect = pixels;'), effects),
        'driver-whole-atlas': (pet, effects.replace('[_pet restorePosterFrame];', '_sprite.contents = (__bridge id)_pet.image.CGImage;')),
        'stop-no-restore': (pet, effects.replace('[_library purgeFrames];\n        [self restorePoster];', '[_library purgeFrames];\n        _ownsSprite = NO;')),
        'swap-no-restore': (pet, effects.replace('[self restorePoster]; // Retire the previous clip even if the new manifest fails.', '// unsafe swap')),
    }


def excerpt(pet):
    # Only unrelated host wiring is shimmed. Every method under test is copied
    # verbatim at test execution from the current checkout, never a saved clone.
    state = re.search(r'typedef NS_ENUM\(NSInteger, MiniSightPetState\) \{.*?\};', pet, re.S).group(0)
    constants = '\n'.join(re.search(r'^static const NSInteger ' + name + r' = .*?;', pet, re.M).group(0)
                          for name in ('kMiniSightPetRows', 'kMiniSightPetMaxCols'))
    preamble = '#import "MiniSightPet.h"\n#import "MiniSightGeometry.h"\n#import "MiniSightLiveliness.h"\n' + state + '\n' + constants + '''
@interface MiniSightPetView () {
    UIImage *_sheet;
    CALayer *_gravityLayer;
    MiniSightPetEffects *_effects;
    MiniSightPetState _state;
    NSInteger _column, _spriteLayout, _variantIndex;
    CGRect _lastSpriteRect, _lastNotifiedBounds;
    CGPoint _lastNotifiedCenter;
    BOOL _longPressEnabled, _geometryReady;
    double _roamPace, _lastSpriteTime, _poseBegan;
    UILabel *_sleepBadge;
}
- (void)applySpriteFrame;
- (void)ensureGravityLayer;
- (void)updateGravityLayerGeometry;
- (NSInteger)frameCountForRow:(NSInteger)row;
- (void)windowVisibilityChanged:(NSNotification *)note;
@end
CGImageRef MSFixtureCrop(CGImageRef image, CGRect rect);
#define CGImageCreateWithImageInRect MSFixtureCrop
@implementation MiniSightPetView
@dynamic image;
'''
    # Do not mask a reintroduced production getter in native mutations.
    getter = re.search(r'^-\s*\(UIImage\s*\*\)\s*image\s*\{', pet, re.M)
    if getter:
        preamble += method(pet, getter.group(0).split('{')[0].rstrip()) + '\n'
    return preamble + '\n\n'.join(method(pet, s) for s in METHODS) + '''
// No notification dispatch, layout host, roaming or gesture emulation here.
- (void)windowVisibilityChanged:(NSNotification *)note { (void)note; }
@end
#undef CGImageCreateWithImageInRect
'''


def source_checks(core):
    pet = (core / 'MiniSightPet.m').read_text()
    effects = (core / 'MiniSightPetEffects.m').read_text()
    header = (core / 'MiniSightPet.h').read_text()
    validate(pet, effects, header)
    generated = excerpt(pet)
    for signature in METHODS:
        assert method(pet, signature) in generated
    for name, (bad_pet, bad_effects) in mutations(pet, effects).items():
        assert (bad_pet, bad_effects) != (pet, effects), name + ' mutation not applied'
        try:
            validate(bad_pet, bad_effects, header)
        except AssertionError:
            print('SOURCE NEGATIVE REJECT:', name)
        else:
            raise AssertionError(name + ' escaped source gate')
    fixture = HERE / 'fixtures/minisight_effects_runtime_20261116'
    runtime = (fixture / 'runtime.m').read_text()
    support = (fixture / 'support.h').read_text()
    assert '@interface MiniSightPetView' not in support, 'duplicate production Pet interface'
    assert '@implementation MiniSightPetView' not in runtime, 'handwritten Pet implementation in fixture'
    assert 'posterRestoreCount' not in runtime and 'pet = [UIImageView new]' not in runtime
    assert '#import "pet_atlas_excerpt.inc"' in runtime and '#import "atlas_cases.inc"' in runtime
    original = ['FirstFrame', 'ThreeBadFrames', 'SupersededRoleAndManifest', 'MissingDragAndChanged',
                'CancelAndVelocity', 'StopAndPurge', 'TapAndIdleAltFinish', 'DelayedTapFirstFrame',
                'ShortTapDoesNotLoop', 'BusyRetreat', 'LyricsOnly']
    atlas = ['AtlasLayouts', 'AtlasRepaintAndSameImage', 'AtlasCropFailureRetry',
             'AtlasActionPosterMetadata', 'AtlasEffectsFailureStop', 'AtlasManifestSwap']
    table = runtime.split('} tests[] = {', 1)[1].split('};', 1)[0]
    for name in original + atlas:
        assert ', ' + name + '}' in table, name + ' not registered'
    assert 'SameImage' in (fixture / 'atlas_cases.inc').read_text()
    print('PASS: 13 literal Pet methods, source contracts + 9 unsafe mutations, 11+6 native groups registered; NOT native/UIKit execution')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=HERE.parent)
    parser.add_argument('--require-native', action='store_true')
    args = parser.parse_args()
    try:
        source_checks(core_path(args.root.resolve()))
    except (AssertionError, OSError) as error:
        print('FAIL:', error, file=sys.stderr)
        return 1
    if args.require_native:
        return subprocess.call([sys.executable, str(HERE / 'test_minisight_effects_runtime_20261116.py'),
                                '--root', str(args.root), '--require-native'])
    print('SKIP: Apple native atlas behavior not requested; iSH source checks are not UIKit proof')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

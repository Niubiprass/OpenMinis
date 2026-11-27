#!/usr/bin/env python3
"""Offline: compile production continuity functions; native integration is separate."""
from pathlib import Path
import os
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / 'src/ios/MiniSightCore'
if not CORE.is_dir():
    CORE = ROOT
SOURCE = CORE / 'MiniSightMusicMonitor.m'


def function(s, name):
    pattern = r'static (?:bool|BOOL|NSUInteger) ' + name + r'\([^\{]+\{'
    match = re.search(pattern, s)
    if not match:
        raise AssertionError(name)
    start, n, i = match.start(), 1, match.end()
    while n:
        n += (s[i] == '{') - (s[i] == '}')
        i += 1
    return s[start:i]


def code(s):
    # Compile the actual production functions, replacing only ObjC field syntax
    # with synthetic C structs and exact string equality. No parallel policy model.
    body = '\n'.join(function(s, n) for n in ('MSMusicDurationCompatible',
        'MSMusicPendingContinuity', 'MSMusicTrackConflictMask',
        'MSMusicTracksCompatible', 'MSMusicTrackContinuity'))
    body = body.replace('MiniSightLyricsTrack *', 'Track *').replace('NSString *', 'const char *')
    for expr in ('firstID', 'lastID'):
        body = body.replace(expr+'.length', '('+expr+' && strlen('+expr+'))')
    body = re.sub(r'\[([A-Za-z]+)(?:\.([A-Za-z]+))? isEqualToString:([A-Za-z]+)(?:\.([A-Za-z]+))?\]',
        lambda m: 'eq('+m[1]+('->'+m[2] if m[2] else '')+','+m[3]+('->'+m[4] if m[4] else '')+')', body)
    body = re.sub(r'(firstTrack|lastTrack)\.(duration|title|artist|cacheKey)', r'\1->\2', body)
    return '''#include <stdbool.h>
#include <stddef.h>
#include <string.h>
#include <math.h>
#include <assert.h>
typedef bool BOOL;
typedef unsigned long NSUInteger;
#define YES true
#define NO false
typedef struct {const char *title,*artist,*cacheKey; double duration;} Track;
static bool eq(const char*a,const char*b){return a&&b&&!strcmp(a,b);}
''' + body + '''
int main(void){
 Track a={"Synthetic A","Artist","exact-261",261.};
 Track b={"Synthetic A","Artist","exact-261.2",261.2};
 assert(MSMusicTrackContinuity(&a,"id",&b,"id",false,true));
 assert(!MSMusicTrackContinuity(&a,"",&b,"",false,true));
 assert(!MSMusicTrackContinuity(&a,"id",&b,"other",false,true));
 assert(!MSMusicTrackContinuity(&a,"id",&b,"id",false,false));
 b.duration=262.; assert(MSMusicTrackContinuity(&a,"id",&b,"id",false,true));
 b.duration=262.00001; assert(!MSMusicTrackContinuity(&a,"id",&b,"id",false,true));
 b.duration=NAN; assert(!MSMusicTrackContinuity(&a,"id",&b,"id",false,true));
 b.duration=261.2; b.title="Other"; assert(!MSMusicTrackContinuity(&a,"id",&b,"id",false,true));
 b.title=a.title; b.artist="Other"; assert(!MSMusicTrackContinuity(&a,"id",&b,"id",false,true));
 assert(!MSMusicTrackContinuity(NULL,"id",&b,"id",false,true));
 b.artist=a.artist; b.duration=261.8;
 assert(MSMusicTrackContinuity(&a,"id",&b,"id",false,true));
 b.duration=262.6; assert(!MSMusicTrackContinuity(&a,"id",&b,"id",false,true));
 return 0;
}
'''


def run(s):
    with tempfile.TemporaryDirectory() as td:
        p = Path(td)
        (p/'test.c').write_text(code(s))
        build = subprocess.run([os.environ.get('CC','cc'),'-std=c11','-Wall','-Wextra','-Werror',str(p/'test.c'),'-lm','-o',str(p/'test')], capture_output=True)
        if build.returncode:
            raise AssertionError('C harness compile failed; NOT a rejected behavior: ' + build.stderr.decode(errors='replace'))
        return subprocess.run([str(p/'test')], capture_output=True).returncode


class PendingTests(unittest.TestCase):
    def test_actual_production_functions(self):
        self.assertEqual(run(SOURCE.read_text()), 0)

    def test_behavioral_mutations(self):
        s = SOURCE.read_text()
        for old, new in [('return fetching && sameKnownID;', 'return fetching || sameKnownID;'),
                         ('fabs(first - last) <= 1.0', 'fabs(first - last) <= 2.0'),
                         ('hasTimeline || pending', 'hasTimeline || pending || true')]:
            with self.subTest(mutation=old):
                self.assertEqual(s.count(old), 1)
                self.assertNotEqual(run(s.replace(old,new)), 0)

    def test_production_wiring_and_privacy(self):
        s = SOURCE.read_text()
        self.assertIn('firstTrack, MSMusicIdentifier(first), self->_timeline != nil, self->_fetching)',s)
        self.assertIn('track, identifier, self->_timeline != nil, self->_fetching)',s)
        self.assertIn('hasTimeline || pending',s)
        self.assertIn('mask &= 15u;',s)
        self.assertIn('now - _conflictAt < 60.',s)
        self.assertIn('[self conflictEvidence:MSMusicIdentityConflictMask(first, last) stage:3];',s)
        body=s.split('- (void)conflictEvidence:',1)[1].split('- (void)beginCandidate:',1)[0]
        self.assertNotIn('MSMusicIdentifier',body)
        self.assertNotIn('@"title"',body)

if __name__ == '__main__': unittest.main(verbosity=2)

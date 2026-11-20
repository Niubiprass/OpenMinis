#include "MiniSightLiveliness.h"
#include <assert.h>
#include <stdio.h>
#include <stdint.h>
static unsigned checks;
#define CHECK(x) do { assert(x); ++checks; } while (0)
int main(void) {
    MSPetDamped s = {0, 0}; double prior = 0;
    for (int i = 0; i < 180; ++i) {
        MSPetDampedStep(&s, 100, 1./60., 22.);
        CHECK(isfinite(s.value) && isfinite(s.velocity));
        CHECK(s.value >= prior - 1e-9 && s.value <= 100. + 1e-9);
        prior = s.value;
    }
    CHECK(fabs(s.value - 100.) < 1e-8);
    MSPetDamped a = {0, 0}, b = {0, 0};
    for (int i = 0; i < 60; ++i) MSPetDampedStep(&a, -30., 1./60., 20.);
    for (int i = 0; i < 30; ++i) MSPetDampedStep(&b, -30., 1./30., 20.);
    CHECK(fabs(a.value - b.value) < 1e-10 && fabs(a.velocity - b.velocity) < 1e-8);
    MSPetDampedStep(&a, 100., -1., 20.); CHECK(fabs(a.value - b.value) < 1e-10);
    a.value = NAN; a.velocity = INFINITY;
    MSPetDampedStep(&a, 7., 1./60., 20.); CHECK(a.value == 7. && a.velocity == 0.);
    uint32_t random = 1;
    for (int i = 0; i < 20000; ++i) {
        random = random * 1664525u + 1013904223u;
        double target = ((double)(random % 20001u) - 10000.) / 100.;
        double old = s.value;
        MSPetDampedStep(&s, target, 1./120., 22.);
        CHECK(isfinite(s.value) && isfinite(s.velocity) && fabs(s.value) <= 160.);
        CHECK(fabs(s.value - old) < 40.); // No instant target assignment during reversals.
    }
    double amplitude = 0.;
    for (int i = 0; i < 60; ++i) {
        double next = MSPetMusicAmplitude(amplitude, true, 1./60.);
        CHECK(next >= amplitude && next <= 1.); amplitude = next;
    }
    CHECK(amplitude > .93 && amplitude < 1.);
    for (int i = 0; i < 60; ++i) {
        double next = MSPetMusicAmplitude(amplitude, false, 1./60.);
        CHECK(next <= amplitude && next >= 0.); amplitude = next;
    }
    CHECK(amplitude < .02);
    double pulseAmplitude = 0.;
    for (int i = 0; i < 60; ++i) {
        double next = MSPetMusicAmplitude(pulseAmplitude, .35, 1./60.);
        CHECK(next >= pulseAmplitude && next <= .35); pulseAmplitude = next;
    }
    CHECK(pulseAmplitude > .34 && pulseAmplitude <= .35);
    for (int i = 0; i < 60; ++i) {
        double next = MSPetMusicAmplitude(pulseAmplitude, 0., 1./60.);
        CHECK(next <= pulseAmplitude && next >= 0.); pulseAmplitude = next;
    }
    CHECK(pulseAmplitude < .01);
    MSPetDragTrail trail = {0}; double vx, vy;
    CHECK(!MSPetReleaseVelocity(&trail, 1., &vx, &vy) && vx == 0 && vy == 0);
    for (int i = 0; i < 10; ++i) MSPetDragRemember(&trail, .01 * i, 600. * .01 * i, -300. * .01 * i);
    CHECK(MSPetReleaseVelocity(&trail, .09, &vx, &vy) && fabs(vx - 600.) < 1e-8 && fabs(vy + 300.) < 1e-8);
    CHECK(!MSPetReleaseVelocity(&trail, .3, &vx, &vy));
    CHECK(!MSPetReleaseVelocity(&trail, .205, &vx, &vy)); // Old release but still enough samples in window.
    CHECK(!MSPetReleaseVelocity(&trail, -.1, &vx, &vy));
    CHECK(!MSPetReleaseVelocity(&trail, .09, NULL, &vy));
    unsigned oldCount = trail.count;
    MSPetDragRemember(&trail, .09, 900, 900); MSPetDragRemember(&trail, NAN, 0, 0);
    CHECK(trail.count == oldCount);
    trail.count = 0;
    for (int i = 0; i < 10; ++i) MSPetDragRemember(&trail, .01 * i, 80. * .01 * i, 0);
    CHECK(!MSPetReleaseVelocity(&trail, .09, &vx, &vy));
    trail.count = 0;
    for (int i = 0; i < 10; ++i) MSPetDragRemember(&trail, .01 * i, 60000. * .01 * i, 0);
    CHECK(MSPetReleaseVelocity(&trail, .09, &vx, &vy));
    CHECK(hypot(vx, vy) <= 1800. + 1e-8);
    for (int i = 10; i < 1000; ++i) MSPetDragRemember(&trail, .01 * i, i, -i);
    CHECK(trail.count == 16);
    trail.count = 100; MSPetDragRemember(&trail, 100, 0, 0); CHECK(trail.count == 1);
    puts("PASS production damping, reversible targets, music envelope, recent release window and caps");
    printf("checks=%u\n", checks);
    return 0;
}

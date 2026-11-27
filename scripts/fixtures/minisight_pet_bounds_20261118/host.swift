import Foundation
import CoreGraphics

// Only UIKit hosting is stubbed. The method inserted at the marker below is
// the exact current production layoutSubviews, not a rewritten geometry rule.
class UIView {
    var bounds = CGRect.zero
    var safeAreaInsets = MSFixtureInsetsZero
    func layoutSubviews() {}
}
struct MSFixtureInsets { var top: CGFloat; var left: CGFloat; var bottom: CGFloat; var right: CGFloat }
let MSFixtureInsetsZero = MSFixtureInsets(top: 0, left: 0, bottom: 0, right: 0)
final class Pet {
    var gravitySafeSize = CGSize(width: 56, height: 61)
    var centerBounds = CGRect.zero
    var keyboardAvoidanceOccluded = false
    var isHidden = false
    private var point = CGPoint.zero
    var center: CGPoint {
        get { point }
        set {
            let p = MSClampCenter(MSRect(x: Double(centerBounds.minX), y: Double(centerBounds.minY),
                w: Double(centerBounds.width), h: Double(centerBounds.height)),
                MSPoint(x: Double(newValue.x), y: Double(newValue.y)))
            point = CGPoint(x: p.x, y: p.y)
        }
    }
}
func MSDiagEvent(_ category: String, _ event: String, _ result: String, _ fields: [String: Any]) {
    // Only the log sink is mocked; production geometry and visibility remain real.
}
final class Host: UIView {
    var localKeyboardFrame = CGRect.null
    var lastKeyboardState = 0
    weak var pet: Pet?
    var normalizedCenter = CGPoint(x: 0.5, y: 0.86)
    private var didPlaceInitialCenter = false
    // PRODUCTION_LAYOUT_METHOD
}
var count = 0
func check(_ ok: Bool, _ message: String) {
    count += 1
    if !ok { fputs("FAIL native host: \(message)\n", stderr); exit(1) }
}
func close(_ a: CGFloat, _ b: CGFloat) -> Bool { abs(a-b) < 0.000001 }
let host = Host(), pet = Pet()
host.pet = pet
host.bounds = CGRect(x: 0,y: 0,width: 390,height: 844)
host.safeAreaInsets = MSFixtureInsets(top: 47,left: 0,bottom: 34,right: 0)
host.normalizedCenter = CGPoint(x: 1,y: 0)
host.layoutSubviews()
check(close(pet.center.x,360) && close(pet.center.y,32.5), "first saved edge, no bubble reserve")
let before = pet.centerBounds
host.safeAreaInsets = MSFixtureInsets(top: 170,left: 100,bottom: 160,right: 110)
host.normalizedCenter = CGPoint(x: 0,y: 1)
host.layoutSubviews()
check(pet.centerBounds == before, "UI safe area cannot shrink movement")
check(close(pet.center.x,360) && close(pet.center.y,32.5), "no reapply stale saved center")
pet.center = CGPoint(x: 340,y: 770)
host.bounds = CGRect(x: 0,y: 0,width: 844,height: 390)
host.layoutSubviews()
check(close(pet.center.x,340) && close(pet.center.y,357.5), "rotate clamps actual center")
pet.gravitySafeSize = CGSize(width: 130,height: 140)
host.layoutSubviews()
check(close(pet.centerBounds.minX,67) && close(pet.centerBounds.minY,72), "gravity envelope retained")
check(close(pet.center.y,318), "resize retains complete body")
host.bounds = CGRect(x: 0,y: 0,width: 30,height: 20)
host.layoutSubviews()
check(pet.centerBounds.width==0 && pet.centerBounds.height==0, "small viewport collapses")
check(close(pet.center.x,15) && close(pet.center.y,10), "small viewport centered, not negative")
print("PASS native production layoutSubviews: \(count) host cases; UIKit/device not exercised")

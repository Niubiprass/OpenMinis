// Compiled with lexical production reader policy and exact token/evidence expressions.
var raw: [String: Any] = ["version":1,"time":1000.25,"allowed":true,"playing":true,
    "lyricsEnabled":false,"motionEnabled":true,"line":"","motionTime":12.5,
    "progressAvailable":true,"motionRate":1,"rhythmGeneration":7,"generation":99]
precondition(MiniSightMusicSnapshot.decode(raw)!.fresh(at:1005.25))
precondition(!MiniSightMusicSnapshot.decode(raw)!.fresh(at:1005.251))
precondition(read(raw,true).0 == 7 && read(raw,true).1)
precondition(!read(raw,false).1)
for bad in [false,1,"true",NSNull()] as [Any] {
    raw["progressAvailable"]=bad; precondition(!read(raw,true).1)
}
raw.removeValue(forKey:"progressAvailable"); precondition(!read(raw,true).1)
raw["progressAvailable"]=true
for bad in [2,true,"1",Double.nan,NSNull()] as [Any] {
    raw["motionRate"]=bad; precondition(!read(raw,true).1 && read(raw,true).0 == 7)
}
raw["motionRate"]=1
for bad in [true,"12",Double.nan,-1,NSNull()] as [Any] {
    raw["motionTime"]=bad; precondition(!read(raw,true).1)
}
raw["motionTime"]=12.5
for bad in [true,0,-1,1.5,Double.nan,Double.infinity,9_007_199_254_740_992.0,"7",NSNull()] as [Any] {
    raw["rhythmGeneration"]=bad; precondition(read(raw,true).0 == 0)
}
raw.removeValue(forKey:"rhythmGeneration"); precondition(read(raw,true).0 == 99)
raw["line"]="bad\nline"; precondition(MiniSightMusicSnapshot.decode(raw) == nil)
raw["line"]=""; raw["playing"]=1; precondition(MiniSightMusicSnapshot.decode(raw) == nil)
print("NATIVE PASS: lexical Swift v1 reader and independent token/position evidence")

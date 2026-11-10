# -*- coding: utf-8 -*-
"""screen_measure 纯算法函数最小自测（无 GUI）。"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import screen_measure as sm

ok = 0
fail = 0


def check(name, got, want, tol=1e-6):
    global ok, fail
    good = abs(got - want) <= tol
    if good:
        ok += 1
        print("  PASS %-28s got=%.6f want=%.6f" % (name, got, want))
    else:
        fail += 1
        print("  FAIL %-28s got=%.6f want=%.6f" % (name, got, want))


print("[1] 鞋带面积 (3-4-5 直角三角形 = 6)")
tri = [(0, 0), (4, 0), (0, 3)]
check("shoelace tri", sm.shoelace_area(tri), 6.0)
check("shoelace tri cm^2", sm.shoelace_area(tri) / (sm.DEFAULT_PX_PER_CM ** 2),
      6.0 / (sm.DEFAULT_PX_PER_CM ** 2))
# 单位正方形
check("shoelace unit sq", sm.shoelace_area([(0, 0), (1, 0), (1, 1), (0, 1)]), 1.0)

print("[2] Catmull-Rom 长度（共线锚点应等于直线长）")
col = [(0, 0), (30, 0), (60, 0), (90, 0)]
check("catmull collinear=90", sm.catmull_rom_length(col), 90.0, tol=1e-3)
check("polyline collinear=90", sm.polyline_length(col), 90.0)
# 弯曲曲线长度应 > 端点直线距离
curve = [(0, 0), (30, 40), (60, 0)]
cl = sm.catmull_rom_length(curve)
check("catmull curve>chord", 1.0 if cl > 60.0 else 0.0, 1.0, tol=0)
print("     curve length=%.3f (chord=60)" % cl)
# 闭合曲线：正方形四锚点，长度应接近周长(每边60=240)但样条略鼓
sq = [(0, 0), (60, 0), (60, 60), (0, 60)]
cl_sq = sm.catmull_rom_length(sq, closed=True)
print("     closed square spline=%.3f (ideal 240)" % cl_sq)
check("closed square >240", 1.0 if cl_sq > 240.0 else 0.0, 1.0, tol=0)

print("[3] 三点拟合圆")
c, r = sm.circle_from_3pts((0, 10), (10, 0), (0, -10))
check("circle center.x", c[0], 0.0, tol=1e-6)
check("circle center.y", c[1], 0.0, tol=1e-6)
check("circle r", r, 10.0, tol=1e-6)
# 共线 → None
check("circle collinear None",
      1.0 if sm.circle_from_3pts((0, 0), (1, 0), (2, 0)) is None else 0.0, 1.0, tol=0)

print("[4] 夹角")
check("angle 90", sm.angle_at((1, 0), (0, 0), (0, 1)), 90.0, tol=1e-6)
check("angle 180", sm.angle_at((-1, 0), (0, 0), (1, 0)), 180.0, tol=1e-6)
check("angle 45", sm.angle_at((1, 1), (0, 0), (1, 0)), 45.0, tol=1e-6)
check("angle 60", sm.angle_at((0.5, math.sqrt(3) / 2), (0, 0), (1, 0)), 60.0, tol=1e-6)

print("[5] 折线 merge（按端点最近贪心串接）")
segs = [
    [(0, 0), (10, 0)],       # A: (0,0)->(10,0)
    [(20, 0), (10, 0)],      # B: 尾(20,0) 接 A 头(10,0)，需反转 -> (10,0)->(20,0)
    [(30, 0), (20, 0)],      # C: 尾(30,0) 接 (20,0)，反转
]
merged, total = sm.merge_polylines(segs)
check("merge total len", total, 30.0)
check("merge start x", merged[0][0], 0.0)
check("merge end x", merged[-1][0], 30.0)
check("merge monotonic x",
      1.0 if all(merged[i][0] <= merged[i + 1][0] for i in range(len(merged) - 1)) else 0.0,
      1.0, tol=0)

print("[6] 单位换算")
check("to_cm", sm.to_cm(sm.DEFAULT_PX_PER_CM, sm.DEFAULT_PX_PER_CM), 1.0)
check("to_px", sm.to_px(1.0, sm.DEFAULT_PX_PER_CM), sm.DEFAULT_PX_PER_CM)

print("[7] 点到线段距离")
check("psd on seg", sm.point_seg_distance((5, 0), (0, 0), (10, 0))[0], 0.0)
check("psd perp", sm.point_seg_distance((5, 7), (0, 0), (10, 0))[0], 7.0)
check("psd beyond", sm.point_seg_distance((15, 0), (0, 0), (10, 0))[0], 5.0)

print("[8] 描边抽稀 smooth_stroke")
raw = [(i * 1.0, 0.0) for i in range(200)]   # 200px 直线
anc = sm.smooth_stroke(raw)
print("     raw=%d -> anchors=%d" % (len(raw), len(anc)))
check("anchor sparse", 1.0 if 2 <= len(anc) <= 12 else 0.0, 1.0, tol=0)
# 稀疏锚点样条长应接近原直线长 199
check("stroke spline~199", sm.catmull_rom_length(anc), 199.0, tol=6.0)

print("\n==== %d passed, %d failed ====" % (ok, fail))
sys.exit(1 if fail else 0)

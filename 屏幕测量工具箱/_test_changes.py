# -*- coding: utf-8 -*-
"""screen_measure.py 4 点改动的程序化测试。"""
import os, sys, math
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import screen_measure as sm
from PySide6.QtWidgets import QApplication, QMessageBox

app = QApplication.instance() or QApplication([])

results = []
def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(("[PASS] " if cond else "[FAIL] ") + name + ("  " + detail if detail else ""))

# ---------- ① 描边合并 merge_all_strokes ----------
from screen_measure import MeasureCanvas, catmull_rom_length, dist
c = MeasureCanvas()
c.set_mode("stroke", confirm=False)
c.strokes = [
    {"anchors": [(50.0, 50.0), (80.0, 60.0), (110.0, 55.0)], "closed": False},
    {"anchors": [(110.0, 55.0), (140.0, 80.0), (170.0, 90.0)], "closed": False},
    {"anchors": [(170.0, 90.0), (200.0, 120.0), (230.0, 125.0)], "closed": False},
]
before_total = c.stroke_total()
dense_cnt = sum(len(sm.catmull_rom_points(s["anchors"], s["closed"], 16)) for s in c.strokes)
total = c.merge_all_strokes()
check("strokes 合并为 1 条", len(c.strokes) == 1, "len=%d" % len(c.strokes))
new = c.strokes[0]
dense_new = sm.catmull_rom_points(new["anchors"], new["closed"], 16)
check("anchors 稀疏(远小于密集点)", len(new["anchors"]) < len(dense_new),
      "anchors=%d dense=%d" % (len(new["anchors"]), len(dense_new)))
gap = [dist(new["anchors"][i], new["anchors"][i+1]) for i in range(len(new["anchors"])-1)]
avg_gap = sum(gap)/len(gap) if gap else 0
check("每段间隔合理(~24px)", 10 <= avg_gap <= 40, "avg_gap=%.1f" % avg_gap)
l1 = catmull_rom_length(new["anchors"], new["closed"])
check("catmull_rom_length>0", l1 > 0, "len=%.2f" % l1)
check("合并后总长≈合并前(允许抽稀误差<8%)",
      abs(l1 - before_total) / before_total < 0.08,
      "before=%.2f after=%.2f" % (before_total, l1))
check("closed=False", new["closed"] is False)
check("返回 total 与重算一致", abs(total - l1) < 0.01)

# ---------- ② 模式切换确认框 ----------
c.set_mode("polyline", confirm=False)
c.polylines = [{"pts": [(10.0,10.0),(50.0,50.0)], "closed": False}]
orig_q = QMessageBox.question
# No -> 不切换
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.No)
c.set_mode("stroke")   # confirm 默认 True
check("确认框 No -> 不切换模式", c.mode == "polyline")
check("确认框 No -> 内容保留", len(c.polylines) == 1)
# Yes -> 切换并清空
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
c.set_mode("stroke")
check("确认框 Yes -> 切换模式", c.mode == "stroke")
check("确认框 Yes -> 清空内容", c.polylines == [])
check("切换后 measureState==draw", c.measureState == "draw")
# 空画布不弹窗直接切
c.set_mode("angle", confirm=True)
check("空画布切模式不弹窗直接切", c.mode == "angle" and c.angle is None)
# 相同模式不弹窗
c.set_mode("polyline", confirm=False)
c.polylines = [{"pts": [(1.0,1.0),(2.0,2.0)], "closed": False}]
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.No)
c.set_mode("polyline")   # 同模式
check("同模式不弹窗(仍polyline)", c.mode == "polyline")
QMessageBox.question = orig_q

# ---------- 直尺不因尺子弹窗 ----------
c.set_mode("ruler", confirm=False)   # 尺子常驻，has_content 应为 False
check("直尺模式不算有内容", c.has_content() is False)
c.strokes = [{"anchors":[(0.0,0.0),(10.0,10.0)],"closed":False}]
check("有描边时 has_content=True", c.has_content() is True)
c.strokes = []

# ---------- ③ 编辑态点别的模式干净回到 draw ----------
c.set_mode("stroke", confirm=False)
c.strokes = [{"anchors":[(0.0,0.0),(10.0,10.0),(20.0,5.0)],"closed":False}]
c.set_measure_state("edit")
check("进入编辑态", c.measureState == "edit")
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
c.set_mode("polyline")
check("编辑态切模式回到新模式的 draw 态", c.measureState == "draw", c.measureState)
check("编辑态切模式已清空描边", c.strokes == [])
QMessageBox.question = orig_q

# ---------- ④ 状态栏不绘制 ----------
c.set_mode("stroke", confirm=False)
c.strokes = [{"anchors":[(0.0,0.0),(10.0,10.0)],"closed":False}]
c.status = "SHOULD_NOT_APPEAR"
img = c.grab()
check("paintEvent 可正常渲染(状态行已移除)", img is not None and not img.isNull())
src = open(sm.__file__, encoding="utf-8").read()
check("_draw_overlay 不再 drawText(self.status)",
      "drawText(QPointF(12, self.height() - 12), self.status)" not in src)

# ---------- 主窗口可实例化 ----------
w = sm.MainWindow()
check("MainWindow 实例化成功", w.canvas is not None)
check("初始化后 measureState==draw", w.canvas.measureState == "draw")

print("\n=== %d/%d 通过 ===" % (sum(1 for _,ok,_ in results if ok), len(results)))
fails = [n for n,ok,_ in results if not ok]
if fails:
    print("FAILED:", fails); sys.exit(1)

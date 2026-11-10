# -*- coding: utf-8 -*-
"""
屏幕测量工具箱 (Screen Measure Toolbox)
单文件 PySide6 实现，严格对齐 SPEC.md (唯一接口契约)。

- 画布：单个 QWidget + QPainter，普通窗口内画布（无透明覆盖层/全局钩子，可截图可测量）
- 坐标：画布像素 px；长度 = px / pxPerCm
- 曲线：稀疏锚点 + Catmull-Rom 样条（绝不自动生成密集节点）

模块导入时不需要 Qt 的纯几何/算法函数放在文件前部，便于在无显示环境
下单独导入做数值自测。
"""
from __future__ import annotations

import json
import math
import os

# ----------------------------------------------------------------------------
# 常量（对齐 SPEC）
# ----------------------------------------------------------------------------
DEFAULT_PX_PER_CM = 37.8          # 96dpi
CARD_CM = 8.56                    # 银行卡短边 cm，用于校准
ANCHOR_PICK_R = 10.0              # 点到锚点/顶点命中半径
ENDPOINT_PICK_R = 12.0            # 尺子端点命中半径
BODY_PICK_R = 18.0                # 尺身线段命中半径
STROKE_ANCHOR_PX = 24.0           # 描边抽稀：每约 24px 取一个锚点
MIN_MOVE_PX = 2.0                 # 采样降频：移动 < 2px 不记录
MIN_POLY_PTS = 2                  # 折线最少点数
MIN_STROKE_PTS = 2                # 描边最少锚点数


def _config_path():
    """校准持久化文件路径。

    PyInstaller 单文件打包后 __file__ 指向临时解压目录(_MEIPASS)，
    该目录程序退出即销毁，配置会丢失，因此优先用「可执行文件所在目录」；
    源码运行时退回脚本所在目录。
    """
    import sys
    if getattr(sys, "frozen", False):          # PyInstaller 打包后为 True
        base = os.path.dirname(os.path.abspath(sys.executable))
    else:
        try:
            base = os.path.dirname(os.path.abspath(__file__))
        except NameError:
            base = os.getcwd()
    return os.path.join(base, "screen_measure_config.json")


# ----------------------------------------------------------------------------
# 纯算法函数（无 Qt 依赖，可独立自测）
# ----------------------------------------------------------------------------
def dist(a, b):
    """两点距离。"""
    return math.hypot(a[0] - b[0], a[1] - b[1])


def to_cm(px, pxPerCm):
    return px / pxPerCm


def to_px(cm, pxPerCm):
    return cm * pxPerCm


def polyline_length(pts):
    """折线长度 = Σ dist 相邻点。"""
    total = 0.0
    for i in range(1, len(pts)):
        total += dist(pts[i - 1], pts[i])
    return total


def shoelace_area(pts):
    """鞋带公式：多边形面积(px²)。返回绝对值。"""
    n = len(pts)
    if n < 3:
        return 0.0
    s = 0.0
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def angle_at(a, v, b):
    """夹角(度)：a-顶点(v)-b，acos(点积/(模积))。"""
    v1 = (a[0] - v[0], a[1] - v[1])
    v2 = (b[0] - v[0], b[1] - v[1])
    n1 = math.hypot(*v1)
    n2 = math.hypot(*v2)
    if n1 == 0 or n2 == 0:
        return 0.0
    c = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)))
    return math.degrees(math.acos(c))


def circle_from_3pts(p1, p2, p3):
    """三点拟合圆。返回 (center, r)；共线返回 None。"""
    ax, ay = p1
    bx, by = p2
    cx, cy = p3
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-9:
        return None
    ux = ((ax * ax + ay * ay) * (by - cy)
          + (bx * bx + by * by) * (cy - ay)
          + (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx)
          + (bx * bx + by * by) * (ax - cx)
          + (cx * cx + cy * cy) * (bx - ax)) / d
    center = (ux, uy)
    r = dist(center, p1)
    return center, r


def _cr_segment(p0, p1, p2, p3, t):
    """单段 Catmull-Rom：q(t)=0.5*((2p1)+(-p0+p2)t+(2p0-5p1+4p2-p3)t²+(-p0+3p1-3p2+p3)t³)"""
    t2 = t * t
    t3 = t2 * t
    x = 0.5 * ((2 * p1[0]) + (-p0[0] + p2[0]) * t
               + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2
               + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3)
    y = 0.5 * ((2 * p1[1]) + (-p0[1] + p2[1]) * t
               + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2
               + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3)
    return (x, y)


def catmull_rom_points(anchors, closed=False, samples_per_seg=16):
    """Catmull-Rom 样条采样。

    anchors: [(x,y), ...] 稀疏锚点
    closed:  闭合曲线首尾环绕取点；开口曲线端点用最近锚点补齐
    返回采样点列表（穿过所有锚点）。
    """
    pts = [tuple(map(float, p)) for p in anchors]
    n = len(pts)
    if n == 0:
        return []
    if n == 1:
        return [pts[0]]
    if n == 2:
        p0, p1, p2, p3 = pts[0], pts[0], pts[1], pts[1]
        return [_cr_segment(p0, p1, p2, p3, i / samples_per_seg)
                for i in range(samples_per_seg + 1)]

    segs = []
    if closed:
        for i in range(n):
            segs.append((pts[(i - 1) % n], pts[i], pts[(i + 1) % n], pts[(i + 2) % n]))
    else:
        for i in range(n - 1):
            p0 = pts[i - 1] if i - 1 >= 0 else pts[i]
            p1 = pts[i]
            p2 = pts[i + 1]
            p3 = pts[i + 2] if i + 2 < n else pts[i + 1]
            segs.append((p0, p1, p2, p3))

    out = []
    for p0, p1, p2, p3 in segs:
        for i in range(samples_per_seg):
            out.append(_cr_segment(p0, p1, p2, p3, i / samples_per_seg))
    out.append(pts[-1] if not closed else out[0])
    return out


def catmull_rom_length(anchors, closed=False, samples_per_seg=16):
    """曲线长度 = 对采样点逐段累加 Σ dist。"""
    return polyline_length(catmull_rom_points(anchors, closed, samples_per_seg))


def moving_average(pts, window=4):
    """滑动平均平滑：p[i] = mean(p[i-w .. i+w])。"""
    if len(pts) < 3:
        return list(pts)
    out = []
    n = len(pts)
    for i in range(n):
        lo = max(0, i - window)
        hi = min(n, i + window + 1)
        seg = pts[lo:hi]
        out.append((sum(p[0] for p in seg) / len(seg),
                    sum(p[1] for p in seg) / len(seg)))
    return out


def simplify_by_distance(pts, step=STROKE_ANCHOR_PX):
    """累积距离抽稀：沿轨迹每约 step px 保留一个锚点，强制保留首尾。"""
    if len(pts) <= 2:
        return list(pts)
    out = [pts[0]]
    acc = 0.0
    last = pts[0]
    for p in pts[1:]:
        d = dist(last, p)
        if d < MIN_MOVE_PX:          # 采样降频
            continue
        acc += d
        last = p                     # 累积距离沿整条轨迹累加
        if acc >= step:
            out.append(p)
            acc = 0.0
    if out[-1] != pts[-1]:
        out.append(pts[-1])
    return out


def smooth_stroke(raw_pts, step=STROKE_ANCHOR_PX, window=4):
    """描边一笔固化：平滑 + 抽稀成稀疏锚点。"""
    pts = [tuple(map(float, p)) for p in raw_pts]
    if len(pts) < 2:
        return pts
    pts = moving_average(pts, window)
    return simplify_by_distance(pts, step)


def point_seg_distance(p, a, b):
    """点到线段距离；投影参数 t=clamp((v·w)/(v·v),0,1)。返回 (d, t)。"""
    ax, ay = a
    vx, vy = b[0] - a[0], b[1] - a[1]
    wx, wy = p[0] - ax, p[1] - ay
    vv = vx * vx + vy * vy
    if vv == 0:
        return math.hypot(wx, wy), 0.0
    t = max(0.0, min(1.0, (wx * vx + wy * vy) / vv))
    cx, cy = ax + t * vx, ay + t * vy
    return math.hypot(p[0] - cx, p[1] - cy), t


def merge_polylines(polylines):
    """把多段连成一段：按端点最近原则贪心串接所有折线为一条。

    每步取未使用且端点距离当前尾部最近的那条，按距离决定正/反接。
    返回 (merged_pts, total_len)。
    """
    pool = [list(pl) for pl in polylines if len(pl) >= 2]
    if not pool:
        return [], 0.0
    merged = list(pool.pop(0))
    while pool:
        tail = merged[-1]
        best_i, best_d, best_rev = None, float("inf"), False
        for i, pl in enumerate(pool):
            d_head = dist(tail, pl[0])
            d_tail = dist(tail, pl[-1])
            if d_head < best_d:
                best_i, best_d, best_rev = i, d_head, False
            if d_tail < best_d:
                best_i, best_d, best_rev = i, d_tail, True
        pl = pool.pop(best_i)
        if best_rev:
            pl = list(reversed(pl))
        merged.extend(pl)
    return merged, polyline_length(merged)


def merge_point_lists(point_lists, samples_per_seg=16):
    """把多段密集点列表按端点最近原则贪心串接为一条（描边合并用）。

    先把每条列表用 Catmull-Rom 重采样成密集点（穿过原锚点），再仿
    merge_polylines 的贪心端点串接逻辑拼成一条密集点序列。
    返回 (merged_pts, total_len)。
    """
    dense = []
    for pts in point_lists:
        if len(pts) >= 2:
            dense.append(catmull_rom_points(pts, False, samples_per_seg))
        elif len(pts) == 1:
            dense.append([tuple(map(float, pts[0]))])
    pool = [list(d) for d in dense if len(d) >= 2]
    if not pool:
        return [], 0.0
    merged = list(pool.pop(0))
    while pool:
        tail = merged[-1]
        best_i, best_d, best_rev = None, float("inf"), False
        for i, d in enumerate(pool):
            d_head = dist(tail, d[0])
            d_tail = dist(tail, d[-1])
            if d_head < best_d:
                best_i, best_d, best_rev = i, d_head, False
            if d_tail < best_d:
                best_i, best_d, best_rev = i, d_tail, True
        d = pool.pop(best_i)
        if best_rev:
            d = list(reversed(d))
        merged.extend(d)
    return merged, polyline_length(merged)

# ----------------------------------------------------------------------------
# Qt 导入（仅 GUI 部分需要）
# ----------------------------------------------------------------------------
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import (QAction, QPainter, QPainterPath, QPen, QBrush,
                           QColor, QFont)
from PySide6.QtWidgets import (QApplication, QButtonGroup, QHBoxLayout, QLabel,
                               QMainWindow, QMenu, QMessageBox, QPushButton,
                               QSizePolicy, QSpinBox, QVBoxLayout, QWidget)

MODES = ["ruler", "polyline", "stroke", "angle", "area", "circle"]
MODE_LABELS = {
    "ruler": "直尺", "polyline": "折线", "stroke": "画笔描边",
    "angle": "角度", "area": "面积", "circle": "圆",
}

# 各模式使用说明（画布顶部横幅显示）
MODE_TIPS = {
    "ruler": "直尺：选中即生成；点空白处把<b>起点(左端)</b>放到该点 · 拖尺身平移 · 拖黄右端改长度 · 拖绿左端旋转；拖到与银行卡等长后右键→校准(8.56cm)。",
    "polyline": "折线：左键逐点点击，双击固化一条后接着点下一条；右键→编辑已有测量 / 把多段连成一段 / 清除。",
    "stroke": "描边：按住左键沿边缘画一笔，松手固化一条，可连续画多笔；右键→编辑已有测量（拖锚点改形 / 连成一段）。",
    "angle": "角度：依次点 边点 → 顶点 → 边点 三点；固化后拖动任一顶点改形，夹角实时刷新。",
    "area": "面积：左键逐点围多边形，双击闭合；用鞋带公式算出面积(cm²)。右键清除。",
    "circle": "圆：点圆上任意 3 个点（每点可见），自动拟合圆心并给出直径/半径/周长/面积。右键清除。",
}


# ----------------------------------------------------------------------------
# 主画布
# ----------------------------------------------------------------------------
class MeasureCanvas(QWidget):
    """单 QWidget 画布，承载全部模式的绘制与交互。"""

    def __init__(self, pxPerCm=DEFAULT_PX_PER_CM, parent=None):
        super().__init__(parent)
        self.setMinimumSize(600, 420)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

        # 全局状态（对齐 SPEC 第1节）
        self.pxPerCm = pxPerCm
        self.mode = "ruler"
        self.measureState = "draw"          # 'draw' | 'edit'（折线/描边用）

        # 测量对象（对齐 SPEC 第2节）
        self.polylines = []                  # [{pts:[(x,y)], closed:bool}]
        self.current = []                    # 折线绘制中 / 临时点
        self.strokes = []                    # [{anchors:[(x,y)], closed:bool}]
        self.angle = None                    # {'a','v','b'} 或采集中 {'pts':[]}
        self.area_pts = None                 # 已闭合多边形
        self.area_open = None                # 采集中
        self.circle = None                   # {'pts','center','r'}
        self.circle_open = None
        self.ruler = None                    # {'x','y','len','angle'}

        # 交互中间状态
        self._stroke_raw = None
        self.drag = None
        self._last = None
        self.hover_pt = None
        self.status = "左键操作；右键菜单切换 编辑/继续绘制。"

        self._ensure_ruler()
        self._load_config()

    # ---------------- 校准持久化 ----------------
    def _load_config(self):
        try:
            with open(_config_path(), "r", encoding="utf-8") as f:
                v = float(json.load(f).get("pxPerCm", DEFAULT_PX_PER_CM))
            if v > 0:
                self.pxPerCm = v
        except Exception:
            pass

    def save_config(self):
        try:
            with open(_config_path(), "w", encoding="utf-8") as f:
                json.dump({"pxPerCm": self.pxPerCm}, f)
        except Exception:
            pass

    def set_px_per_cm(self, v):
        if v and v > 0:
            self.pxPerCm = float(v)
            self.save_config()
            self.update()

    # ---------------- 直尺 ----------------
    def _ensure_ruler(self):
        if self.ruler is None:
            self.ruler = {"x": 80.0, "y": 80.0,
                          "len": to_px(CARD_CM, self.pxPerCm), "angle": 0.0}

    def ruler_endpoints(self):
        r = self.ruler
        return ((r["x"], r["y"]),
                (r["x"] + math.cos(r["angle"]) * r["len"],
                 r["y"] + math.sin(r["angle"]) * r["len"]))

    def hit_ruler(self, p):
        """返回 'right'(改长) / 'left'(旋转) / 'body'(平移) / None。"""
        if not self.ruler:
            return None
        a, b = self.ruler_endpoints()
        if dist(p, b) < ENDPOINT_PICK_R:
            return "right"
        if dist(p, a) < ENDPOINT_PICK_R:
            return "left"
        d, _ = point_seg_distance(p, a, b)
        if d < BODY_PICK_R:
            return "body"
        return None

    def calibrate_from_ruler(self):
        """用当前尺子长度对齐银行卡(8.56cm) → 反算 pxPerCm 并持久化。"""
        if not self.ruler:
            return 0.0
        v = self.ruler["len"] / CARD_CM
        if v > 0:
            self.pxPerCm = v
            self.save_config()
            self.update()
        return self.pxPerCm

    # ---------------- 命中测试（对齐 SPEC 第8节）----------------
    def _hit_angle_vertex(self, p, tol=12.0):
        """命中已固化角度的三个顶点，返回 'a'/'v'/'b'，否则 None。"""
        if not (self.angle and "a" in self.angle):
            return None
        for key in ("a", "v", "b"):
            if dist(p, self.angle[key]) <= tol:
                return key
        return None

    def hit_anchor(self, p):
        """编辑态命中锚点/顶点：返回 (kind, si, pi)，kind in polyline/stroke。"""
        for si, pl in enumerate(self.polylines):
            for pi, pt in enumerate(pl["pts"]):
                if dist(p, pt) < ANCHOR_PICK_R:
                    return ("polyline", si, pi)
        for si, st in enumerate(self.strokes):
            for pi, pt in enumerate(st["anchors"]):
                if dist(p, pt) < ANCHOR_PICK_R:
                    return ("stroke", si, pi)
        return None

    def hit_midpoint(self, p):
        """编辑态命中中点[+]：返回 (kind, si, pi)，表示在 pi 与 pi+1 之间插入。"""
        for si, pl in enumerate(self.polylines):
            pts = pl["pts"]
            for pi in range(len(pts) - 1):
                mid = ((pts[pi][0] + pts[pi + 1][0]) / 2,
                       (pts[pi][1] + pts[pi + 1][1]) / 2)
                if dist(p, mid) < ANCHOR_PICK_R:
                    return ("polyline", si, pi)
        for si, st in enumerate(self.strokes):
            pts = st["anchors"]
            for pi in range(len(pts) - 1):
                mid = ((pts[pi][0] + pts[pi + 1][0]) / 2,
                       (pts[pi][1] + pts[pi + 1][1]) / 2)
                if dist(p, mid) < ANCHOR_PICK_R:
                    return ("stroke", si, pi)
        return None

    def hit_object(self, p):
        """命中某一条折线/描边（用于删除命中的这一条）。返回 (kind, si) 或 None。"""
        best = (None, None, float("inf"))
        for si, pl in enumerate(self.polylines):
            pts = pl["pts"]
            for pi in range(len(pts) - 1):
                d, _ = point_seg_distance(p, pts[pi], pts[pi + 1])
                if d < best[2]:
                    best = ("polyline", si, d)
        for si, st in enumerate(self.strokes):
            samp = catmull_rom_points(st["anchors"], st["closed"])
            for pi in range(len(samp) - 1):
                d, _ = point_seg_distance(p, samp[pi], samp[pi + 1])
                if d < best[2]:
                    best = ("stroke", si, d)
        if best[2] < ANCHOR_PICK_R:
            return (best[0], best[1])
        return None

    # ---------------- 结果统计 ----------------
    def polyline_total(self):
        return sum(polyline_length(pl["pts"]) for pl in self.polylines)

    def stroke_total(self):
        return sum(catmull_rom_length(s["anchors"], s["closed"])
                   for s in self.strokes)

    # ---------------- 模式切换 ----------------
    def has_content(self):
        """画布是否"有内容"（切换模式时需清空并提示）。

        直尺尺子常驻，本身不算需要清空的内容。
        """
        return bool(self.polylines or self.current or self.strokes
                    or self.angle is not None or self.area_pts
                    or self.circle is not None)

    def _clear_all_measurements(self):
        """清空全部测量内容（模式切换-清空时用；直尺尺子常驻不清）。"""
        self.polylines = []
        self.strokes = []
        self.current = []
        self._stroke_raw = None
        self.angle = None
        self.area_pts = None
        self.area_open = None
        self.circle = None
        self.circle_open = None

    def set_mode(self, mode, confirm=True):
        if mode not in MODES:
            return
        if mode == self.mode:
            return
        self.mode = mode
        self.measureState = "draw"          # 任何模式切换后都回到绘制态（第3点）
        self.drag = None
        self.hover_pt = None
        # 切换模式时询问是否清空画布（第1点）：确定→清空；取消→保留内容
        if confirm and self.has_content():
            ret = QMessageBox.question(
                self, "切换模式",
                "是否清空当前画布内容？\n\n选择“Yes”清空后进入新模式；"
                "选择“No”保留现有测量并进入新模式。",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ret == QMessageBox.Yes:
                self._clear_all_measurements()
        else:
            self._clear_all_measurements()
        if mode == "ruler":
            self._ensure_ruler()
        self.status = MODE_LABELS[mode] + "：左键操作；右键菜单切换 编辑/继续绘制。"
        self.update()

    def set_measure_state(self, st):
        self.measureState = st
        self.update()

    # ---------------- 清除 / 删除 / 合并 ----------------
    def clear_current(self):
        if self.mode == "polyline":
            self.polylines = []
            self.current = []
        elif self.mode == "stroke":
            self.strokes = []
            self._stroke_raw = None
        elif self.mode == "angle":
            self.angle = None
        elif self.mode == "area":
            self.area_pts = None
            self.area_open = None
        elif self.mode == "circle":
            self.circle = None
            self.circle_open = None
        self.update()

    def delete_hit(self, hit):
        """删除命中的这一条（用命中对象索引删除）。"""
        if not hit:
            return
        kind, si = hit
        if kind == "polyline" and 0 <= si < len(self.polylines):
            self.polylines.pop(si)
        elif kind == "stroke" and 0 <= si < len(self.strokes):
            self.strokes.pop(si)
        self.update()

    def delete_anchor(self, p):
        """编辑态右键点锚点 → 删除该锚点（最少留2点）。"""
        a = self.hit_anchor(p)
        if not a:
            return
        kind, si, pi = a
        if kind == "polyline":
            if len(self.polylines[si]["pts"]) > MIN_POLY_PTS:
                self.polylines[si]["pts"].pop(pi)
        else:
            if len(self.strokes[si]["anchors"]) > MIN_STROKE_PTS:
                self.strokes[si]["anchors"].pop(pi)
        self.update()

    def merge_all(self):
        """把多段连成一段（按端点最近原则贪心串接）。"""
        merged, total = merge_polylines([pl["pts"] for pl in self.polylines])
        self.polylines = [{"pts": merged, "closed": False}]
        self.current = []
        self.status = "已把多段连成 1 段，总长 %.2f cm" % to_cm(total, self.pxPerCm)
        self.update()
        return total

    def merge_all_strokes(self):
        """把多条描边连成一条（重采样→端点贪心串接→重新抽稀成稀疏锚点）。"""
        if len(self.strokes) < 2:
            return 0.0
        dense, _ = merge_point_lists(
            [st["anchors"] for st in self.strokes], samples_per_seg=16)
        if len(dense) < 2:
            self.strokes = []
            self.update()
            return 0.0
        anchors = smooth_stroke(dense, STROKE_ANCHOR_PX)   # 抽稀成稀疏锚点
        if len(anchors) < MIN_STROKE_PTS:
            anchors = [dense[0], dense[-1]]
        self.strokes = [{"anchors": anchors, "closed": False}]
        self._stroke_raw = None
        total = catmull_rom_length(anchors, False)
        self.status = "已把多条描边连成 1 条，总长 %.2f cm" % to_cm(
            total, self.pxPerCm)
        self.update()
        return total

    def _insert_mid(self, mi):
        """在 pi 与 pi+1 中点插入锚点。"""
        kind, si, pi = mi
        pts = (self.polylines[si]["pts"] if kind == "polyline"
               else self.strokes[si]["anchors"])
        if pi + 1 >= len(pts):
            return
        a, b = pts[pi], pts[pi + 1]
        pts.insert(pi + 1, ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2))
        self.update()

    # ---------------- 鼠标事件 ----------------
    def mousePressEvent(self, e):
        p = (e.position().x(), e.position().y())
        if e.button() == Qt.LeftButton:
            self._on_left_press(p, e)
        elif e.button() == Qt.RightButton:
            self._on_right_press(p, e)

    def mouseMoveEvent(self, e):
        p = (e.position().x(), e.position().y())
        self.hover_pt = p
        if self.drag:
            self._on_drag_move(p)
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.drag:
            self._on_drag_release()

    def mouseDoubleClickEvent(self, e):
        p = (e.position().x(), e.position().y())
        self._on_double(p)

    # ---------------- 左键按下 ----------------
    def _on_left_press(self, p, e):
        m = self.mode
        if m == "ruler":
            h = self.hit_ruler(p)
            if h:
                self.drag = {"kind": "ruler", "what": h}
                self._last = p
            else:
                # 点空白：第一个点作为直尺起点（左端），保持原方向不变
                r = self.ruler
                r["x"], r["y"] = p
                self._update_ruler_status()
            return

        if m == "polyline":
            if self.measureState == "edit":
                a = self.hit_anchor(p)
                if a:
                    self.drag = {"kind": "anchor", "ref": a}
                else:
                    mi = self.hit_midpoint(p)
                    if mi:
                        self._insert_mid(mi)
                return
            self.current.append(p)          # draw 态：追加一个点到当前折线
            self.update()
            return

        if m == "stroke":
            if self.measureState == "edit":
                a = self.hit_anchor(p)
                if a:
                    self.drag = {"kind": "anchor", "ref": a}
                else:
                    mi = self.hit_midpoint(p)
                    if mi:
                        self._insert_mid(mi)
                return
            self._stroke_raw = [p]          # draw 态：按住画一笔
            self.drag = {"kind": "stroke_draw"}
            return

        if m == "angle":
            # 已固化的角度：左键点中三个顶点之一 → 拖动改形
            if self.angle and "a" in self.angle:
                key = self._hit_angle_vertex(p)
                if key:
                    self.drag = {"kind": "angle_vertex", "key": key}
                    return
            if self.angle is None or "a" in self.angle:
                self.angle = {"pts": []}
            self.angle["pts"].append(p)
            if len(self.angle["pts"]) == 3:
                a, v, b = self.angle["pts"]
                self.angle = {"a": a, "v": v, "b": b}
                self.status = "夹角 = %.2f°" % angle_at(a, v, b)
            else:
                self.status = "角度：已点 %d/3 点（边点→顶点→边点）" % len(self.angle["pts"])
            self.update()
            return

        if m == "area":
            if self.area_pts is not None:      # 已闭合，重新开始
                self.area_pts = None
            if self.area_open is None:
                self.area_open = []
            self.area_open.append(p)
            self.update()
            return

        if m == "circle":
            if self.circle is not None:
                self.circle = None
            if self.circle_open is None:
                self.circle_open = []
            self.circle_open.append(p)
            if len(self.circle_open) == 3:
                res = circle_from_3pts(*self.circle_open)
                if res:
                    c, r = res
                    self.circle = {"pts": list(self.circle_open),
                                   "center": c, "r": r}
                    self.status = ("圆：r=%.1fpx  直径=%.2fcm  周长=%.2fcm  面积=%.2fcm²"
                                   % (r, to_cm(2 * r, self.pxPerCm),
                                      to_cm(2 * math.pi * r, self.pxPerCm),
                                      math.pi * r * r / (self.pxPerCm ** 2)))
                    self.circle_open = None
                else:
                    self.status = "三点共线，无法拟合圆，请重选"
                    self.circle_open = []
            else:
                self.status = "圆：已点 %d/3 点" % len(self.circle_open)
            self.update()
            return

    # ---------------- 拖动移动 ----------------
    def _on_drag_move(self, p):
        d = self.drag
        if d["kind"] == "ruler":
            r = self.ruler
            if d["what"] == "body":
                dx = p[0] - self._last[0]
                dy = p[1] - self._last[1]
                r["x"] += dx
                r["y"] += dy
                self._last = p
            elif d["what"] == "right":
                r["len"] = max(20.0, dist((r["x"], r["y"]), p))
            elif d["what"] == "left":
                _, b = self.ruler_endpoints()
                r["angle"] = math.atan2(p[1] - b[1], p[0] - b[0])
            self._update_ruler_status()
            return
        if d["kind"] == "anchor":
            kind, si, pi = d["ref"]
            if kind == "polyline":
                self.polylines[si]["pts"][pi] = p
            else:
                self.strokes[si]["anchors"][pi] = p
            return
        if d["kind"] == "angle_vertex":
            self.angle[d["key"]] = p          # 拖动顶点改形，夹角实时刷新
            self.update()
            return
        if d["kind"] == "stroke_draw":
            if self._stroke_raw and dist(self._stroke_raw[-1], p) >= MIN_MOVE_PX:
                self._stroke_raw.append(p)

    def _on_drag_release(self):
        d = self.drag
        self.drag = None
        self._last = None
        if d["kind"] == "stroke_draw" and self._stroke_raw:
            anchors = smooth_stroke(self._stroke_raw)
            if len(anchors) >= MIN_STROKE_PTS:
                self.strokes.append({"anchors": anchors, "closed": False})
                self.status = "描边固化：%d 锚点，长 %.2f cm" % (
                    len(anchors),
                    to_cm(catmull_rom_length(anchors), self.pxPerCm))
            self._stroke_raw = None
            self.update()

    def _update_ruler_status(self):
        a, b = self.ruler_endpoints()
        L = dist(a, b)
        self.status = "直尺：长 %.2f cm (%.0f px)，角度 %.1f°" % (
            to_cm(L, self.pxPerCm), L, math.degrees(self.ruler["angle"]))

    # ---------------- 双击 ----------------
    def _on_double(self, p):
        m = self.mode
        if m == "polyline":
            if self.measureState == "draw":
                # 固化当前折线，接着点是下一条新折线
                if len(self.current) >= MIN_POLY_PTS:
                    self.polylines.append({"pts": list(self.current), "closed": False})
                self.current = []
                self.status = "已固化一条折线，接着点是下一条"
                self.update()
            return
        if m == "stroke":
            if self.measureState == "edit":
                hit = self.hit_object(p)
                if hit and hit[0] == "stroke":
                    st = self.strokes[hit[1]]
                    st["closed"] = not st["closed"]     # 切换 闭合/开口
                    self.update()
            return
        if m == "area":
            if self.area_open and len(self.area_open) >= 3:
                self.area_pts = list(self.area_open)     # 双击闭合
                self.area_open = None
                s_px = shoelace_area(self.area_pts)
                self.status = "面积 = %.2f cm²" % (s_px / (self.pxPerCm ** 2))
                self.update()
            return

    # ---------------- 右键菜单（对齐 SPEC 第10节）----------------
    def _on_right_press(self, p, e):
        menu = QMenu(self)
        m = self.mode
        if m in ("polyline", "stroke"):
            if self.measureState == "draw":
                menu.addAction("编辑已有测量", self._enter_edit)
                if m == "polyline" and len(self.polylines) >= 2:
                    menu.addAction("把多段连成一段", self.merge_all)
                if m == "stroke" and len(self.strokes) >= 2:
                    menu.addAction("把多段连成一段", self.merge_all_strokes)
                menu.addAction("清除当前", self.clear_current)
            else:  # edit
                menu.addAction("继续绘制", lambda: self.set_measure_state("draw"))
                if self.hit_anchor(p):
                    menu.addAction("删除该锚点", lambda: self.delete_anchor(p))
                if m == "polyline" and len(self.polylines) >= 2:
                    menu.addAction("把多段连成一段", self.merge_all)
                if m == "stroke" and len(self.strokes) >= 2:
                    menu.addAction("把多段连成一段", self.merge_all_strokes)
                hit = self.hit_object(p)
                if hit:
                    menu.addAction("删除命中的这一条",
                                   lambda h=hit: self.delete_hit(h))
                menu.addAction("清除全部", self.clear_current)
        elif m in ("angle", "area", "circle"):
            menu.addAction("清除当前测量", self.clear_current)
        elif m == "ruler":
            menu.addAction("校准：用当前尺子对齐银行卡(8.56cm)",
                           self.calibrate_from_ruler)
            menu.addAction("重置尺子", self._reset_ruler)
        if menu.actions():
            menu.exec(e.globalPosition().toPoint())

    def _enter_edit(self):
        self.measureState = "edit"
        self.current = []
        self.status = "编辑态：拖锚点改形 / 中点[+]插点 / 右键删锚点 / 右键空白换菜单"
        self.update()

    def _reset_ruler(self):
        self.ruler = None
        self._ensure_ruler()
        self.update()

    # ---------------- 绘制 ----------------
    def paintEvent(self, ev):
        qp = QPainter(self)
        qp.setRenderHint(QPainter.Antialiasing)
        qp.fillRect(self.rect(), QColor(30, 32, 38))
        self._draw_grid(qp)
        if self.ruler and self.mode == "ruler":
            self._draw_ruler(qp)
        self._draw_polylines(qp)
        self._draw_strokes(qp)
        self._draw_angle(qp)
        self._draw_area(qp)
        self._draw_circle(qp)
        self._draw_edit_guides(qp)
        self._draw_overlay(qp)
        qp.end()

    def _draw_grid(self, qp):
        pen = QPen(QColor(44, 48, 56), 1)
        qp.setPen(pen)
        step = self.pxPerCm
        w, h = self.width(), self.height()
        x = step
        while x < w:
            qp.drawLine(QPointF(x, 0), QPointF(x, h))
            x += step
        y = step
        while y < h:
            qp.drawLine(QPointF(0, y), QPointF(w, y))
            y += step

    def _dot(self, qp, p, color, r=4):
        qp.setBrush(QBrush(QColor(color)))
        qp.setPen(Qt.NoPen)
        qp.drawEllipse(QPointF(p[0], p[1]), r, r)

    def _draw_ruler(self, qp):
        r = self.ruler
        a, b = self.ruler_endpoints()
        ang = r["angle"]
        L = dist(a, b)
        body_h = 26
        qp.save()
        qp.translate(QPointF(a[0], a[1]))
        qp.rotate(math.degrees(ang))
        qp.setPen(QPen(QColor(235, 235, 240), 1.5))
        qp.setBrush(QBrush(QColor(210, 215, 225, 235)))
        qp.drawRect(QRectF(0, -body_h, L, body_h))
        # mm/cm 刻度（校准后自动重排）
        mm = self.pxPerCm / 10.0
        qp.setPen(QPen(QColor(40, 40, 45), 1))
        f = QFont()
        f.setPointSize(7)
        qp.setFont(f)
        n = int(L / mm)
        for i in range(1, n + 1):
            x = i * mm
            if x > L:
                break
            if i % 10 == 0:
                qp.drawLine(QPointF(x, -body_h), QPointF(x, -body_h + 16))
                qp.drawText(QPointF(x - 3, -body_h + 25), str(i // 10))
            elif i % 5 == 0:
                qp.drawLine(QPointF(x, -body_h), QPointF(x, -body_h + 10))
            else:
                qp.drawLine(QPointF(x, -body_h), QPointF(x, -body_h + 6))
        qp.restore()
        # 黄色右端块（改长）
        qp.setPen(QPen(QColor(120, 90, 0), 1.5))
        qp.setBrush(QBrush(QColor(255, 210, 0)))
        qp.drawRect(QRectF(b[0] - 6, b[1] - 6, 12, 12))
        # 绿色左端圆点（旋转）
        self._dot(qp, a, "#31c48d", 6)

    def _draw_polylines(self, qp):
        for pl in self.polylines:
            pts = pl["pts"]
            if len(pts) < 2:
                continue
            qp.setPen(QPen(QColor(80, 170, 255), 2))
            qp.setBrush(Qt.NoBrush)
            path = QPainterPath(QPointF(*pts[0]))
            for pt in pts[1:]:
                path.lineTo(QPointF(*pt))
            qp.drawPath(path)
            for pt in pts:
                self._dot(qp, pt, "#8ecbff", 3)
        if self.mode == "polyline" and len(self.current) >= 1:
            qp.setPen(QPen(QColor(80, 170, 255, 180), 2, Qt.DashLine))
            qp.setBrush(Qt.NoBrush)
            path = QPainterPath(QPointF(*self.current[0]))
            for pt in self.current[1:]:
                path.lineTo(QPointF(*pt))
            qp.drawPath(path)
            for pt in self.current:
                self._dot(qp, pt, "#8ecbff", 3)
            if self.hover_pt:
                qp.setPen(QPen(QColor(80, 170, 255, 90), 1.5, Qt.DotLine))
                qp.drawLine(QPointF(*self.current[-1]), QPointF(*self.hover_pt))

    def _draw_strokes(self, qp):
        for st in self.strokes:
            pts = catmull_rom_points(st["anchors"], st["closed"])
            if len(pts) < 2:
                continue
            qp.setPen(QPen(QColor(255, 150, 80), 2.5))
            qp.setBrush(Qt.NoBrush)
            path = QPainterPath(QPointF(*pts[0]))
            for pt in pts[1:]:
                path.lineTo(QPointF(*pt))
            qp.drawPath(path)
            if self.measureState == "edit":
                for an in st["anchors"]:        # 方形锚点
                    qp.setBrush(QBrush(QColor(255, 200, 60)))
                    qp.setPen(QPen(QColor(120, 90, 0), 1))
                    qp.drawRect(QRectF(an[0] - 4, an[1] - 4, 8, 8))
        # 正在画的一笔（原始轨迹预览）
        if self.mode == "stroke" and self._stroke_raw and len(self._stroke_raw) > 1:
            qp.setPen(QPen(QColor(255, 150, 80, 150), 2))
            qp.setBrush(Qt.NoBrush)
            path = QPainterPath(QPointF(*self._stroke_raw[0]))
            for pt in self._stroke_raw[1:]:
                path.lineTo(QPointF(*pt))
            qp.drawPath(path)

    def _draw_angle(self, qp):
        an = self.angle
        if not an:
            return
        if "pts" in an:                            # 采集中
            for pt in an["pts"]:
                self._dot(qp, pt, "#ffd166", 4)
            return
        a, v, b = an["a"], an["v"], an["b"]
        qp.setPen(QPen(QColor(255, 209, 102), 2))
        qp.setBrush(Qt.NoBrush)
        qp.drawLine(QPointF(*a), QPointF(*v))
        qp.drawLine(QPointF(*v), QPointF(*b))
        # 三个顶点画成可拖动手柄：空心环（提示可点住改形）
        for pt in (a, v, b):
            qp.setPen(QPen(QColor(255, 209, 102), 2))
            qp.setBrush(QBrush(QColor(255, 209, 102, 60)))
            qp.drawEllipse(QPointF(*pt), 6, 6)
        # 弧线标注
        r = 32
        a1 = math.atan2(a[1] - v[1], a[0] - v[0])
        a2 = math.atan2(b[1] - v[1], b[0] - v[0])
        qp.drawArc(QRectF(v[0] - r, v[1] - r, 2 * r, 2 * r),
                   int(a1 * 180 / math.pi * 16),
                   int(((a2 - a1 + math.pi) % (2 * math.pi) - math.pi) * 180 / math.pi * 16))

    def _draw_area(self, qp):
        pts = self.area_pts or self.area_open
        if not pts or len(pts) < 2:
            if pts:
                for pt in pts:
                    self._dot(qp, pt, "#6ee7b7", 4)
            return
        closed = self.area_pts is not None
        poly = QPolygonF([QPointF(*pt) for pt in pts])
        if closed:
            qp.setBrush(QBrush(QColor(110, 231, 183, 60)))
            qp.setPen(QPen(QColor(110, 231, 183), 2))
            qp.drawPolygon(poly)
        else:
            qp.setBrush(Qt.NoBrush)
            qp.setPen(QPen(QColor(110, 231, 183), 2, Qt.DashLine))
            qp.drawPolyline(poly)
            if self.hover_pt:
                qp.setPen(QPen(QColor(110, 231, 183, 90), 1.5, Qt.DotLine))
                qp.drawLine(QPointF(*pts[-1]), QPointF(*self.hover_pt))
        for pt in pts:
            self._dot(qp, pt, "#6ee7b7", 4)

    def _draw_circle(self, qp):
        if self.circle_open:
            for pt in self.circle_open:
                self._dot(qp, pt, "#c084fc", 4)
            return
        c = self.circle
        if not c:
            return
        cx, cy = c["center"]
        r = c["r"]
        qp.setBrush(Qt.NoBrush)
        qp.setPen(QPen(QColor(192, 132, 252), 2))
        qp.drawEllipse(QPointF(cx, cy), r, r)
        for pt in c["pts"]:
            self._dot(qp, pt, "#c084fc", 4)
        self._dot(qp, (cx, cy), "#e9d5ff", 3)

    def _draw_edit_guides(self, qp):
        """编辑态在折线/描边中点画 [+] 标记。"""
        if self.measureState != "edit":
            return
        qp.setPen(QPen(QColor(255, 255, 255, 120), 1))
        qp.setBrush(QBrush(QColor(255, 255, 255, 40)))
        for pl in self.polylines:
            pts = pl["pts"]
            for i in range(len(pts) - 1):
                mx = (pts[i][0] + pts[i + 1][0]) / 2
                my = (pts[i][1] + pts[i + 1][1]) / 2
                qp.drawLine(QPointF(mx - 4, my), QPointF(mx + 4, my))
                qp.drawLine(QPointF(mx, my - 4), QPointF(mx, my + 4))
        for st in self.strokes:
            pts = st["anchors"]
            for i in range(len(pts) - 1):
                mx = (pts[i][0] + pts[i + 1][0]) / 2
                my = (pts[i][1] + pts[i + 1][1]) / 2
                qp.drawLine(QPointF(mx - 4, my), QPointF(mx + 4, my))
                qp.drawLine(QPointF(mx, my - 4), QPointF(mx, my + 4))

    def _draw_overlay(self, qp):
        f = QFont()
        f.setPointSize(9)
        qp.setFont(f)
        # 顶部：当前模式使用说明横幅
        tip = MODE_TIPS.get(self.mode, "")
        if tip:
            label = MODE_LABELS.get(self.mode, "") + " · " + tip
            fm = qp.fontMetrics()
            tw = fm.horizontalAdvance(label)
            qp.fillRect(8, 8, tw + 20, 26, QColor(0, 0, 0, 110))
            qp.setPen(QPen(QColor(255, 255, 255, 60)))
            qp.drawRect(8, 8, tw + 20, 26)
            qp.setPen(QColor(230, 235, 245))
            qp.drawText(QPointF(18, 25), label)
        # 右下累计总长与逐条长度（左下角状态行已移除，状态仅在侧栏/菜单体现）
        lines = self._result_lines()
        y = self.height() - 12
        qp.setPen(QPen(QColor(255, 255, 255, 230)))
        for ln in reversed(lines):
            qp.drawText(QPointF(self.width() - 12 - 220, y), ln)
            y -= 16

    def _result_lines(self):
        out = []
        if self.mode == "polyline":
            tot = self.polyline_total()
            out.append("折线累计总长: %.2f cm" % to_cm(tot, self.pxPerCm))
            for i, pl in enumerate(self.polylines):
                out.append("  #%d: %.2f cm (%d点)" % (
                    i + 1, to_cm(polyline_length(pl["pts"]), self.pxPerCm),
                    len(pl["pts"])))
            if len(self.current) >= 2:
                out.append("  当前: %.2f cm" % to_cm(
                    polyline_length(self.current), self.pxPerCm))
        elif self.mode == "stroke":
            tot = self.stroke_total()
            out.append("描边累计总长: %.2f cm" % to_cm(tot, self.pxPerCm))
            for i, st in enumerate(self.strokes):
                out.append("  #%d: %.2f cm (%d锚点%s)" % (
                    i + 1, to_cm(catmull_rom_length(st["anchors"], st["closed"]),
                                 self.pxPerCm), len(st["anchors"]),
                    "/闭合" if st["closed"] else ""))
        elif self.mode == "angle" and self.angle and "a" in self.angle:
            out.append("夹角: %.2f°" % angle_at(self.angle["a"],
                                                self.angle["v"], self.angle["b"]))
        elif self.mode == "area" and self.area_pts:
            s = shoelace_area(self.area_pts) / (self.pxPerCm ** 2)
            out.append("面积: %.2f cm²" % s)
        elif self.mode == "circle" and self.circle:
            r = self.circle["r"]
            out.append("圆: 直径%.2fcm 半径%.2fcm 周长%.2fcm 面积%.2fcm²" % (
                to_cm(2 * r, self.pxPerCm), to_cm(r, self.pxPerCm),
                to_cm(2 * math.pi * r, self.pxPerCm),
                math.pi * r * r / (self.pxPerCm ** 2)))
        elif self.mode == "ruler":
            a, b = self.ruler_endpoints()
            L = dist(a, b)
            out.append("直尺: %.2f cm / %.0f px  %.1f°" % (
                to_cm(L, self.pxPerCm), L, math.degrees(self.ruler["angle"])))
        return out

# ----------------------------------------------------------------------------
# 主窗口：左侧模式栏 + DPI 校准区
# ----------------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("屏幕测量工具箱")
        self.resize(1100, 720)

        self.canvas = MeasureCanvas()
        self.setCentralWidget(self._build_ui())

    def _build_ui(self):
        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 左侧模式栏
        side = QWidget()
        side.setFixedWidth(190)
        side.setStyleSheet("background:#1b1d23;")
        sv = QVBoxLayout(side)
        sv.setContentsMargins(12, 14, 12, 14)
        sv.setSpacing(8)

        title = QLabel("屏幕测量工具箱")
        title.setStyleSheet("color:#fff;font-weight:bold;font-size:14px;")
        sv.addWidget(title)

        self.mode_group = QButtonGroup(self)
        self._mode_buttons = {}
        for m in MODES:
            b = QPushButton(MODE_LABELS[m])
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(self._btn_qss())
            b.clicked.connect(lambda _=False, mm=m: self._on_mode(mm))
            self.mode_group.addButton(b)
            self._mode_buttons[m] = b
            sv.addWidget(b)
        self._mode_buttons["ruler"].setChecked(True)

        sv.addSpacing(10)
        calib = QLabel("DPI 校准")
        calib.setStyleSheet("color:#9aa0ab;font-size:11px;")
        sv.addWidget(calib)

        self.spin = QSpinBox()
        self.spin.setRange(5, 400)
        self.spin.setValue(int(round(self.canvas.pxPerCm)))
        self.spin.setSuffix(" px/cm")
        self.spin.valueChanged.connect(self.canvas.set_px_per_cm)
        sv.addWidget(self.spin)

        cal = QPushButton("用尺子校准(银行卡8.56cm)")
        cal.setCursor(Qt.PointingHandCursor)
        cal.setStyleSheet(self._btn_qss())
        cal.clicked.connect(self._on_calibrate)
        sv.addWidget(cal)

        self.pxlabel = QLabel()
        self.pxlabel.setStyleSheet("color:#9aa0ab;font-size:11px;")
        sv.addWidget(self.pxlabel)

        sv.addStretch(1)
        hint = QLabel("折线/描边右键切换\n编辑 / 继续绘制")
        hint.setStyleSheet("color:#6b7280;font-size:10px;")
        sv.addWidget(hint)

        root.addWidget(side)

        # 画布容器
        wrapper = QWidget()
        wv = QVBoxLayout(wrapper)
        wv.setContentsMargins(0, 0, 0, 0)
        wv.addWidget(self.canvas)
        root.addWidget(wrapper, 1)

        self._refresh_pxlabel()
        # 初始化首次设置模式：不弹确认框（画布尚无内容）
        self.canvas.set_mode("ruler", confirm=False)
        self._mode_buttons["ruler"].setChecked(True)
        return central

    def _btn_qss(self):
        return ("QPushButton{color:#d7dae0;background:#262a33;border:1px solid #333;"
                "border-radius:6px;padding:8px;text-align:left;}"
                "QPushButton:hover{background:#2f3440;}"
                "QPushButton:checked{background:#2b6cb0;color:#fff;border-color:#3182ce;}")

    def _on_mode(self, m):
        self.canvas.set_mode(m)
        # 若用户在确认框选 No 未切换，回同步按钮选中态到实际模式
        cur = self.canvas.mode
        for mm, b in self._mode_buttons.items():
            b.setChecked(mm == cur)

    def _on_calibrate(self):
        v = self.canvas.calibrate_from_ruler()
        self.spin.blockSignals(True)
        self.spin.setValue(int(round(v)))
        self.spin.blockSignals(False)
        self._refresh_pxlabel()

    def _refresh_pxlabel(self):
        self.pxlabel.setText("1cm = %.1f px" % self.canvas.pxPerCm)


def main():
    import sys
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

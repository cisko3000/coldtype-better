import math
from enum import Enum
from fontTools.pens.filterPen import ContourFilterPen
from fontTools.pens.reverseContourPen import ReverseContourPen
from fontTools.pens.boundsPen import ControlBoundsPen, BoundsPen
from fontTools.pens.recordingPen import RecordingPen
from fontTools.pens.pointPen import SegmentToPointPen, PointToSegmentPen, AbstractPointPen
from fontTools.pens.pointInsidePen import PointInsidePen
from fontTools.svgLib.path.parser import parse_path
from fontTools.pens.transformPen import TransformPen
from fontTools.misc.transform import Transform
from fontPens.flattenPen import FlattenPen
from fontPens.marginPen import MarginPen
from random import random, randint
from fontTools.misc.bezierTools import calcCubicArcLength, splitCubicAtT
from collections import OrderedDict
from numbers import Number

try:
    from noise import pnoise1
except:
    pass

if __name__ == "__main__":
    import os
    import sys
    dirname = os.path.realpath(os.path.dirname(__file__))
    sys.path.append(f"{dirname}/../..")

USE_SKIA_PATHOPS = True

if USE_SKIA_PATHOPS:
    from pathops import Path, OpBuilder, PathOp
else:
    from booleanOperations.booleanGlyph import BooleanGlyph


from coldtype.geometry import Rect, Edge, Point, txt_to_edge
from coldtype.beziers import raise_quadratic, CurveCutter
from coldtype.color import Gradient, normalize_color, Color

try:
    from coldtype.pens.outlinepen import OutlinePen
except:
    pass


class BooleanOp(Enum):
    Difference = 0
    Union = 1
    XOR = 2
    ReverseDifference = 3
    Intersection = 4

    def Skia(x):
        return [
            PathOp.DIFFERENCE,
            PathOp.UNION,
            PathOp.XOR,
            PathOp.REVERSE_DIFFERENCE,
            PathOp.INTERSECTION,
        ][x.value]
    
    def BooleanGlyphMethod(x):
        return [
            "difference",
            "union",
            "xor",
            "reverseDifference",
            "intersection",
        ][x.value]


class ExplodingPen(ContourFilterPen):
    def __init__(self, outPen):
        self.pens = []
        super().__init__(outPen)

    def filterContour(self, contour):
        dp = DATPen()
        dp.value = contour
        self.pens.append(dp)
        return contour


class SmoothPointsPen(ContourFilterPen):
    def __init__(self, outPen, length=80):
        super().__init__(outPen)
        self.length = length

    def filterContour(self, contour):
        nc = []

        def split_line(pts):
            p0, p1 = pts
            nc.append(["lineTo", [p1]])

        def split_curve(pts):
            p0, p1, p2, p3 = pts
            length_arc = calcCubicArcLength(p0, p1, p2, p3)
            if length_arc <= self.length:
                nc.append(["curveTo", pts[1:]])
            else:
                d = self.length / length_arc
                b = (p0, p1, p2, p3)
                a, b = splitCubicAtT(*b, d)
                nc.append(["curveTo", a[1:]])
                split_curve(b)

        for i, (t, pts) in enumerate(contour):
            if t == "lineTo":
                p0 = contour[i-1][-1][-1]
                split_line((p0, pts[0]))
            elif t == "curveTo":
                p1, p2, p3 = pts
                p0 = contour[i-1][-1][-1]
                split_curve((p0, p1, p2, p3))
            else:
                nc.append([t, pts])
        return nc


class AlignableMixin():
    def align(self, rect, x=Edge.CenterX, y=Edge.CenterY, th=True, tv=False):
        x = txt_to_edge(x)
        y = txt_to_edge(y)
        b = self.getFrame(th=th, tv=tv)

        xoff = 0
        if x != None:
            if x == Edge.CenterX:
                xoff = -b.x + rect.x + rect.w/2 - b.w/2
            elif x == Edge.MinX:
                xoff = rect.x
            elif x == Edge.MaxX:
                xoff = -b.x + rect.x + rect.w - b.w
        
        yoff = 0
        if y != None:
            if y == Edge.CenterY:
                yoff = -b.y + rect.y + rect.h/2 - b.h/2
            elif y == Edge.MaxY:
                yoff = rect.y + rect.h - b.h
            elif y == Edge.MinY:
                yoff = rect.y
        
        diff = rect.w - b.w
        return self.translate(xoff, yoff)


class DATPen(RecordingPen, AlignableMixin):
    def __init__(self, **kwargs):
        super().__init__()
        self.clearAttrs()
        self.attr("default", **kwargs)
        self.frame = None
        self.typographic = False
        self._tag = "Unknown"
        self.container = None
        self.glyphName = None
    
    def pen(self):
        return self
    
    #def pens(self):
    #    return DATPenSet([pen])
    
    def tag(self, tag):
        self._tag = tag
        return self
    
    def getTag(self):
        return self._tag

    def contain(self, rect):
        self.container = rect
        return self
    
    def copy(self):
        dp = DATPen()
        self.replay(dp)
        for tag, attrs in self.attrs.items():
            dp.attr(tag, **attrs)
        return dp
    
    def cast(self, _class, *args):
        return _class(self, *args)
    
    def clearAttrs(self):
        self.attrs = OrderedDict()
        self.attr("default", fill=(1, 0, 0.5))
        return self

    def attr(self, tag="default", **kwargs):
        if len(kwargs.items()) == 0: # getting, not setting
            return self.attrs.get(tag)
        
        attrs = {}
        if tag and self.attrs.get(tag):
            attrs = self.attrs[tag]
        else:
            self.attrs[tag] = attrs
        for k, v in kwargs.items():
            if k == "fill":
                attrs[k] = normalize_color(v)
            elif k == "stroke":
                if not isinstance(v, dict):
                    attrs[k] = dict(color=normalize_color(v))
                else:
                    attrs[k] = dict(weight=v.get("weight", 1), color=normalize_color(v.get("color", 0)))
            elif k == "strokeWidth":
                if "stroke" in attrs:
                    attrs["stroke"]["weight"] = v
                    if attrs["stroke"]["color"].alpha == 0:
                        attrs["stroke"]["color"] = normalize_color((1, 0, 0.5))
                else:
                    attrs["stroke"] = dict(color=normalize_color((1, 0, 0.5)), weight=v)
            elif k == "shadow":
                if "color" in v:
                    v["color"] = normalize_color(v["color"])
                attrs[k] = v
            else:
                attrs[k] = v
        return self
    
    def clearFrame(self):
        self.frame = None
        return self
    
    def addFrame(self, frame, typographic=False):
        self.frame = frame
        if typographic:
            self.typographic = True
        return self
    
    def frameSet(self, th=False, tv=False):
        return DATPen(fill=("random", 0.25)).rect(self.getFrame(th=th, tv=tv))
    
    def getFrame(self, th=False, tv=False):
        if self.frame:
            if (th or tv) and len(self.value) > 0:
                f = self.frame
                b = self.bounds()
                if th and tv:
                    return b
                elif th:
                    return Rect(b.x, f.y, b.w, f.h)
                else:
                    return Rect(f.x, b.y, f.w, b.h)
            else:
                return self.frame
        else:
            return self.bounds()
    
    def updateFrameHeight(self, h):
        self.frame.h = h
    
    def reverse(self):
        dp = DATPen()
        rp = ReverseContourPen(dp)
        self.replay(rp)
        self.value = dp.value
        return self
    
    def transform(self, transform, transformFrame=True):
        op = RecordingPen()
        tp = TransformPen(op, transform)
        self.replay(tp)
        self.value = op.value
        if transformFrame and self.frame:
            self.frame = self.frame.transform(transform)
        return self
    
    def _pathop(self, otherPen=None, operation=BooleanOp.XOR):
        if USE_SKIA_PATHOPS:
            p1 = Path()
            self.replay(p1.getPen())
            if otherPen:
                p2 = Path()
                otherPen.replay(p2.getPen())
            builder = OpBuilder(fix_winding=True, keep_starting_points=True)
            builder.add(p1, PathOp.UNION)
            if otherPen:
                builder.add(p2, BooleanOp.Skia(operation))
            result = builder.resolve()
            d0 = DATPen()
            result.draw(d0)
            self.value = d0.value
            return self
        else:
            bg2 = BooleanGlyph()
            if otherPen:
                otherPen.replay(bg2.getPen())
            bg = BooleanGlyph()
            self.replay(bg.getPen())
            bg = bg._booleanMath(BooleanOp.BooleanGlyphMethod(operation), bg2)
            dp = DATPen()
            bg.draw(dp)
            self.value = dp.value
            return self
    
    def difference(self, otherPen):
        return self._pathop(otherPen=otherPen, operation=BooleanOp.Difference)
    
    def union(self, otherPen):
        return self._pathop(otherPen=otherPen, operation=BooleanOp.Union)
    
    def xor(self, otherPen):
        return self._pathop(otherPen=otherPen, operation=BooleanOp.XOR)
    
    def reverseDifference(self, otherPen):
        return self._pathop(otherPen=otherPen, operation=BooleanOp.ReverseDifference)
    
    def intersection(self, otherPen):
        return self._pathop(otherPen=otherPen, operation=BooleanOp.Intersection)
    
    def removeOverlap(self):
        return self._pathop(otherPen=DATPen(), operation=BooleanOp.Union)
    
    def translate(self, x, y):
        return self.transform(Transform(1, 0, 0, 1, x, y))
    
    def scale(self, scaleX, scaleY=None, center=None):
        # TODO centering
        t = Transform().scale(scaleX, scaleY or scaleX)
        return self.transform(t)
    
    def scaleToRect(self, rect):
        bounds = self.bounds()
        h = rect.w / bounds.w
        v = rect.h / bounds.h
        scale = h if h < v else v
        return self.scale(scale)
    
    def rotate(self, degrees, point=None):
        t = Transform()
        if not point:
            point = self.bounds().point("C") # maybe should be getFrame()?
        t = t.translate(point.x, point.y)
        t = t.rotate(math.radians(degrees))
        t = t.translate(-point.x, -point.y)
        return self.transform(t, transformFrame=False)

    def bounds(self):
        try:
            cbp = BoundsPen(None)
            self.replay(cbp)
            mnx, mny, mxx, mxy = cbp.bounds
            return Rect((mnx, mny, mxx - mnx, mxy - mny))
        except:
            return Rect(0, 0, 0, 0)

    def round(self, rounding):
        rounded = []
        for t, pts in self.value:
            rounded.append(
                (t,
                [(round(x, rounding), round(y, rounding)) for x, y in pts]))
        self.value = rounded
        return self

    def simplify(self):
        import numpy as np
        last = None
        times = 0
        nv = []
        for idx, (t, pts) in enumerate(self.value):
            if last == t and t == "qCurveTo":
                print("hello")
                continue
                p0 = np.array(self.value[idx-2][-1][-1])
                p1, p2, p3 = [np.array(p) for p in self.value[idx-1][-1]]
                q0 = np.array(self.value[idx-1][-1][-1])
                q1, q2, q3 = [np.array(p) for p in pts]
                r0 = p0
                kp = 2
                kq = 2
                r1 = p0 + kp * (p1 - p0)
                r2 = q3 + kq * (q2 - q3)
                r3 = q3
                nv.pop()
                nv.append([t, [r1.tolist(), r2.tolist(), r3.tolist()]])
                times += 1
            else:
                nv.append([t, pts])
            last = t
        #self.value = nv
        return self

    def record(self, pen):
        pen.replay(self)
        return self
    
    def glyph(self, glyph):
        glyph.draw(self)
        return self

    def flatten(self, length=10):
        if length == 0:
            return self
        dp = DATPen()
        fp = FlattenPen(dp, approximateSegmentLength=length, segmentLines=True)
        self.replay(fp)
        self.value = dp.value
        return self
    
    def addSmoothPoints(self, length=100):
        rp = RecordingPen()
        fp = SmoothPointsPen(rp)
        self.replay(fp)
        self.value = rp.value
        return self
    
    def smooth(self):
        dp = DATPen()
        for pts in self.skeletonPoints():
            _pts = [p[-1][-1] for p in pts]
            dp.catmull(_pts, close=True)
        self.value = dp.value
        return self
    
    def pixellate(self, rect, increment=50, inset=0):
        x = -200
        y = -200
        dp = DATPen()
        while x < 1000:
            while y < 1000:
                #print(x, y)
                pen = PointInsidePen(None, (x, y))
                self.replay(pen)
                isInside = pen.getResult()
                if isInside:
                    dp.rect(Rect(x, y, increment, increment).inset(inset))
                y += increment
            x += increment
            y = -200
        self.value = dp.value
        return self
    
    def scanlines(self, rect, sample=40, width=20, threshold=10):
        dp = DATPen()
        #print(">>>", rect)
        for y in range(min(-300, rect.y), max(1000, rect.h), sample): # 500 should be calc'ed from box right?
            mp = MarginPen(None, y, isHorizontal=True)
            self.replay(mp)
            xs = mp.getAll()
            if len(xs) > 1:
                for i in range(0, len(xs), 2):
                    try:
                        x1 = xs[i]
                        x2 = xs[i+1]
                        if abs(x2 - x1) > threshold:
                            dp.line([(x1, y), (x2, y)])
                    except:
                        pass
        self.value = dp.value
        return self.outline(width)
    
    def roughen(self, amplitude=10, threshold=10):
        try:
            randomized = []
            _x = 0
            _y = 0
            for t, pts in self.value:
                if t == "lineTo" or t == "curveTo":
                    jx = pnoise1(_x) * amplitude # should actually be 1-d on the tangent!
                    jy = pnoise1(_y) * amplitude
                    jx = randint(0, amplitude) - amplitude/2
                    jy = randint(0, amplitude) - amplitude/2
                    randomized.append([t, [(x+jx, y+jy) for x, y in pts]])
                    _x += 0.2
                    _y += 0.3
                else:
                    randomized.append([t, pts])
            self.value = randomized
        except:
            pass
        return self

    def outline(self, offset=1):
        op = OutlinePen(None, offset=offset, optimizeCurve=True, cap="square")
        self.replay(op)
        op.drawSettings(drawInner=True, drawOuter=True)
        g = op.getGlyph()
        p = DATPen()
        g.draw(p)
        self.value = p.value
        return self
    
    def dots(self, radius=4):
        dp = DATPen()
        for t, pts in self.value:
            if t == "moveTo":
                x, y = pts[0]
                dp.oval(Rect((x-radius, y-radius, radius, radius)))
        self.value = dp.value
        return self
    
    def catmull(self, points, close=False):
        p0 = points[0]
        p1, p2, p3 = points[:3]
        pts = [p0]
        i = 1
        while i < len(points):
            pts.append([
                ((-p0[0] + 6 * p1[0] + p2[0]) / 6),
                ((-p0[1] + 6 * p1[1] + p2[1]) / 6),
                ((p1[0] + 6 * p2[0] - p3[0]) / 6),
                ((p1[1] + 6 * p2[1] - p3[1]) / 6),
                p2[0],
                p2[1]
            ])
            p0 = p1
            p1 = p2
            p2 = p3
            try:
                p3 = points[i + 2]
            except:
                p3 = p3
            i += 1
        self.moveTo(pts[0])
        for p in pts[1:]:
            self.curveTo((p[0], p[1]), (p[2], p[3]), (p[4], p[5]))
        if close:
            self.closePath()
    
    def pattern(self, rect, clip=False):
        dp_copy = DATPen()
        dp_copy.value = self.value

        for y in range(-1, 1):
            for x in range(-1, 1):
                dpp = DATPen()
                dp_copy.replay(dpp)
                dpp.translate(rect.w*x, rect.h*y)
                dpp.replay(self)
        
        self.translate(rect.w/2, rect.h/2)
        if clip:
            clip_box = DATPen().rect(rect)
            return self.intersection(clip_box)
        return self
    
    def rect(self, rect, *args):
        if isinstance(rect, Rect):
            self.moveTo(rect.point("SW").xy())
            self.lineTo(rect.point("SE").xy())
            self.lineTo(rect.point("NE").xy())
            self.lineTo(rect.point("NW").xy())
            self.closePath()
        elif isinstance(rect, Number):
            return self.rect(Rect(rect, args[0], args[1], args[2]))
        elif isinstance(rect[0], Rect):
            for r in rect:
                self.rect(r)
        else:
            self.rect(Rect(rect))
        return self

    def line(self, points):
        self.moveTo(points[0])
        for p in points[1:]:
            self.lineTo(p)
        self.endPath()
        return self
    
    def roundedRect(self, rect, hr, vr):
        l, b, w, h = rect
        r, t = l + w, b + h
        K = 4 * (math.sqrt(2)-1) / 3
        circle = hr == 0.5 and vr == 0.5
        if hr <= 0.5:
            hr = w * hr
        if vr <= 0.5:
            vr = h * vr
        self.moveTo((l + hr, b))
        if not circle:
            self.lineTo((r - hr, b))
        self.curveTo((r+hr*(K-1), b), (r, b+vr*(1-K)), (r, b+vr))
        if not circle:
            self.lineTo((r, t-vr))
        self.curveTo((r, t-vr*(1-K)), (r-hr*(1-K), t), (r-hr, t))
        if not circle:
            self.lineTo((l+hr, t))
        self.curveTo((l+hr*(1-K), t), (l, t-vr*(1-K)), (l, t-vr))
        if not circle:
            self.lineTo((l, b+vr))
        self.curveTo((l, b+vr*(1-K)), (l+hr*(1-K), b), (l+hr, b))
        self.closePath()
        return self
    
    def oval(self, rect):
        self.roundedRect(rect, 0.5, 0.5)
        return self
    
    def polygon(self, sides, rect):
        radius = rect.square().w / 2
        c = rect.center()
        one_segment = math.pi * 2 / sides
        points = [(math.sin(one_segment * i) * radius, math.cos(one_segment * i) * radius) for i in range(sides)]
        dp = DATPen()
        points.reverse()
        dp.moveTo(points[0])
        for p in points[1:]:
            dp.lineTo(p)
        dp.closePath()
        dp.align(rect)
        self.record(dp)
        return self
    
    def quadratic(self, a, b, c, lineTo=False):
        a, b, c = [p.xy() if isinstance(p, Point) else p for p in [a, b, c]]
        dp = DATPen()
        if lineTo:
            dp.lineTo(a)
        else:
            dp.moveTo(a)
        dp.curveTo(*raise_quadratic(a, b, c))
        self.record(dp)
        return self
    
    def sine(self, r, periods):
        dp = DATPen()
        pw = r.w / periods
        p1 = r.point("SW")
        end = r.point("SE")
        dp.moveTo(p1)
        done = False
        up = True
        while not done:
            h = r.h if up else -r.h
            c1 = p1.offset(pw/2, 0)
            c2 = p1.offset(pw/2, h)
            p2 = p1.offset(pw, h)
            dp.curveTo(c1, c2, p2)
            p1 = p2
            if p1.x >= end.x:
                done = True
            else:
                done = False
            up = not up
        self.record(dp)
        return self
    
    def svg(self, file, gid, rect=Rect(0, 0, 0, 100)):
        from bs4 import BeautifulSoup
        with open(file, "r") as f:
            soup = BeautifulSoup(f.read(), features="lxml")
            tp = TransformPen(self, (1, 0, 0, -1, 0, rect.h))
            for path in soup.find(id=gid).find_all("path"):
                parse_path(path.get("d"), tp)
        return self
    
    def explode(self):
        dp = RecordingPen()
        ep = ExplodingPen(dp)
        self.replay(ep)
        return DATPenSet(ep.pens)
    
    def segregate(self):
        dp_open = DATPen()
        dp_closed = DATPen()
        for pen in self.explode().pens:
            if pen.value[-1][0] == "closePath":
                dp_closed.record(pen)
            else:
                dp_open.record(pen)
        return dp_open, dp_closed
    
    def subsegment(self, start=0, end=1):
        cc = CurveCutter(self)
        start = 0
        end = end * cc.calcCurveLength()
        pv = cc.subsegment(start, end)
        self.value = pv
        return self

    
    def points(self):
        contours = []
        for contour in self.skeletonPoints():
            _c = []
            for step, pts in contour:
                for pt in pts:
                    _c.append(pt)
            contours.append(_c)
        return contours

    def skeletonPoints(self):
        all_points = []
        points = []
        for idx, (t, pts) in enumerate(self.value):
            if t == "moveTo":
                points.append(("moveTo", pts))
            elif t == "curveTo":
                p0 = self.value[idx-1][-1][-1]
                points.append(("curveTo", [p0, *pts]))
            elif t == "lineTo":
                p0 = self.value[idx-1][-1][-1]
                points.append(("lineTo", [p0, *pts]))
            elif t == "closePath":
                all_points.append(points)
                points = []
                #points.append(("closePath", [None]))
        if len(points) > 0:
            all_points.append(points)
        return all_points
    
    def skeleton(self, scale=1, returnSet=False):
        dp = DATPen()
        moveTo = DATPen(fill=("random", 0.5))
        lineTo = DATPen(fill=("random", 0.5))
        curveTo_on = DATPen(fill=("random", 0.5))
        curveTo_off = DATPen(fill=("random", 0.25))
        curveTo_bars = DATPen(fill=None, stroke=dict(color=("random", 0.5), weight=1*scale))
        for idx, (t, pts) in enumerate(self.value):
            if t == "moveTo":
                r = 12*scale
                x, y = pts[0]
                moveTo.rect(Rect((x-r/2, y-r/2, r, r)))
            elif t == "curveTo":
                r = 6*scale
                x, y = pts[-1]
                curveTo_on.oval(Rect((x-r/2, y-r/2, r, r)))
                r = 4*scale
                x, y = pts[1]
                curveTo_off.oval(Rect((x-r/2, y-r/2, r, r)))
                x, y = pts[0]
                curveTo_off.oval(Rect((x-r/2, y-r/2, r, r)))
                p0 = self.value[idx-1][-1][-1]
                curveTo_bars.line((p0, pts[0]))
                curveTo_bars.line((pts[1], pts[2]))
            elif t == "lineTo":
                r = 6*scale
                x, y = pts[0]
                lineTo.rect(Rect((x-r/2, y-r/2, r, r)))
        
        all_pens = [moveTo, lineTo, curveTo_on, curveTo_off, curveTo_bars]
        if returnSet:
            return all_pens
        else:
            for _dp in all_pens:
                dp.record(_dp)
            self.value = dp.value
            return self
    
    def Grid(rect, x=20, y=None, opacity=0.3):
        grid = rect.inset(0, 0).grid(y or x, x)
        return DATPen(fill=None, stroke=dict(color=("random", opacity), weight=1)).rect(grid)


class DATPenSet(AlignableMixin):
    def __init__(self, *pens):
        self.pens = []
        self.addPens(pens)
        self.typographic = True
        self.layered = False
        self._tag = "Unknown"
        self.container = None
    
    def tag(self, tag):
        self._tag = tag
        return self
    
    def getTag(self):
        return self._tag
    
    def contain(self, rect):
        self.container = rect
        return self
    
    def addPens(self, pens):
        if isinstance(pens, DATPenSet):
            self.addPen(pens)
        else:
            for p in pens:
                if p:
                    if hasattr(p, "value"):
                        self.pens.append(p)
                    else:
                        self.addPens(p)
    
    def addPen(self, pen):
        if pen:
            self.pens.append(pen)
    
    def clearFrames(self):
        for p in self.pens:
            p.clearFrame()
        return self
    
    def addFrame(self, frame, typographic=False):
        for p in self.pens:
            p.addFrame(frame, typographic=typographic)
        return self
    
    def getFrame(self, th=False, tv=False, includeBlanks=True):
        try:
            union = self.pens[0].getFrame(th=th, tv=tv)
            for p in self.pens[1:]:
                if not includeBlanks and isinstance(p, DATPen) and len(p.value) == 0:
                    print(p.glyphName, len(p.value))
                else:
                    union = union.union(p.getFrame(th=th, tv=tv))
            return union
        except Exception as e:
            print("EXCEPTION>>>>>>>>>>>>>>>>>>>>>>>>>>", e)
            return Rect(0,0,0,0)
    
    def updateFrameHeight(self, h):
        for p in self.pens:
            p.updateFrameHeight(h)
    
    def replay(self, pen):
        self.pen().replay(pen)
    
    def pen(self):
        dp = DATPen()
        fps = self.flatten()
        for p in fps.pens:
            dp.record(p)
        if len(fps.pens) > 0:
            for k, attrs in fps.pens[0].attrs.items():
                dp.attr(tag=k, **attrs)
        dp.addFrame(self.getFrame())
        return dp
    
    def attr(self, k="default", **kwargs):
        if len(kwargs.items()) == 0: # getting, not setting
            return self.pens[0].attrs.get(k)
        
        for p in self.pens:
            p.attr(k, **kwargs)
        return self
    
    def removeOverlap(self):
        for p in self.pens:
            p.removeOverlap()
        return self
    
    def transform(self, t):
        for p in self.pens:
            p.transform(t)
        return self
    
    def translate(self, x, y):
        for p in self.pens:
            p.translate(x, y)
        return self
    
    def rotate(self, degrees):
        for p in self.pens:
            p.rotate(degrees)
        return self
    
    def round(self, rounding):
        for p in self.pens:
            p.round(rounding)
        return self
    
    def flatten(self):
        pens = []
        for p in self.pens:
            if isinstance(p, DATPenSet):
                pens.extend(p.flatten().pens)
            else:
                pens.append(p)
        dps = DATPenSet(pens)
        if self.layered:
            dps.layered = True
        return dps
    
    def frameSet(self, th=False, tv=False):
        dps = DATPenSet()
        for p in self.pens:
            if p.frame:
                dps.addPen(p.frameSet(th=th, tv=tv))
        return dps
    
    def alignToRects(self, rects, x=Edge.CenterX, y=Edge.CenterY):
        for idx, p in enumerate(self.pens):
            p.align(rects[idx], x, y)
    
    def distribute(self):
        x_off = 0
        for p in self.pens:
            frame = p.getFrame()
            #x_off += s.margin[0]
            p.translate(x_off, 0)
            x_off += frame.w
            #x_off += s.margin[1]
        return self
        
    def distributeOnPath(self, path):
        cutter = CurveCutter(path)
        limit = len(self.pens)
        for idx, p in enumerate(self.pens):
            f = p.getFrame()
            bs = f.y
            ow = f.x + f.w / 2
            if ow > cutter.length:
                limit = min(idx, limit)
            else:
                _p, tangent = cutter.subsegmentPoint(end=ow)
                x_shift = bs * math.cos(math.radians(tangent))
                y_shift = bs * math.sin(math.radians(tangent))
                t = Transform()
                t = t.translate(_p[0] + x_shift - f.x, _p[1] + y_shift - f.y)
                t = t.translate(f.x, f.y)
                t = t.rotate(math.radians(tangent-90))
                t = t.translate(-f.x, -f.y)
                t = t.translate(-f.w*0.5)
                p.transform(t)
        return self



if __name__ == "__main__":
    from coldtype.viewer import viewer
    from coldtype.pens.svgpen import SVGPen
    from coldtype.pens.reportlabpen import ReportLabPen
    from coldtype.color import Color

    from coldtype import StyledString, Style, Slug

    from random import seed, shuffle
    #seed(104)
    
    with viewer() as v:
        def gradient_test():
            r = Rect((0, 0, 500, 200))
            dp1 = StyledString("cold", Style("≈/Nonplus-Black.otf", 200)).pen().align(r)
            dp2 = StyledString("type", Style("≈/Nostrav0.9-Stream.otf", 110)).pen().align(r)
            dp1.removeOverlap().attr(fill="random")
            dp2.attr(fill=Gradient.Random(r)).rotate(5).translate(10, 0)
            pens = [
                DATPen.Grid(r, opacity=0.1),
                dp2.copy().translate(-4, 4).attr(fill=Gradient.Random(r, 0.9)),
                dp1.attr(fill=None, stroke="random"),
                dp2.intersection(dp1),
                *dp1.copy().skeleton(returnSet=True, scale=2),
            ]
            svg = SVGPen.Composite(pens, r)
            v.send(svg, r)
    
        def roughen_test():
            #seed(100)
            r = Rect((0, 0, 500, 300))
            f = "≈/Taters-Baked-v0.1.otf"
            f = "≈/Oaks0.1.otf"
            dp1 = Slug("o", Style(f, fontSize=300, ch="x")).pen().align(r)
            dp1.removeOverlap()
            dp1.flatten(length=10)
            dp1.roughen(amplitude=10)
            dp1.smooth()
            #dp1.removeOverlap()
            dp1.attr(fill=None, strokeWidth=1)

            pens = [dp1]
            svg = SVGPen.Composite(pens, r)
            v.send(svg, r)
        
        def pixellate_test():
            r = Rect((0, 0, 500, 300))
            f = "≈/Taters-Baked-v0.1.otf"
            f = "≈/Vinila-VF-HVAR-table.ttf"
            #f = "≈/Oaks0.1.otf"
            #f = "≈/RageItalicStd.otf"
            #f = "≈/MapRomanVariable-VF.ttf"
            dp1 = Slug("Pixels", Style(f, fontSize=100, ch="x", fill=0, wdth=1, wght=1, slnt=1, filter=lambda r, p: p.pixellate(r, inset=4))).pen().align(r)
            dp1.removeOverlap()
            v.send(SVGPen.Composite(dp1, r), r)
        
        def scanlines_test():
            r = Rect((0, 0, 500, 300))
            f = "≈/Taters-Baked-v0.1.otf"
            f = "≈/Vinila-VF-HVAR-table.ttf"
            #f = "≈/Oaks0.1.otf"
            #f = "≈/RageItalicStd.otf"
            #f = "≈/MapRomanVariable-VF.ttf"
            dp1 = Slug("Pixels", Style(f, fontSize=100, ch="x", fill=0, wdth=1, wght=1, slnt=1, filter=lambda r, p: p.removeOverlap().scanlines(r, sample=40, width=20))).pen().align(r)
            dp1.removeOverlap()
            v.send(SVGPen.Composite(dp1, r), r)
        
        def map_test():
            f, _v = ["≈/Fit-Variable.ttf", dict(wdth=0.2, scale=True)]
            f, _v = ["≈/MapRomanVariable-VF.ttf", dict(wdth=1, scale=True)]
            ss = Slug("California", Style(f, 40, t=20, **_v, fill=0))
            rect = Rect(0,0,500,500)
            r = rect.inset(50, 0).take(180, "centery")
            dp = DATPen(fill=None, stroke=("random", 0.3), strokeWidth=10).quadratic(r.p("SW"), r.p("C").offset(0, 300), r.p("NE"))
            ps = ss.pens()
            ps.distributeOnPath(dp)
            v.send(SVGPen.Composite(ps.pens + ps.frameSet(th=True, tv=True).pens + [dp], rect), rect)
        
        def align_test():
            r = Rect(0,0,500,300)
            p = Slug("Bay", Style("≈/RageItalicStd.otf", 300, fill=Gradient.Random(r))).pen().align(r)
            ps = Slug("Bay", Style("≈/RageItalicStd.otf", 300, fill=None, stroke=(0), strokeWidth=2)).pen().align(r)

            v.send(SVGPen.Composite([
                DATPen.Grid(r),
                p,
                ps,
                ps.frameSet()
            ], r), r)

        def conic_test():
            r = Rect(0, 0, 800, 800)
            ps = Slug("x", Style("≈/VulfMonoLightItalicVariable.ttf", 1000)).pen().align(r)
            ps.removeOverlap()
            dp = DATPen()
            #ps.simplify()
            c = SVGPen.Composite([ps], r)
            print(len(ps.value))
            v.send(c, r)

        def reverse_test():
            r = Rect(0, 0, 500, 500)
            ps = Slug("wow", Style("≈/Nonplus-Black.otf", 200, t=-20, fill=("random", 0.2), stroke="random", strokeWidth=2)).pens().align(r)
            ps.pens[1].reverse()
            v.send(SVGPen.Composite(ps.pen(), r), r)

        def sine_test():
            r = Rect(0, 0, 500, 500)
            dp = DATPen(fill=None, stroke=0).sine(r.take(100, "centery"), 10)
            v.send(SVGPen.Composite([dp], r), r)
        
        def outline_test():
            r = Rect(0, 0, 500, 500)
            ri = r.inset(100, 100)
            dp = DATPen(fill=None, stroke=0).line([ri.point("SW"), ri.point("NE")]).line([ri.point("NW"), ri.point("SE")])
            dp.outline(10).removeOverlap()
            v.send(SVGPen.Composite([dp], r), r)
        
        def separate_path_types_test():
            value = [('moveTo', [(40.0, 171.6)]), ('curveTo', [(42.8, 172.8), (43.6, 183.2), (38.8, 183.2)]), ('curveTo', [(30.0, 183.2), (32.0, 168.4), (40.0, 171.6)]), ('closePath', []), ('moveTo', [(65.2, 186.8)]), ('curveTo', [(59.2, 186.8), (57.2, 173.6), (65.2, 176.0)]), ('curveTo', [(70.8, 177.6), (69.2, 186.8), (65.2, 186.8)]), ('closePath', []), ('moveTo', [(28.0, 188.8)]), ('curveTo', [(32.4, 192.4), (38.0, 193.6), (43.6, 194.4)]), ('endPath', []), ('moveTo', [(62.4, 197.2)]), ('curveTo', [(70.4, 194.4), (76.8, 192.8), (80.0, 188.0)]), ('endPath', []), ('moveTo', [(35.2, 149.6)]), ('curveTo', [(46.8, 149.6), (74.0, 154.0), (86.4, 163.2)]), ('endPath', [])]

            r = Rect(0, 0, 500, 500)
            
            dp = DATPen(fill=None, stroke=0, strokeWidth=2)
            dp.value = value
            dp.align(r)
            o, c = dp.segregate()
            o.attr(fill=None, stroke=0, strokeWidth=2)
            o.subsegment(0, 1)
            v.send(SVGPen.Composite([o, c], r), r)

        #gradient_test()
        #roughen_test()
        #map_test()
        #align_test()
        #conic_test()
        #reverse_test()
        #sine_test()
        #outline_test()
        #pixellate_test()
        separate_path_types_test()
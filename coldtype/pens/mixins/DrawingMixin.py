import math

from pathlib import Path
from coldtype.geometry import Rect, Line, Point, Atom


class DrawingMixin():
    def _normPointSplat(self, p):
        if isinstance(p[0], Point):
            return p[0].xy()
        elif len(p) == 1:
            return p[0]
        else:
            return p

    def moveTo(self, *p):
        p = self._normPointSplat(p)
        self._val.moveTo(p)
        self._last = p
        return self

    def lineTo(self, *p):
        p = self._normPointSplat(p)
        if len(self._val.value) == 0:
            self._val.moveTo(p)
        else:
            self._val.lineTo(p)
        self._last = p
        return self

    def qCurveTo(self, *points):
        self._val.qCurveTo(*points)
        self._last = points[-1]
        return self

    def curveTo(self, *points):
        self._val.curveTo(*points)
        self._last = points[-1]
        return self

    def closePath(self):
        self._val.closePath()
        return self

    def endPath(self):
        self._val.endPath()
        return self
    
    def replay(self, pen):
        self._val.replay(pen)
        return self
    
    def record(self, pen):
        """Play a pen into this pen, meaning that pen will be added to this one’s value."""
        if hasattr(pen, "value"):
            pen.replay(self._val)
            return self

        if len(pen) > 0:
            for el in pen._els:
                self.record(el._val)
        elif pen:
            if isinstance(pen, Path):
                self.withJSONValue(pen)
            else:
                pen.replay(self._val)
        return self
    
    def unended(self):
        if not self.val_present():
            return None

        if len(self._val.value) == 0:
            return True
        elif self._val.value[-1][0] not in ["endPath", "closePath"]:
            return True
        return False
    
    def fully_close_path(self):
        if not self.val_present():
            # TODO log noop?
            return self

        if self._val.value[-1][0] == "closePath":        
            start = self._val.value[0][-1][-1]
            end = self._val.value[-2][-1][-1]

            if start != end:
                self._val.value = self._val.value[:-1]
                self.lineTo(start)
                self.closePath()
        return self
    
    fullyClosePath = fully_close_path

    def rect(self, rect):
        """Rectangle primitive — `moveTo/lineTo/lineTo/lineTo/closePath`"""
        self.moveTo(rect.point("SW").xy())
        self.lineTo(rect.point("SE").xy())
        self.lineTo(rect.point("NE").xy())
        self.lineTo(rect.point("NW").xy())
        self.closePath()
        return self
    
    r = rect
    
    def roundedRect(self, rect, hr, vr=None):
        """Rounded rectangle primitive"""
        if vr is None:
            vr = hr
        l, b, w, h = Rect(rect)
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
    
    rr = roundedRect
    
    def oval(self, rect):
        """Oval primitive"""
        self.roundedRect(rect, 0.5, 0.5)
        return self
    
    o = oval

    def line(self, points, moveTo=True, endPath=True):
        """Syntactic sugar for `moveTo`+`lineTo`(...)+`endPath`; can have any number of points"""
        if isinstance(points, Line):
            points = list(points)
        if len(points) == 0:
            return self
        if len(self._val.value) == 0 or moveTo:
            self.moveTo(points[0])
        else:
            self.lineTo(points[0])
        for p in points[1:]:
            self.lineTo(p)
        if endPath:
            self.endPath()
        return self
    
    l = line
    
    def hull(self, points):
        """Same as `DraftingPen.line` but calls closePath instead of endPath`"""
        self.moveTo(points[0])
        for pt in points[1:]:
            self.lineTo(pt)
        self.closePath()
        return self
    
    def round(self):
        """Round the values of this pen to integer values."""
        return self.round_to(1)

    def round_to(self, rounding):
        """Round the values of this pen to nearest multiple of rounding."""
        def rt(v, mult):
            rndd = float(round(v / mult) * mult)
            if rndd.is_integer():
                return int(rndd)
            else:
                return rndd
        
        rounded = []
        for t, pts in self._val.value:
            _rounded = []
            for p in pts:
                if p:
                    x, y = p
                    _rounded.append((rt(x, rounding), rt(y, rounding)))
                else:
                    _rounded.append(p)
            rounded.append((t, _rounded))
        
        self._val.value = rounded
        return self
    
    # Compound curve mechanics
    
    def interpCurveTo(self, p1, f1, p2, f2, to, inset=0):
        a = Point(self._val.value[-1][-1][-1])
        d = Point(to)
        pl = Line(p1, p2).inset(inset)
        b = Line(a, pl.start).t(f1/100)
        c = Line(d, pl.end).t(f2/100)
        return self.curveTo(b, c, d)
    
    def ioEaseCurveTo(self, pt, slope=0, fA=0, fB=85):
        a = Point(self._val.value[-1][-1][-1])
        d = Point(pt)
        box = Rect.FromMnMnMxMx([
            min(a.x, d.x),
            min(a.y, d.y),
            max(a.x, d.x),
            max(a.y, d.y)
        ])

        if a.y < d.y:
            line_vertical = Line(box.ps, box.pn)
        else:
            line_vertical = Line(box.pn, box.ps)

        angle = Line(a, d).angle() - line_vertical.angle()

        try:
            fA1, fA2 = fA
        except TypeError:
            fA1, fA2 = fA, fA
        
        try:
            fB1, fB2 = fB
        except TypeError:
            fB1, fB2 = fB, fB

        rotated = line_vertical.rotate(math.degrees(angle*(slope/100)))
        vertical = Line(rotated.intersection(box.es), rotated.intersection(box.en))

        if a.y > d.y:
            vertical = vertical.reverse()

        c1 = Line(a, vertical.start).t(fA1)
        c2 = Line(vertical.mid, vertical.start).t(fA1)
        self.lineTo(c1)
        self.curveTo(
            Line(c1, vertical.start).t(fB1),
            Line(c2, vertical.start).t(fB1),
            c2)
        c1 = Line(vertical.mid, vertical.end).t(fA2)
        c2 = Line(d, vertical.end).t(fA2)
        self.lineTo(c1)
        self.curveTo(
            Line(c1, vertical.end).t(fB2),
            Line(c2, vertical.end).t(fB2),
            c2)
        self.lineTo(d)
        return self
    
    def boxCurveTo(self, pt, point, factor=65, po=(0, 0), mods={}, flatten=False):
        #print("BOX", point, factor, pt, po, mods)

        if flatten:
            self.lineTo(pt)
            return self
        
        a = Point(self._val.value[-1][-1][-1])
        d = Point(pt)
        box = Rect.FromMnMnMxMx([
            min(a.x, d.x),
            min(a.y, d.y),
            max(a.x, d.x),
            max(a.y, d.y)
        ])

        try:
            f1, f2 = factor
        except TypeError:
            if isinstance(factor, Atom):
                f1, f2 = (factor[0], factor[0])
            else:
                f1, f2 = (factor, factor)

        if isinstance(point, str):
            #print("POINT", point)
            if point == "cx": # ease-in-out
                if a.y < d.y:
                    p1 = box.pse
                    p2 = box.pnw
                elif a.y > d.y:
                    p1 = box.pne
                    p2 = box.psw
                else:
                    p1 = p2 = a.interp(0.5, d)
            elif point == "e": # ease-in
                if a.y < d.y:
                    p1 = p2 = box.pse
                elif a.y > d.y:
                    p1 = p2 = box.pne
                else:
                    p1 = p2 = a.interp(0.5, d)
            elif point == "w": # ease-out
                if a.y < d.y:
                    p1 = p2 = box.pnw
                elif a.y > d.y:
                    p1 = p2 = box.psw
                else:
                    p1 = p2 = a.interp(0.5, d)
            else:
                p = box.point(point)
                p1, p2 = (p, p)
        elif isinstance(point, Point):
            p1, p2 = point, point
        else:
            p1, p2 = point
            p1 = box.point(p1)
            p2 = box.point(p2)
        
        p1 = p1.offset(*po)
        p2 = p2.offset(*po)
        
        b = a.interp(f1, p1)
        c = d.interp(f2, p2)

        mb = mods.get("b")
        mc = mods.get("c")
        if mb:
            b = mb(b)
        elif mc:
            c = mc(c)
        
        self.curveTo(b, c, d)
        return self
# to be loaded from within Blender

import os, math
from pathlib import Path

from coldtype.geometry.rect import Rect
from coldtype.pens.datpen import DATPen, DATPens
from coldtype.pens.blenderpen import BlenderPen, BPH
from coldtype.color import hsl

from coldtype.time import Frame, Timeline
from coldtype.renderable import renderable, Overlay, Action
from coldtype.renderable.animation import animation

from coldtype.blender.render import blend_source

try:
    import bpy # noqa
except ImportError:
    bpy = None
    pass

def b3d(collection,
    callback=None,
    plane=False,
    dn=False,
    material=None,
    zero=False,
    upright=False,
    tag_prefix=None,
    ):
    if not bpy: # short-circuit if this is meaningless
        return lambda x: x

    if not isinstance(collection, str):
        callback = collection
        collection = "Coldtype"

    pen_mod = None
    if callback and not callable(callback):
        pen_mod = callback[0]
        callback = callback[1]

    def annotate(pen:DATPen):
        if bpy and pen_mod:
            pen_mod(pen)
        
        prev = pen.data.get("b3d", {})
        if prev:
            callbacks = [*prev.get("callbacks"), callback]
        else:
            callbacks = [callback]

        c = None
        if zero:
            c = pen.ambit().pc
            pen.translate(-c.x, -c.y)

        pen.add_data("b3d", dict(
            collection=(collection
                or prev.get("collection", "Coldtype")),
            callbacks=callbacks,
            material=(material
                or prev.get("material", "auto")),
            tag_prefix=(tag_prefix or prev.get("tag_prefix")),
            dn=dn,
            plane=plane,
            reposition=c,
            upright=upright))
    
    return annotate


def b3d_mod(callback):
    def _cast(pen:DATPen):
        if bpy:
            callback(pen)
    return _cast


class b3d_mods():
    @staticmethod
    def center(r:Rect):
        return b3d_mod(lambda p:
            p.translate(-r.w/2, -r.h/2))
    
    def centerx(r:Rect):
        return b3d_mod(lambda p:
            p.translate(-r.w/2, 0))
    
    def centery(r:Rect):
        return b3d_mod(lambda p:
            p.translate(0, -r.h/2))


def walk_to_b3d(result:DATPens, dn=False):
    built = {}

    def walker(p:DATPen, pos, data):
        if pos == 0:
            bdata = p.data.get("b3d")
            if not bdata:
                p.ch(b3d(lambda bp: bp.extrude(0.01)))
                bdata = p.data.get("b3d")
            
            if p.tag() == "?" and data.get("idx"):
                tag = "_".join([str(i) for i in data["idx"]])
                if bdata.get("tag_prefix"):
                    tag = bdata.get("tag_prefix") + tag
                else:
                    tag = "ct_autotag_" + tag
                p.tag(tag)

            if bdata:
                coll = BPH.Collection(bdata["collection"])
                material = bdata.get("material", "auto")

                if len(p.value) == 0:
                    p.v(0)
                
                denovo = bdata.get("dn", dn)

                if bdata.get("plane"):
                    bp = p.cast(BlenderPen).draw(coll, plane=True, material=material, dn=True)
                else:
                    bp = p.cast(BlenderPen).draw(coll, dn=denovo, material=material)
                
                if bdata.get("callbacks"):
                    for cb in bdata.get("callbacks"):
                        cb(bp)

                bp.hide(not p._visible)

                if bdata.get("reposition"):
                    pt = bdata.get("reposition")
                    if bdata.get("upright"):
                        bp.locate(pt.x/100, 0, pt.y/100)
                    else:
                        bp.locate(pt.x/100, pt.y/100)
                
                built[p.tag()] = (p, bp)
                
    result.walk(walker)

class b3d_renderable(renderable):
    def post_read(self):
        if not hasattr(self, "blend"):
            self.blend = self.filepath.parent / "blends" / (self.filepath.stem + ".blend")

        if self.blend:
            self.blend = Path(self.blend).expanduser()
            self.blend.parent.mkdir(exist_ok=True, parents=True)

        super().post_read()


class b3d_animation(animation):
    def __init__(self,
        rect=(1080, 1080),
        samples=16,
        denoise=True,
        blend=None,
        match_length=True,
        match_output=True,
        bake=False,
        **kwargs
        ):
        self.func = None
        self.name = None
        self.current_frame = -1
        self.samples = samples
        self.denoise = denoise
        self.blend = blend
        self.bake = bake
        self.match_length = match_length
        self.match_output = match_output
        
        if "timeline" not in kwargs:
            kwargs["timeline"] = Timeline(30)
        
        super().__init__(rect=rect, **kwargs)

        if bpy and self.match_length:
            bpy.data.scenes[0].frame_end = self.t.duration-1
            # don't think this is totally accurate but good enough for now
            if isinstance(self.t.fps, float):
                bpy.data.scenes[0].render.fps = round(self.t.fps)
                bpy.data.scenes[0].render.fps_base = 1.001
            else:
                bpy.data.scenes[0].render.fps = self.t.fps
                bpy.data.scenes[0].render.fps_base = 1
    
    def run(self, render_pass, renderer_state):
        fi = render_pass.args[0].i
        if renderer_state and not bpy:
            if renderer_state.previewing:
                if Overlay.Rendered in renderer_state.overlays:
                    from coldtype.img.skiaimage import SkiaImage
                    return SkiaImage(self.pass_path(fi))
        
        return super().run(render_pass, renderer_state)
    
    def rasterize(self, _, rp):
        fi = rp.args[0].i
        blend_source(self.filepath, self.blend, fi, self.pass_path(""), self.samples, denoise=self.denoise)
        return True
    
    def post_read(self):
        if not self.blend:
            self.blend = self.filepath.parent / "blends" / (self.filepath.stem + ".blend")

        if self.blend:
            self.blend = Path(self.blend).expanduser()
            self.blend.parent.mkdir(exist_ok=True, parents=True)

        super().post_read()
        if bpy and self.match_output:
            bpy.data.scenes[0].render.filepath = str(self.pass_path(""))
    
    def baked_frames(self):
        def bakewalk(p, pos, data):
            if pos == 0:
                fi = data["idx"][0]
                (p.ch(b3d(f"CTBakedAnimation_{self.name}",
                    lambda bp: bp
                        .show_on_frame(fi)
                        .print(f"Baking frame {fi}..."),
                    dn=True,
                    tag_prefix=f"ct_baked_frame_{fi}_{self.name}")))
        
        to_bake = DATPens([])
        for ps in self.passes(Action.RenderAll, None)[:]:
            to_bake += self.run_normal(ps, None)
        
        return to_bake.walk(bakewalk)
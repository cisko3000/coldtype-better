from coldtype import *
from coldtype.blender import *

"""
pʰliz kalˠ stɛlɘ
æsk hɚ ɾɘ bɹɪŋ ðiːz θɪŋɡz wɪð hɚ fɹɔm nɘ stɔɘ
sɪks spuːnz ʌv fɹɛʃ snoʊ pʰiːz
faɪv tɪk slæbz ʌv blu tʃiːz
n meɪbi ɘ snæk fɔɹ hɚ bɹʌðɘ bɔɘb
"""

bt = BlenderTimeline(__BLENDER__, 400)

@b3d_sequencer((1080, 1080)
, timeline=bt
, bg=hsl(0.7)
, render_bg=1
, watch=[bt.file]
, live_preview_scale=0.25
)
def lyrics(f):
    def render_clip(tc):
        if "title" in tc.styles:
            return tc.text.upper(), Style("smoosh4", 500)
        else:
            return tc.text, Style("Brill Roman", 250)

    cg = f.t.words.currentGroup()

    txt = (cg.pens(f, render_clip
        , graf_style=GrafStyle(leading=30)
        , use_lines=[cg.currentWord(f.i) if not f.t.words.styles.ki("title").on() else None]
        )
        .removeFutures()
        .removeBlanks()
        .align(f.a.r)
        .f(1))
    

    if len(txt) > 0:
        return PS([
            #P(txt.ambit(th=1).inset(-20)),
            #P().gridlines(f.a.r, 5).s(hsl(0.9)),
            txt])
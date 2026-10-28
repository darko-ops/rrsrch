# Renders the RRSRCH icon (a white dot on black, as in public/favicon.svg) to the PNG and ICO files in public/.
import sys
from PIL import Image, ImageDraw

def icon(size, ss=8):
    big = size * ss
    im = Image.new('RGB', (big, big), '#000000')
    r = big * 0.17
    c = big / 2
    ImageDraw.Draw(im).ellipse((c - r, c - r, c + r, c + r), fill='#ffffff')
    return im.resize((size, size), Image.LANCZOS)

out = sys.argv[1]
for name, size in [('logo192.png', 192), ('logo512.png', 512), ('apple-touch-icon.png', 180)]:
    icon(size).save(f'{out}/{name}', optimize=True)
icon(256).save(f'{out}/favicon.ico', sizes=[(16, 16), (32, 32), (48, 48)])

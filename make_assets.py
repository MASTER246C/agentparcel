#!/usr/bin/env python3
"""Regenerates src/assets/* from the two source images (neon AgentParcel brand). Run when the logo changes."""
import os
from PIL import Image, ImageDraw, ImageChops, ImageEnhance, ImageFilter
A = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src", "assets")
SRC_ICON = Image.open(os.path.join(A, "source-icon.png")).convert("RGB")
SQUARE = (100, 90, 925, 915)          # the rounded square inside the black margin (measured)
RADIUS = 0.206                        # corner radius / side (measured on the source)
ZOOM = (175, 160, 895, 880)           # cube only, for 16-32 px so it stays readable


def rounded(im, size, radius):
    im = im.resize((size, size), Image.LANCZOS).convert("RGBA")
    ss = 4
    m = Image.new("L", (size * ss, size * ss), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, size * ss - 1, size * ss - 1), radius=radius * size * ss, fill=255)
    im.putalpha(m.resize((size, size), Image.LANCZOS))
    return im


def icon(size):
    if size <= 48:
        im = SRC_ICON.crop(ZOOM)
        # thicken the neon lines so they survive the downscale (1 source px ~ 1/45 of a 16 px icon pixel)
        k = {16: 25, 24: 17, 32: 13, 48: 9}.get(size, 9)
        im = ImageChops.lighter(im, im.filter(ImageFilter.MaxFilter(k)))
        im = ImageEnhance.Brightness(im).enhance(1.5)
        im = ImageEnhance.Color(im).enhance(1.3)
        im = im.resize((size * 4, size * 4), Image.LANCZOS).filter(ImageFilter.UnsharpMask(2, 160, 2))
        return rounded(im, size, 0.22)
    return rounded(SRC_ICON.crop(SQUARE), size, RADIUS)


def write_ico(path, images, png_from=128):
    """ICO with classic 32-bit BMP frames (+ PNG frames from png_from px up). BMP frames load in every
    Windows / .NET Framework version (System.Drawing.Icon), unlike all-PNG icons."""
    import io, struct
    blobs = []
    for im in images:
        w, h = im.size
        if w >= png_from:
            b = io.BytesIO(); im.save(b, "PNG"); blobs.append(b.getvalue()); continue
        px = im.convert("RGBA").transpose(Image.FLIP_TOP_BOTTOM).tobytes("raw", "BGRA")
        mask_row = ((w + 31) // 32) * 4
        hdr = struct.pack("<IiiHHIIiiII", 40, w, h * 2, 1, 32, 0, len(px) + mask_row * h, 0, 0, 0, 0)
        blobs.append(hdr + px + b"\0" * (mask_row * h))
    out = struct.pack("<HHH", 0, 1, len(images))
    off = 6 + 16 * len(images)
    for im, b in zip(images, blobs):
        w, h = im.size
        out += struct.pack("<BBBBHHII", w % 256, h % 256, 0, 0, 1, 32, len(b), off); off += len(b)
    with open(path, "wb") as f:
        f.write(out + b"".join(blobs))


def glow_to_alpha(im, gamma=0.8):
    """Black background -> transparent (alpha = brightest channel), colours un-premultiplied."""
    im = im.convert("RGB")
    r, g, b = im.split()
    a = ImageChops.lighter(ImageChops.lighter(r, g), b).point(lambda v: 0 if v < 10 else min(255, int(255 * ((v - 10) / 245.0) ** gamma)))
    px = im.load(); ap = a.load()
    out = Image.new("RGBA", im.size)
    op = out.load()
    for y in range(im.height):
        for x in range(im.width):
            al = ap[x, y]
            if al:
                c = px[x, y]; k = 255.0 / max(c)
                op[x, y] = (min(255, int(c[0] * k)), min(255, int(c[1] * k)), min(255, int(c[2] * k)), al)
    return out


if __name__ == "__main__":
    for f in os.listdir(A):
        if not f.startswith("source-"):
            os.remove(os.path.join(A, f))
    for s in (16, 24, 32, 48, 64, 128, 256, 512, 1024):
        icon(s).save(os.path.join(A, "agentparcel-%d.png" % s), optimize=True)
    write_ico(os.path.join(A, "AgentParcel.ico"), [icon(s) for s in (16, 24, 32, 48, 64, 128, 256)])
    write_ico(os.path.join(A, "AgentParcel-small.ico"), [icon(s) for s in (16, 24, 32, 48)])
    try:
        icon(1024).save(os.path.join(A, "AgentParcel.icns"))
    except Exception as e:
        print("icns skipped:", e)
    wm = Image.open(os.path.join(A, "source-wordmark.jpg")).convert("RGB")
    bbox = wm.convert("L").point(lambda v: 255 if v > 18 else 0).getbbox()
    p = 24
    crop = wm.crop((max(0, bbox[0] - p), max(0, bbox[1] - p), min(wm.width, bbox[2] + p), min(wm.height, bbox[3] + p)))
    wm.save(os.path.join(A, "agentparcel-wordmark-black.jpg"), quality=95)          # as delivered
    crop.save(os.path.join(A, "agentparcel-wordmark-black.png"), optimize=True)      # trimmed, black bg
    t = glow_to_alpha(crop)
    t.save(os.path.join(A, "agentparcel-wordmark.png"), optimize=True)              # transparent
    t.resize((640, round(t.height * 640 / t.width)), Image.LANCZOS).save(os.path.join(A, "agentparcel-wordmark-640.png"), optimize=True)
    for f in sorted(os.listdir(A)):
        print("%8d  %s" % (os.path.getsize(os.path.join(A, f)), f))

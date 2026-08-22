"""Render the Listen app icon to assets/Listen.png and assets/Listen.icns.

PyObjC's NSImage.lockFocus() draws into a view-backed context that is empty
when we then read back via CGImage. We render straight into a CGBitmapContext
and use Quartz for both drawing and PNG export.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import AppKit
import objc
import Quartz
from Quartz import CGPointMake, CGSizeMake, CGRectMake

SIZE = 1024


def _rounded_rect(ctx, x, y, w, h, r):
    path = Quartz.CGPathCreateMutable()
    Quartz.CGPathAddRoundedRect(path, None, CGRectMake(x, y, w, h), r, r)
    Quartz.CGContextAddPath(ctx, path)


def _add_arc(ctx, cx, cy, r, start_deg, end_deg):
    path = Quartz.CGPathCreateMutable()
    Quartz.CGPathAddArc(path, None, cx, cy, r, start_deg, end_deg, False)
    Quartz.CGContextAddPath(ctx, path)


def _add_line(ctx, x1, y1, x2, y2):
    Quartz.CGContextMoveToPoint(ctx, x1, y1)
    Quartz.CGContextAddLineToPoint(ctx, x2, y2)


def _set_fill_rgb(ctx, r, g, b, a=1.0):
    Quartz.CGContextSetRGBFillColor(ctx, r, g, b, a)


def _set_stroke_rgb(ctx, r, g, b, a=1.0):
    Quartz.CGContextSetRGBStrokeColor(ctx, r, g, b, a)


def _draw(size: int):
    s = float(size)
    cs = Quartz.CGColorSpaceCreateDeviceRGB()
    ctx = Quartz.CGBitmapContextCreate(
        None, size, size, 8, size * 4, cs,
        Quartz.kCGImageAlphaPremultipliedLast,
    )

    # 1. Solid blue background — proves the bitmap context is writing
    # something opaque. CG origin is bottom-left, so this fills the canvas.
    _set_fill_rgb(ctx, 0.20, 0.27, 0.50, 1.0)
    Quartz.CGContextFillRect(ctx, CGRectMake(0, 0, s, s))

    # 2. Clip to a rounded square so subsequent drawing respects the shape.
    Quartz.CGContextSaveGState(ctx)
    _rounded_rect(ctx, 0, 0, s, s, s * 0.22)
    Quartz.CGContextClip(ctx)

    # 3. Vertical blue gradient on top of the solid fill.
    grad_cs = Quartz.CGColorSpaceCreateDeviceRGB()
    locs = (0.0, 1.0)
    colors = (
        (0.30, 0.36, 0.55, 1.0),  # lighter blue at top
        (0.14, 0.20, 0.42, 1.0),  # dark blue at bottom
    )
    grad = Quartz.CGGradientCreateWithColors(grad_cs, colors, locs)
    Quartz.CGContextDrawLinearGradient(
        ctx, grad,
        CGPointMake(0, s), CGPointMake(0, 0),
        0,
    )
    Quartz.CGContextRestoreGState(ctx)

    # 4. White microphone, centered, sized to fit comfortably.
    cx, cy = s / 2, s / 2
    _set_fill_rgb(ctx, 1.0, 1.0, 1.0, 1.0)
    _set_stroke_rgb(ctx, 1.0, 1.0, 1.0, 1.0)

    # Capsule body (rounded rectangle)
    body_w = s * 0.18
    body_h = s * 0.28
    body = Quartz.CGPathCreateMutable()
    Quartz.CGPathAddRoundedRect(
        body, None,
        CGRectMake(cx - body_w / 2, cy + body_h / 2 - body_h * 0.85, body_w, body_h),
        body_w / 2, body_w / 2,
    )
    Quartz.CGContextAddPath(ctx, body)
    Quartz.CGContextFillPath(ctx)

    # Cradle arc (open semicircle below the body)
    Quartz.CGContextSetLineWidth(ctx, s * 0.04)
    Quartz.CGContextSetLineCap(ctx, Quartz.kCGLineCapRound)
    _add_arc(ctx, cx, cy - s * 0.05, s * 0.20, 30.0, 150.0)
    Quartz.CGContextStrokePath(ctx)

    # Vertical stem
    _add_line(ctx, cx, cy - s * 0.25, cx, cy - s * 0.40)
    Quartz.CGContextStrokePath(ctx)

    # Horizontal base
    _add_line(ctx, cx - s * 0.12, cy - s * 0.40, cx + s * 0.12, cy - s * 0.40)
    Quartz.CGContextStrokePath(ctx)

    # Sound-wave dots above the mic
    for i, dx in enumerate((-0.10, 0.0, 0.10)):
        d = Quartz.CGPathCreateMutable()
        Quartz.CGPathAddEllipseInRect(
            d, None,
            CGRectMake(cx + s * dx - s * 0.022, cy + s * 0.22 - i * s * 0.015,
                       s * 0.044, s * 0.044),
        )
        _set_fill_rgb(ctx, 1.0, 1.0, 1.0, 0.7 - i * 0.15)
        Quartz.CGContextAddPath(ctx, d)
        Quartz.CGContextFillPath(ctx)

    return Quartz.CGBitmapContextCreateImage(ctx)


def _save_png(cg_image, path: Path) -> None:
    url = Quartz.CFURLCreateWithFileSystemPath(
        None, str(path), Quartz.kCFURLPOSIXPathStyle, False
    )
    dest = Quartz.CGImageDestinationCreateWithURL(url, "public.png", 1, None)
    Quartz.CGImageDestinationAddImage(dest, cg_image, None)
    Quartz.CGImageDestinationFinalize(dest)


def _resize(src, size: int):
    color_space = Quartz.CGColorSpaceCreateDeviceRGB()
    ctx = Quartz.CGBitmapContextCreate(
        None, size, size, 8, size * 4, color_space,
        Quartz.kCGImageAlphaPremultipliedLast,
    )
    Quartz.CGContextSetInterpolationQuality(ctx, Quartz.kCGInterpolationHigh)
    Quartz.CGContextDrawImage(ctx, CGRectMake(0, 0, size, size), src)
    return Quartz.CGBitmapContextCreateImage(ctx)


def main() -> int:
    out = Path(__file__).resolve().parent.parent / "assets"
    out.mkdir(exist_ok=True)

    # Source: 1024x1024 master.
    master = _draw(SIZE)
    _save_png(master, out / "Listen.png")
    print(f"wrote {out / 'Listen.png'}")

    # Build .iconset of all required Apple sizes.
    iconset = out / "Listen.iconset"
    if iconset.exists():
        subprocess.run(["rm", "-rf", str(iconset)], check=True)
    iconset.mkdir()
    sizes = [
        (16, "icon_16x16.png"),
        (32, "icon_16x16@2x.png"),
        (32, "icon_32x32.png"),
        (64, "icon_32x32@2x.png"),
        (128, "icon_128x128.png"),
        (256, "icon_128x128@2x.png"),
        (256, "icon_256x256.png"),
        (512, "icon_256x256@2x.png"),
        (512, "icon_512x512.png"),
        (1024, "icon_512x512@2x.png"),
    ]
    for s, name in sizes:
        _save_png(_resize(master, s), iconset / name)

    icns = out / "Listen.icns"
    if icns.exists():
        icns.unlink()
    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(icns)], check=True)
    subprocess.run(["rm", "-rf", str(iconset)], check=True)
    print(f"wrote {icns}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
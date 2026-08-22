"""Menu-bar icon rendering and the recording pulse animation.

Icons owns the one NSStatusBarButton reference; `apply(AppState)` is the only
entry point the app needs — it stops/starts the pulse and swaps the image.
All calls must come from the main thread.
"""
from __future__ import annotations

import AppKit

from . import state

_ICON_SIZE = 16.0


def _drawn(size: float, template: bool, color: AppKit.NSColor, draw_fn) -> AppKit.NSImage:
    """Render `draw_fn` into a template/colored NSImage of the given size.

    We draw into an explicit NSBitmapImageRep/NSGraphicsContext instead of
    NSImage.lockFocus(): in a menu-bar-only (LSUIElement) process lockFocus
    produces an empty snapshot on recent macOS, and the status item shows a
    crossed-circle placeholder. 2× backing keeps the icon crisp on Retina.
    """
    px = int(size) * 2
    rep = AppKit.NSBitmapImageRep.alloc(
    ).initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, px, px, 8, 4, True, False, AppKit.NSDeviceRGBColorSpace, 0, 0
    )
    rep.setSize_((size, size))
    AppKit.NSGraphicsContext.saveGraphicsState()
    AppKit.NSGraphicsContext.setCurrentContext_(
        AppKit.NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep)
    )
    try:
        color.set()
        draw_fn()
    finally:
        AppKit.NSGraphicsContext.restoreGraphicsState()
    img = AppKit.NSImage.alloc().initWithSize_((size, size))
    img.addRepresentation_(rep)
    img.setTemplate_(template)
    return img


def _black(alpha: float = 1.0) -> AppKit.NSColor:
    return AppKit.NSColor.blackColor().colorWithAlphaComponent_(alpha)


def _mic(alpha: float = 1.0) -> AppKit.NSImage:
    """A minimalist microphone, drawn as a template image (adapts to bar)."""

    def draw() -> None:
        # capsule body
        AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            ((5.5, 5.8), (5.0, 7.4)), 2.4, 2.4
        ).fill()
        # cradle arc under the head (CCW from 180° to 360° = bottom semicircle)
        arc = AppKit.NSBezierPath.bezierPath()
        arc.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_(
            (8.0, 7.0), 3.1, 180.0, 360.0
        )
        arc.setLineWidth_(1.3)
        arc.stroke()
        # stem + base
        stem = AppKit.NSBezierPath.bezierPath()
        stem.moveToPoint_((8.0, 3.9))
        stem.lineToPoint_((8.0, 2.3))
        stem.setLineWidth_(1.3)
        stem.stroke()
        base = AppKit.NSBezierPath.bezierPath()
        base.moveToPoint_((5.0, 2.3))
        base.lineToPoint_((11.0, 2.3))
        base.setLineWidth_(1.3)
        base.stroke()

    return _drawn(_ICON_SIZE, template=True, color=_black(alpha), draw_fn=draw)


def _warn(alpha: float = 1.0) -> AppKit.NSImage:
    """A warning triangle with an exclamation mark (template)."""

    def draw() -> None:
        tri = AppKit.NSBezierPath.bezierPath()
        tri.moveToPoint_((8.0, 13.6))
        tri.lineToPoint_((1.8, 2.6))
        tri.lineToPoint_((14.2, 2.6))
        tri.closePath()
        tri.setLineWidth_(1.3)
        tri.stroke()
        bar = AppKit.NSBezierPath.bezierPath()
        bar.moveToPoint_((8.0, 10.6))
        bar.lineToPoint_((8.0, 6.6))
        bar.setLineWidth_(1.6)
        bar.stroke()
        AppKit.NSBezierPath.bezierPathWithOvalInRect_(((7.2, 4.4), (1.6, 1.6))).fill()

    return _drawn(_ICON_SIZE, template=True, color=_black(alpha), draw_fn=draw)


def _red_dot(dimen: float = 14.0, alpha: float = 1.0) -> AppKit.NSImage:
    def draw() -> None:
        inset = 2.0
        AppKit.NSBezierPath.bezierPathWithOvalInRect_(
            ((inset, inset), (dimen - 2 * inset, dimen - 2 * inset))
        ).fill()

    color = AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(
        0.95, 0.2, 0.15, alpha
    )
    return _drawn(dimen, template=False, color=color, draw_fn=draw)  # stays red


def _reduce_motion() -> bool:
    return bool(
        AppKit.NSWorkspace.sharedWorkspace().accessibilityDisplayShouldReduceMotion()
    )


class Icons:
    """Caches icon images and drives the recording pulse for one status button."""

    def __init__(self) -> None:
        self._button = None
        self._timer = None
        self._pulse_on = False
        # Cache icons so we don't rebuild them per state change.
        self._icon_mic = _mic(1.0)
        self._icon_mic_dim = _mic(0.4)
        self._icon_warn = _warn(1.0)
        self._icon_dot = _red_dot(14.0, 1.0)
        self._icon_dot_dim = _red_dot(14.0, 0.35)

    def attach(self, button) -> None:
        self._button = button

    def apply(self, eff: state.AppState) -> None:
        """Show the icon for an effective app state (pulse when recording)."""
        if eff == state.RECORDING:
            if self._timer is None:
                self._start_pulse()
            return
        if self._timer is not None:
            self._stop_pulse()
        if eff == state.READY:
            self._show(self._icon_mic)
        elif eff == state.TRANSCRIBING:
            self._show(self._icon_dot_dim)
        elif eff == state.LOADING:
            self._show(self._icon_mic_dim)
        else:  # NEEDS_AX, MIC_DENIED, ERROR
            self._show(self._icon_warn)

    def set_tooltip(self, text: str) -> None:
        if self._button is not None:
            self._button.setToolTip_(text)

    def _show(self, image: AppKit.NSImage) -> None:
        if self._button is not None:
            self._button.setImage_(image)

    def _start_pulse(self) -> None:
        if _reduce_motion():
            self._show(self._icon_dot)
            return
        self._pulse_on = True
        self._show(self._icon_dot)
        self._timer = (
            AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                0.5, self, "pulse:", None, True
            )
        )

    def pulse_(self, timer) -> None:
        self._pulse_on = not self._pulse_on
        self._show(self._icon_dot if self._pulse_on else self._icon_dot_dim)

    def _stop_pulse(self) -> None:
        if self._timer is not None:
            self._timer.invalidate()
            self._timer = None

"""The Auto-Replace editor window — the app's manual "fine-tuning" surface.

One row per rule: a normal system text field "heard as" → a normal system
text field "replace with", a − button to drop the row, + to add one. Editing
is a plain NSTextField (click and type — no table cell machinery, no edit
sessions to get cancelled). Every change persists immediately (atomic save),
so there is no Save button to forget.

"Paste List…" opens a sheet for bulk entry: paste the mis-heard words into
the left list and the replacements into the right one — line N pairs with
line N and becomes rows in one click (an already-known word updates its
replacement instead of duplicating).

The window is owned by the App and reused across opens; reload() re-reads
the dictionary.

Stability: every ObjC-exposed method (actions, control delegate) wraps its
body in try/except — a Python exception escaping into ObjC shows the macOS
"unexpectedly quit" alert and aborts the app.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import AppKit
import objc

from .corrections import merge_into, parse_pairs_text

log = logging.getLogger("listen")

_WIN_W = 540
_WIN_H = 470
_ROW_H = 36
_FIELD_H = 24
_SCROLL_X = 16
_SCROLL_Y = 64
_SCROLL_W = _WIN_W - 2 * _SCROLL_X
_SCROLL_H = _WIN_H - _SCROLL_Y - 92

_DESCRIPTION = (
    "Words recognized as the left column are auto-replaced with the right "
    "one before pasting; an empty right field deletes the word. Pasting a "
    "multi-line list into a field splits it into rows, one line per row "
    "(a list pasted into a right field fills the rows downward)."
)

_SHEET_W = 540
_SHEET_H = 320
_COL_W = 246
_TV_H = 112


class ListTextField(AppKit.NSTextField):
    """Marker subclass: the window's performKeyEquivalent_ finds its row
    fields by type (see the Cmd+V list-paste interception there)."""

    pass


class CorrectionsWindow(AppKit.NSWindow):

    def init(self):
        style = AppKit.NSTitledWindowMask | AppKit.NSClosableWindowMask
        self = objc.super(CorrectionsWindow, self).initWithContentRect_styleMask_backing_defer_(
            AppKit.NSMakeRect(0, 0, _WIN_W, _WIN_H),
            style,
            AppKit.NSBackingStoreBuffered,
            False,
        )
        if self is None:
            return None
        self.setTitle_("Auto-Replace")
        self.setReleasedWhenClosed_(False)
        self._corrections = None
        self._rows: list[dict] = []
        self._row_fields: list[tuple] = []  # (left NSTextField, right) per row
        self._build()
        self.center()
        return self

    @objc.python_method
    def _build(self) -> None:
        view = AppKit.NSView.alloc().initWithFrame_(
            AppKit.NSMakeRect(0, 0, _WIN_W, _WIN_H)
        )
        self.setContentView_(view)

        desc = AppKit.NSTextField.labelWithString_(_DESCRIPTION)
        desc.setFont_(AppKit.NSFont.systemFontOfSize_(12))
        desc.setTextColor_(AppKit.NSColor.secondaryLabelColor())
        desc.setLineBreakMode_(AppKit.NSLineBreakByWordWrapping)
        desc.setFrame_(AppKit.NSMakeRect(_SCROLL_X, _WIN_H - 80, _SCROLL_W, 56))
        view.addSubview_(desc)

        self.scroll = AppKit.NSScrollView.alloc().initWithFrame_(
            AppKit.NSMakeRect(_SCROLL_X, _SCROLL_Y, _SCROLL_W, _SCROLL_H)
        )
        self.scroll.setHasVerticalScroller_(True)
        self.scroll.setAutohidesScrollers_(True)
        self.scroll.setBorderType_(AppKit.NSBezelBorder)
        self._container = AppKit.NSView.alloc().initWithFrame_(
            AppKit.NSMakeRect(0, 0, _SCROLL_W - 4, _SCROLL_H - 4)
        )
        self.scroll.setDocumentView_(self._container)
        view.addSubview_(self.scroll)

        add = AppKit.NSButton.buttonWithTitle_target_action_("+", self, "addAction:")
        add.setBezelStyle_(AppKit.NSBezelStyleCircular)
        add.setFont_(AppKit.NSFont.boldSystemFontOfSize_(14))
        add.setFrame_(AppKit.NSMakeRect(_SCROLL_X, 16, 28, 28))
        view.addSubview_(add)

        paste = AppKit.NSButton.buttonWithTitle_target_action_(
            "Paste List…", self, "pasteListAction:"
        )
        paste.setBezelStyle_(AppKit.NSBezelStyleRounded)
        paste.setFrame_(AppKit.NSMakeRect(_SCROLL_X + 40, 16, 120, 28))
        view.addSubview_(paste)

        export = AppKit.NSButton.buttonWithTitle_target_action_(
            "Export…", self, "exportAction:"
        )
        export.setBezelStyle_(AppKit.NSBezelStyleRounded)
        export.setFrame_(AppKit.NSMakeRect(196, 16, 92, 28))
        view.addSubview_(export)

        imp = AppKit.NSButton.buttonWithTitle_target_action_(
            "Import…", self, "importAction:"
        )
        imp.setBezelStyle_(AppKit.NSBezelStyleRounded)
        imp.setFrame_(AppKit.NSMakeRect(296, 16, 92, 28))
        view.addSubview_(imp)

        done = AppKit.NSButton.buttonWithTitle_target_action_(
            "Done", self, "doneAction:"
        )
        done.setBezelStyle_(AppKit.NSBezelStyleRounded)
        done.setKeyEquivalent_("\r")
        done.setFrame_(AppKit.NSMakeRect(_WIN_W - 116, 16, 100, 28))
        view.addSubview_(done)

    # -- wiring ---------------------------------------------------------------

    @objc.python_method
    def set_corrections(self, corrections) -> None:
        self._corrections = corrections

    @objc.python_method
    def reload(self) -> None:
        """Re-read the dictionary into the rows (window (re)open)."""
        if self._corrections is not None:
            self._rows = [dict(p) for p in self._corrections.pairs]
            self._rebuild_rows()

    @objc.python_method
    def _push(self) -> None:
        """Persist the current rows (a cleaned copy) into the dictionary."""
        if self._corrections is not None:
            self._corrections.set_pairs(self._rows)

    # -- the row list -----------------------------------------------------------

    @objc.python_method
    def _rebuild_rows(self) -> None:
        """Recreate the row views from self._rows (structure changed)."""
        # Drop the live-field list BEFORE unmounting the old views: their
        # dying edit sessions fire controlTextDidEndEditing_ mid-rebuild,
        # and the stale-field guard must reject them (else they clobber
        # whatever the rebuild's caller just wrote).
        self._row_fields = []
        for sub in list(self._container.subviews()):
            sub.removeFromSuperview()

        width = self._container.frame().size.width
        field_w = int((width - 96) / 2)
        n = len(self._rows)
        total_h = max(int(_SCROLL_H - 4), n * _ROW_H)
        self._container.setFrame_(
            AppKit.NSMakeRect(0, 0, width, total_h)
        )

        if n == 0:
            hint = AppKit.NSTextField.labelWithString_(
                "No rules yet — click + to add one."
            )
            hint.setFont_(AppKit.NSFont.systemFontOfSize_(12))
            hint.setTextColor_(AppKit.NSColor.tertiaryLabelColor())
            hint.setAlignment_(AppKit.NSCenterTextAlignment)
            hint.setFrame_(AppKit.NSMakeRect(0, total_h / 2 - 10, width, 20))
            self._container.addSubview_(hint)
            return

        for i, row in enumerate(self._rows):
            y = total_h - (i + 1) * _ROW_H + 5
            left = self._field(
                "heard as", AppKit.NSMakeRect(0, y, field_w, _FIELD_H)
            )
            left.setIdentifier_(f"{i}:from")
            left.setStringValue_(row.get("from", ""))
            self._container.addSubview_(left)

            arrow = AppKit.NSTextField.labelWithString_("→")
            arrow.setFont_(AppKit.NSFont.systemFontOfSize_(12))
            arrow.setTextColor_(AppKit.NSColor.secondaryLabelColor())
            arrow.setAlignment_(AppKit.NSCenterTextAlignment)
            arrow.setFrame_(AppKit.NSMakeRect(field_w + 6, y + 3, 20, 18))
            self._container.addSubview_(arrow)

            right = self._field(
                "replace with", AppKit.NSMakeRect(field_w + 32, y, field_w, _FIELD_H)
            )
            right.setIdentifier_(f"{i}:to")
            right.setStringValue_(row.get("to", ""))
            self._container.addSubview_(right)

            minus = AppKit.NSButton.buttonWithTitle_target_action_(
                "−", self, "removeRow:"
            )
            minus.setBezelStyle_(AppKit.NSBezelStyleCircular)
            minus.setFont_(AppKit.NSFont.boldSystemFontOfSize_(13))
            minus.setTag_(i)
            minus.setFrame_(AppKit.NSMakeRect(width - 28, y, 24, 24))
            self._container.addSubview_(minus)

            self._row_fields.append((left, right))

    @objc.python_method
    def _field(self, placeholder: str, frame) -> AppKit.NSTextField:
        """A plain, standard editable system text field — click and type."""
        field = ListTextField.alloc().initWithFrame_(frame)
        field.setBezeled_(True)
        field.setEditable_(True)
        field.setSelectable_(True)
        field.setFont_(AppKit.NSFont.systemFontOfSize_(12))
        field.setPlaceholderString_(placeholder)
        field.setDelegate_(self)
        return field

    @objc.python_method
    def _sync_from_fields(self) -> None:
        """Pull the current field contents into self._rows (before a
        structural change rebuilds the views)."""
        for i, (left, right) in enumerate(self._row_fields):
            if i < len(self._rows):
                self._rows[i]["from"] = str(left.stringValue())
                self._rows[i]["to"] = str(right.stringValue())

    # -- actions ----------------------------------------------------------------

    def addAction_(self, _sender) -> None:
        try:
            self._sync_from_fields()
            self._rows.append({"from": "", "to": ""})
            self._push()
            self._rebuild_rows()
            self._scroll_to_bottom()
            # Focus the new left field on the next run-loop turn (changing
            # the first responder while the button still tracks the click
            # can be discarded).
            self.performSelector_withObject_afterDelay_(
                "focusNewRow:", None, 0.05
            )
        except Exception:
            log.exception("corrections add failed (recovered)")

    def focusNewRow_(self, _sender) -> None:
        try:
            if self._row_fields:
                self.makeFirstResponder_(self._row_fields[-1][0])
        except Exception:
            log.exception("corrections focusNewRow failed (recovered)")

    def removeRow_(self, sender) -> None:
        try:
            i = int(sender.tag())
            self._sync_from_fields()
            if 0 <= i < len(self._rows):
                del self._rows[i]
            self._push()
            self._rebuild_rows()
        except Exception:
            log.exception("corrections removeRow failed (recovered)")

    def doneAction_(self, _sender) -> None:
        try:
            self._sync_from_fields()
            self._push()
            self.performClose_(None)
        except Exception:
            log.exception("corrections done failed (recovered)")

    # -- export / import ------------------------------------------------------------

    def exportAction_(self, _sender) -> None:
        """Save the whole dictionary to a JSON file the user picks."""
        try:
            self._sync_from_fields()
            self._push()
            panel = AppKit.NSSavePanel.savePanel()
            panel.setNameFieldStringValue_("listen-corrections.json")
            panel.setCanCreateDirectories_(True)
            if panel.runModal() != AppKit.NSModalResponseOK:
                return
            self._do_export(str(panel.url().path()), [
                dict(p) for p in self._corrections.pairs
            ])
        except Exception:
            log.exception("corrections export failed (recovered)")

    @objc.python_method
    def _do_export(self, path: str, pairs: list[dict]) -> None:
        Path(path).write_text(
            json.dumps({"pairs": pairs}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        log.info("corrections exported: %d pairs -> %s", len(pairs), path)

    def importAction_(self, _sender) -> None:
        """Load pairs from a JSON file (our export or a bare list); known
        words get their replacement updated, new words are added."""
        try:
            panel = AppKit.NSOpenPanel.openPanel()
            panel.setCanChooseFiles_(True)
            panel.setCanChooseDirectories_(False)
            panel.setAllowsMultipleSelection_(False)
            try:
                import UniformTypeIdentifiers

                panel.setAllowedContentTypes_(
                    [UniformTypeIdentifiers.UTType.typeWithFilenameExtension_("json")]
                )
            except Exception:
                panel.setAllowedFileTypes_(["json"])
            if panel.runModal() != AppKit.NSModalResponseOK:
                return
            try:
                self._do_import(str(panel.url().path()))
            except Exception:
                log.exception("corrections import failed (recovered)")
                alert = AppKit.NSAlert.alloc().init()
                alert.setMessageText_("Could not read that file")
                alert.setInformativeText_(
                    "Expected a corrections export — JSON with a pairs list."
                )
                alert.runModal()
        except Exception:
            log.exception("corrections import panel failed (recovered)")

    @objc.python_method
    def _do_import(self, path: str) -> None:
        incoming = parse_pairs_text(Path(path).read_text(encoding="utf-8"))
        self._sync_from_fields()
        self._rows, _n_up, _n_add = merge_into(self._rows, incoming)
        self._push()
        self._rows = [dict(p) for p in self._corrections.pairs]
        self._rebuild_rows()
        self._scroll_to_bottom()
        log.info(
            "corrections imported from %s: %d updated, %d added",
            path, _n_up, _n_add,
        )

    # -- pasting a list straight into a field -------------------------------------

    def performKeyEquivalent_(self, event) -> bool:
        """Intercept Cmd+V aimed at a row field. While a field is being
        edited the first responder is the shared field editor, so paste:
        never reaches the field itself — this runs BEFORE menu key
        equivalents. A multi-line clipboard becomes rows; a normal paste
        falls through to the field editor via the Edit menu, untouched."""
        try:
            flags = event.modifierFlags()
            if (
                flags & AppKit.NSCommandKeyMask
                and str(event.charactersIgnoringModifiers()) == "v"
            ):
                fr = self.firstResponder()
                field = fr.delegate() if isinstance(fr, AppKit.NSTextView) else fr
                if isinstance(field, ListTextField):
                    pb = AppKit.NSPasteboard.generalPasteboard()
                    text = str(
                        pb.stringForType_(AppKit.NSPasteboardTypeString) or ""
                    )
                    if "\n" in text:
                        self.handle_list_paste(field, text)
                        return True
        except Exception:
            log.exception("corrections key-equivalent failed (recovered)")
        return objc.super(CorrectionsWindow, self).performKeyEquivalent_(event)

    @objc.python_method
    def handle_list_paste(self, field: "ListTextField", text: str) -> None:
        """A multi-line paste into a row field. Into a LEFT field: line 1
        becomes this row's "heard as", the rest insert new rows below. Into
        a RIGHT field: line 1..N fill this row's and the following rows'
        "replace with" (missing rows are created with an empty left side)."""
        lines = self._lines(text)
        if not lines:
            return
        try:
            i, _, side = str(field.identifier()).partition(":")
            i = int(i)
            self._sync_from_fields()
            if side == "from":
                if not str(self._rows[i].get("from", "")).strip():
                    self._rows[i]["from"] = lines[0]  # empty row takes line 1
                    new_lines = lines[1:]
                else:  # a filled row is never clobbered — grow below it
                    new_lines = lines
                for k, extra in enumerate(new_lines):
                    self._rows.insert(i + 1 + k, {"from": extra, "to": ""})
            else:  # "to" — fill downward
                for k, value in enumerate(lines):
                    j = i + k
                    while j >= len(self._rows):
                        self._rows.append({"from": "", "to": ""})
                    self._rows[j]["to"] = value
            self._push()
            # NOTE: _rows stays as-is (not re-read from the store) — an
            # overflow right-paste creates empty-left rows that set_pairs
            # keeps out of the matcher/file; the editor shows them until
            # they get a left side or are deleted.
            self._rebuild_rows()
            self._scroll_to_bottom()
            self._focus_after = (i, 0 if side == "from" else 1)
            self.performSelector_withObject_afterDelay_(
                "refocusAfterPaste:", None, 0.05
            )
        except Exception:
            log.exception("corrections list paste failed (recovered)")

    def refocusAfterPaste_(self, _sender) -> None:
        try:
            pos = getattr(self, "_focus_after", None)
            if pos and self._row_fields:
                i, s = pos
                pair = self._row_fields[min(i, len(self._row_fields) - 1)]
                self.makeFirstResponder_(pair[s])
        except Exception:
            log.exception("corrections refocus failed (recovered)")

    # -- bulk paste sheet --------------------------------------------------------

    @objc.python_method
    def _lines(self, text: str) -> list[str]:
        """Non-empty, trimmed lines of a pasted list."""
        return [ln.strip() for ln in text.splitlines() if ln.strip()]

    @objc.python_method
    def _sheet_textview(self, frame) -> AppKit.NSTextView:
        """An editable plain-text NSTextView inside a bordered scroll view."""
        w, h = frame.size.width, frame.size.height
        tv = AppKit.NSTextView.alloc().initWithFrame_(
            AppKit.NSMakeRect(0, 0, w, h)
        )
        tv.setEditable_(True)
        tv.setSelectable_(True)
        tv.setRichText_(False)
        tv.setAllowsUndo_(True)
        tv.setUsesFindBar_(False)
        tv.setFont_(AppKit.NSFont.systemFontOfSize_(12))
        tv.setVerticallyResizable_(True)
        tv.setHorizontallyResizable_(False)
        tv.setAutoresizingMask_(AppKit.NSViewNotSizable)
        tv.setMinSize_(AppKit.NSSize(0.0, h))
        tv.setMaxSize_(AppKit.NSSize(w, 1e7))
        tv.textContainer().setContainerSize_(AppKit.NSSize(w, 1e7))
        tv.textContainer().setWidthTracksTextView_(True)
        tv.setDelegate_(self)
        scroll = AppKit.NSScrollView.alloc().initWithFrame_(frame)
        scroll.setBorderType_(AppKit.NSBezelBorder)
        scroll.setHasVerticalScroller_(True)
        scroll.setAutohidesScrollers_(True)
        scroll.setDocumentView_(tv)
        return tv

    def pasteListAction_(self, _sender) -> None:
        """Open the bulk-paste sheet: two lists in, pairs out (line to line)."""
        try:
            sheet = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                AppKit.NSMakeRect(0, 0, _SHEET_W, _SHEET_H),
                AppKit.NSTitledWindowMask,
                AppKit.NSBackingStoreBuffered,
                False,
            )
            sheet.setTitle_("Paste List")
            sheet.setReleasedWhenClosed_(False)
            view = AppKit.NSView.alloc().initWithFrame_(
                AppKit.NSMakeRect(0, 0, _SHEET_W, _SHEET_H)
            )
            sheet.setContentView_(view)

            head = AppKit.NSTextField.labelWithString_(
                "Paste your two lists — line N on the left is auto-replaced "
                "with line N on the right. Blank lines are skipped."
            )
            head.setFont_(AppKit.NSFont.systemFontOfSize_(12))
            head.setTextColor_(AppKit.NSColor.secondaryLabelColor())
            head.setLineBreakMode_(AppKit.NSLineBreakByWordWrapping)
            head.setFrame_(AppKit.NSMakeRect(16, 262, _SHEET_W - 32, 40))
            view.addSubview_(head)

            self._sheet_left = self._sheet_textview(
                AppKit.NSMakeRect(16, 122, _COL_W, _TV_H)
            )
            self._sheet_right = self._sheet_textview(
                AppKit.NSMakeRect(16 + _COL_W + 16, 122, _COL_W, _TV_H)
            )
            view.addSubview_(self._sheet_left.enclosingScrollView())
            view.addSubview_(self._sheet_right.enclosingScrollView())

            for x, title in ((16, "Heard as — one per line"),
                             (16 + _COL_W + 16, "Replace with — one per line")):
                lab = AppKit.NSTextField.labelWithString_(title)
                lab.setFont_(AppKit.NSFont.boldSystemFontOfSize_(11))
                lab.setTextColor_(AppKit.NSColor.secondaryLabelColor())
                lab.setFrame_(AppKit.NSMakeRect(x, 242, _COL_W, 16))
                view.addSubview_(lab)

            self._sheet_left_count = AppKit.NSTextField.labelWithString_("0 lines")
            self._sheet_left_count.setFont_(AppKit.NSFont.systemFontOfSize_(11))
            self._sheet_left_count.setTextColor_(AppKit.NSColor.tertiaryLabelColor())
            self._sheet_left_count.setFrame_(AppKit.NSMakeRect(16, 102, _COL_W, 14))
            view.addSubview_(self._sheet_left_count)
            self._sheet_right_count = AppKit.NSTextField.labelWithString_("0 lines")
            self._sheet_right_count.setFont_(AppKit.NSFont.systemFontOfSize_(11))
            self._sheet_right_count.setTextColor_(AppKit.NSColor.tertiaryLabelColor())
            self._sheet_right_count.setFrame_(
                AppKit.NSMakeRect(16 + _COL_W + 16, 102, _COL_W, 14)
            )
            view.addSubview_(self._sheet_right_count)

            self._sheet_hint = AppKit.NSTextField.labelWithString_(
                "The line counts must match."
            )
            self._sheet_hint.setFont_(AppKit.NSFont.systemFontOfSize_(11))
            self._sheet_hint.setTextColor_(AppKit.NSColor.systemRedColor())
            self._sheet_hint.setAlignment_(AppKit.NSCenterTextAlignment)
            self._sheet_hint.setHidden_(True)
            self._sheet_hint.setFrame_(AppKit.NSMakeRect(16, 66, _SHEET_W - 32, 16))
            view.addSubview_(self._sheet_hint)

            cancel = AppKit.NSButton.buttonWithTitle_target_action_(
                "Cancel", self, "sheetCancelAction:"
            )
            cancel.setBezelStyle_(AppKit.NSBezelStyleRounded)
            cancel.setKeyEquivalent_("\x1b")
            cancel.setFrame_(AppKit.NSMakeRect(16, 18, 110, 28))
            view.addSubview_(cancel)

            self._sheet_add = AppKit.NSButton.buttonWithTitle_target_action_(
                "Add Pairs", self, "sheetAddAction:"
            )
            self._sheet_add.setBezelStyle_(AppKit.NSBezelStyleRounded)
            self._sheet_add.setKeyEquivalent_("\r")
            self._sheet_add.setEnabled_(False)
            self._sheet_add.setFrame_(AppKit.NSMakeRect(_SHEET_W - 166, 18, 150, 28))
            view.addSubview_(self._sheet_add)

            self._sheet_win = sheet
            self.beginSheet_completionHandler_(sheet, None)
            # Focus the left list once the sheet has settled (same tracking
            # caveat as the + button).
            self.performSelector_withObject_afterDelay_("sheetFocus:", None, 0.05)
        except Exception:
            log.exception("corrections paste-list sheet failed (recovered)")

    def sheetFocus_(self, _sender) -> None:
        try:
            if getattr(self, "_sheet_win", None) is not None:
                self._sheet_win.makeFirstResponder_(self._sheet_left)
        except Exception:
            log.exception("corrections sheet focus failed (recovered)")

    def textDidChange_(self, _notification) -> None:
        """Live line counts; Add is armed only when both lists line up."""
        try:
            if getattr(self, "_sheet_win", None) is None:
                return
            nl = len(self._lines(str(self._sheet_left.string())))
            nr = len(self._lines(str(self._sheet_right.string())))
            self._sheet_left_count.setStringValue_(
                f"{nl} line{'s' if nl != 1 else ''}"
            )
            self._sheet_right_count.setStringValue_(
                f"{nr} line{'s' if nr != 1 else ''}"
            )
            ok = nl > 0 and nl == nr
            self._sheet_hint.setHidden_(ok or nl == 0 or nr == 0)
            self._sheet_add.setEnabled_(ok)
            self._sheet_add.setTitle_(
                f"Add {nl} Pair{'s' if nl != 1 else ''}" if ok else "Add Pairs"
            )
        except Exception:
            log.exception("corrections sheet textDidChange failed (recovered)")

    def sheetAddAction_(self, _sender) -> None:
        try:
            left = self._lines(str(self._sheet_left.string()))
            right = self._lines(str(self._sheet_right.string()))
            if not left or len(left) != len(right):
                return  # counts drifted since the button was armed
            self._sync_from_fields()
            # Merge (shared with Import): an already-known "heard as" gets its
            # "replace with" updated in place; new words become new rows.
            self._rows = merge_into(
                self._rows, [{"from": s, "to": d} for s, d in zip(left, right)]
            )[0]
            self._push()
            self._rows = [dict(p) for p in self._corrections.pairs]
            self._rebuild_rows()
            self._scroll_to_bottom()
            self._close_sheet()
        except Exception:
            log.exception("corrections sheet add failed (recovered)")

    def sheetCancelAction_(self, _sender) -> None:
        try:
            self._close_sheet()
        except Exception:
            log.exception("corrections sheet cancel failed (recovered)")

    @objc.python_method
    def _close_sheet(self) -> None:
        sheet = getattr(self, "_sheet_win", None)
        if sheet is not None:
            self.endSheet_(sheet)
            sheet.orderOut_(None)
        self._sheet_win = None

    # -- field delegate -----------------------------------------------------------

    def controlTextDidEndEditing_(self, notification) -> None:
        """A field lost focus (Tab, Enter, click elsewhere) — persist."""
        try:
            field = notification.object()
            # A rebuild (list paste / row removal) unmounts fields; their
            # dying edit sessions fire this notification with STALE values
            # that must not overwrite what the rebuild just wrote.
            if not any(field is l or field is r for l, r in self._row_fields):
                return
            ident = str(field.identifier())
            i, _, side = ident.partition(":")
            i = int(i)
            if side in ("from", "to") and 0 <= i < len(self._rows):
                self._rows[i][side] = str(field.stringValue())
                self._push()
        except Exception:
            log.exception("corrections endEdit failed (recovered)")

    # -- helpers -----------------------------------------------------------------

    @objc.python_method
    def _scroll_to_bottom(self) -> None:
        try:
            doc_h = self._container.frame().size.height
            vis_h = self.scroll.contentView().bounds().size.height
            if doc_h > vis_h:
                self.scroll.contentView().scrollToPoint_(
                    AppKit.NSMakePoint(0, doc_h - vis_h)
                )
                self.scroll.reflectScrolledClipView_(self.scroll.contentView())
        except Exception:
            log.exception("corrections scroll failed (recovered)")

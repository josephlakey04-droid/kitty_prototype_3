#!/usr/bin/env python3
"""
Desktop Kitten - a little pixel-art black cat that lives on your screen.

This version draws the cat as a native macOS window (via pyobjc) instead
of a Tk widget, because Tk's own transparency support is broken on this
machine - it makes the whole window invisible instead of just clearing
the background. A plain NSImageView on a borderless, non-opaque NSWindow
sidesteps that entirely.

Tkinter is still used, just invisibly (its root window is withdrawn) -
for the animation timer, the right-click menu, file dialogs, the speech
bubble, and the coding-question console. None of those need transparency,
so Tk handles them fine.

Needs: pip3 install pyobjc-framework-Cocoa

Run it with:  python3 desktop_pet.py
Quit it from the right-click menu, or Ctrl+C in the terminal.
"""

import sys
import os
import time
import json
import random
import threading
import subprocess
import urllib.request
import tkinter as tk
from tkinter import filedialog, messagebox
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("This needs Pillow. Install it with:\n    pip3 install --user Pillow")
    sys.exit(1)

try:
    import AppKit
except ImportError:
    print("This needs pyobjc. Install it with:\n    pip3 install pyobjc-framework-Cocoa")
    sys.exit(1)

import sprites

# ---------------------------------------------------------------- CONFIG --
SCALE = 3                    # sprite pixel scale (bigger = bigger cat)
WALK_SPEED = 3                 # pixels per tick while walking
TICK_MS = 120                    # animation/behavior/input-poll tick, ms
TOP_MARGIN = 30                   # keep clear of the menu bar
BOTTOM_MARGIN = 90               # keep clear of the Dock
ALERT_RADIUS = 180               # how close the mouse gets before the cat notices
CURIOUS_RADIUS = 350               # wider range where a walking cat drifts toward the cursor
DRAG_THRESHOLD = 4               # pixels of movement before a click counts as a drag
DOUBLE_CLICK_SECS = 0.4            # max gap between clicks to count as a double-click
INACTIVITY_SLEEP_SECS = 300         # nap after this many seconds of no mouse movement
DESKTOP = Path.home() / "Desktop"
DOWNLOADS = Path.home() / "Downloads"

# Model used for "Ask a coding question..." - needs your own API key, see
# the console window for setup. Swap to "claude-haiku-4-5-20251001" for a
# cheaper/faster option.
ANTHROPIC_MODEL = "claude-sonnet-5"

DEBUG = True
# ----------------------------------------------------------------------- --


def log(*args):
    if DEBUG:
        print("[kitten]", *args)


class DesktopPet:
    def __init__(self):
        log("creating hidden Tk root (timer/menu/dialogs only)...")
        self.root = tk.Tk()
        self.root.withdraw()

        sample = sprites.base_frame("idle", "right", 0)
        self.pet_w = sample.width * SCALE
        self.pet_h = sample.height * SCALE

        self.screen_w = self.root.winfo_screenwidth()
        self.screen_h = self.root.winfo_screenheight()
        self.x = random.randint(50, self.screen_w - 150)
        self.y = random.randint(TOP_MARGIN, self.screen_h - BOTTOM_MARGIN - self.pet_h)
        log(f"screen is {self.screen_w}x{self.screen_h}, cat placed at ({self.x},{self.y}), "
            f"sprite size {self.pet_w}x{self.pet_h}")

        self._create_ns_window()

        self.direction = random.choice(["left", "right"])
        self.pose = "idle"
        self.anim_frame = 0
        self.state = "idle"          # idle, walk, sleep, alert, pounce, play, stretch, dragged
        self.state_timer = 0
        self.cooldown_until = 0
        self.chase_mode = False
        self.target_x, self.target_y = self.x, self.y
        self.last_mouse_pos = (self.root.winfo_pointerx(), self.root.winfo_pointery())
        self.last_activity_time = time.time()

        self.dragging = False
        self.drag_moved = False
        self.drag_offset = (0, 0)
        self.left_was_down = False
        self.right_was_down = False
        self.last_click_time = 0

        self.watch_desktop = False
        self._desktop_snapshot = None

        self.bubble = None
        self._gaze = (0, 0)
        self.console_win = None

        self._build_menu()
        self._render()
        self.root.after(TICK_MS, self.tick)

    # ------------------------------------------------------ native window
    def _create_ns_window(self):
        rect = ((self.x, self._cocoa_y(self.y)), (self.pet_w, self.pet_h))
        self.ns_window = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, AppKit.NSWindowStyleMaskBorderless, AppKit.NSBackingStoreBuffered, False
        )
        self.ns_window.setOpaque_(False)
        self.ns_window.setBackgroundColor_(AppKit.NSColor.clearColor())
        self.ns_window.setHasShadow_(False)
        self.ns_window.setLevel_(AppKit.NSFloatingWindowLevel)
        self.ns_window.setIgnoresMouseEvents_(True)  # we handle input via polling instead

        self.image_view = AppKit.NSImageView.alloc().initWithFrame_(((0, 0), (self.pet_w, self.pet_h)))
        self.image_view.setImageScaling_(AppKit.NSImageScaleNone)
        self.ns_window.setContentView_(self.image_view)
        self.ns_window.orderFrontRegardless()
        log("native transparent window created")

    def _cocoa_y(self, tk_y):
        # Cocoa's origin is bottom-left with Y increasing upward; Tk's
        # (and all our own position logic) is top-left with Y increasing
        # downward. Flip only at the point we talk to Cocoa.
        return self.screen_h - tk_y - self.pet_h

    def _pil_to_nsimage(self, pil_img):
        pil_img = pil_img.convert("RGBA")
        w, h = pil_img.size
        raw = pil_img.tobytes("raw", "RGBA")
        bitmap = AppKit.NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
            None, w, h, 8, 4, True, False, AppKit.NSDeviceRGBColorSpace, w * 4, 32
        )
        bitmap.bitmapData()[:] = raw
        image = AppKit.NSImage.alloc().initWithSize_((w, h))
        image.addRepresentation_(bitmap)
        return image

    # ----------------------------------------------------------- render --
    def _current_pil_frame(self, mx, my):
        frame_idx = self.anim_frame % sprites.FRAME_COUNTS.get(self.pose, 1)
        img = sprites.base_frame(self.pose, self.direction, frame_idx)
        anchors = sprites.eye_anchor_points(self.pose, self.direction, frame_idx)
        if anchors:
            cat_cx = self.x + self.pet_w / 2
            cat_cy = self.y + self.pet_h / 2
            gx = 1 if mx > cat_cx + 10 else (-1 if mx < cat_cx - 10 else 0)
            gy = 1 if my > cat_cy + 10 else (-1 if my < cat_cy - 10 else 0)
            self._gaze = (gx, gy)
            img = sprites.with_pupils(img, anchors, gx, gy)
        return img.resize((self.pet_w, self.pet_h), Image.NEAREST)

    def _render(self):
        mx, my = self.root.winfo_pointerx(), self.root.winfo_pointery()
        cat_img = self._current_pil_frame(mx, my)
        try:
            ns_image = self._pil_to_nsimage(cat_img)
            self.image_view.setImage_(ns_image)
        except Exception as e:
            log("frame render failed:", repr(e))
        self.ns_window.setFrameOrigin_((int(self.x), int(self._cocoa_y(self.y))))

    # ------------------------------------------------------------- menu --
    def _build_menu(self):
        m = tk.Menu(self.root, tearoff=0)
        m.add_command(label="Ask a coding question...", command=self.open_coding_console)
        m.add_separator()
        m.add_command(label="Pet the cat", command=self.do_pet)
        m.add_command(label="Toggle chase mode (or double-click the cat)", command=self.toggle_chase_mode)
        m.add_separator()
        m.add_command(label="Tidy up Desktop by file type", command=self.tidy_desktop)
        m.add_command(label="Find old Downloads (30+ days)", command=self.find_old_downloads)
        m.add_command(label="Count files in a folder...", command=self.count_folder)
        m.add_command(label="Open Desktop in Finder", command=lambda: self.open_in_finder(DESKTOP))
        m.add_command(label="Open Downloads in Finder", command=lambda: self.open_in_finder(DOWNLOADS))
        self.watch_var = tk.BooleanVar(value=False)
        m.add_checkbutton(label="Watch Desktop for new files", variable=self.watch_var,
                           command=lambda: setattr(self, "watch_desktop", self.watch_var.get()))
        m.add_separator()
        m.add_command(label="Nap", command=self.force_sleep)
        m.add_command(label="Quit", command=self.quit_app)
        self.menu = m

    def show_menu_at(self, x, y):
        try:
            self.menu.tk_popup(x, y)
        finally:
            self.menu.grab_release()

    def quit_app(self):
        try:
            self.ns_window.orderOut_(None)
            self.ns_window.close()
        except Exception:
            pass
        self.root.destroy()

    # ------------------------------------------------- coding console --
    def open_coding_console(self):
        if self.console_win is not None and self.console_win.winfo_exists():
            self.console_win.deiconify()
            self.console_win.lift()
            self.console_entry.focus_set()
            return

        win = tk.Toplevel(self.root)
        win.title("Desktop Kitten - Coding Help")
        win.geometry("480x360")

        text = tk.Text(win, wrap="word", state="disabled")
        text.pack(fill="both", expand=True, padx=6, pady=(6, 0))

        entry_frame = tk.Frame(win)
        entry_frame.pack(fill="x", padx=6, pady=6)
        entry = tk.Entry(entry_frame)
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", lambda e: self._ask_coding_question())
        btn = tk.Button(entry_frame, text="Ask", command=self._ask_coding_question)
        btn.pack(side="left", padx=(6, 0))

        self.console_win = win
        self.console_text = text
        self.console_entry = entry
        entry.focus_set()

        if not os.environ.get("ANTHROPIC_API_KEY"):
            self._console_append(
                "No ANTHROPIC_API_KEY found in your environment, so questions won't "
                "get real answers yet.\n\nIn Terminal, before running the cat:\n"
                "  export ANTHROPIC_API_KEY=sk-ant-...\n"
                "(get a key at console.anthropic.com - this uses your own paid API "
                "usage, separate from any Claude subscription)\n\n"
                "Then quit and restart the cat.\n\n"
            )

    def _console_append(self, txt):
        self.console_text.configure(state="normal")
        self.console_text.insert("end", txt)
        self.console_text.see("end")
        self.console_text.configure(state="disabled")

    def _ask_coding_question(self):
        q = self.console_entry.get().strip()
        if not q:
            return
        self.console_entry.delete(0, tk.END)
        self._console_append(f"You: {q}\n")
        threading.Thread(target=self._threaded_ask, args=(q,), daemon=True).start()

    def _threaded_ask(self, question):
        answer = self._call_claude(question)
        self.root.after(0, lambda: self._console_append(f"Kitty: {answer}\n\n"))

    def _call_claude(self, question):
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            return "(no ANTHROPIC_API_KEY set - see instructions above)"
        try:
            body = json.dumps({
                "model": ANTHROPIC_MODEL,
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": question}],
            }).encode("utf-8")
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                data=body,
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            parts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
            return "\n".join(parts) if parts else "(empty response)"
        except Exception as e:
            return f"(error calling the API: {e})"

    # -------------------------------------------------------- interaction
    def do_pet(self):
        self.pose = "alert"
        self.say(random.choice(["mrrp!", "purr~", ":3", "mew"]))
        self.state = "idle"
        self.state_timer = 0
        self.cooldown_until = time.time() + 2

    def toggle_chase_mode(self, event=None):
        self.chase_mode = not self.chase_mode
        self.say("chase mode on!" if self.chase_mode else "chase mode off")
        self.state = "idle"
        self.state_timer = 0

    def force_sleep(self):
        self.state = "sleep"
        self.state_timer = 0

    def say(self, text):
        if self.bubble is not None:
            try:
                self.bubble.destroy()
            except tk.TclError:
                pass
        b = tk.Toplevel(self.root)
        b.overrideredirect(True)
        b.attributes("-topmost", True)
        lbl = tk.Label(b, text=text, bg="#fffdf0", fg="#333",
                        font=("Menlo", 11), padx=6, pady=2,
                        relief="solid", bd=1)
        lbl.pack()
        b.update_idletasks()
        bx = int(self.x + self.pet_w / 2 - b.winfo_width() / 2)
        by = int(self.y - b.winfo_height() - 4)
        b.geometry(f"+{bx}+{by}")
        self.bubble = b
        self.root.after(1600, self._clear_bubble)

    def _clear_bubble(self):
        if self.bubble is not None:
            try:
                self.bubble.destroy()
            except tk.TclError:
                pass
            self.bubble = None

    # ------------------------------------------------------ mouse polling
    def _poll_mouse_buttons(self):
        mx, my = self.root.winfo_pointerx(), self.root.winfo_pointery()
        pressed = AppKit.NSEvent.pressedMouseButtons()
        left_down = bool(pressed & 1)
        right_down = bool(pressed & 2)
        within = (self.x <= mx <= self.x + self.pet_w) and (self.y <= my <= self.y + self.pet_h)

        if left_down and not self.left_was_down:
            if within:
                self.dragging = True
                self.drag_moved = False
                self.drag_offset = (mx - self.x, my - self.y)
                self.state = "dragged"
        elif left_down and self.dragging:
            nx, ny = mx - self.drag_offset[0], my - self.drag_offset[1]
            if abs(nx - self.x) > DRAG_THRESHOLD or abs(ny - self.y) > DRAG_THRESHOLD:
                self.drag_moved = True
            self.x = max(0, min(self.screen_w - self.pet_w, nx))
            self.y = max(TOP_MARGIN, min(self.screen_h - BOTTOM_MARGIN - self.pet_h, ny))
        elif not left_down and self.left_was_down and self.dragging:
            self.dragging = False
            now = time.time()
            if not self.drag_moved:
                if now - self.last_click_time < DOUBLE_CLICK_SECS:
                    self.toggle_chase_mode()
                else:
                    self.do_pet()
                self.last_click_time = now
            else:
                # set back down after being carried around - give it a stretch
                self.state = "stretch"
                self.state_timer = 0

        if right_down and not self.right_was_down and within:
            self.show_menu_at(mx, my)

        self.left_was_down = left_down
        self.right_was_down = right_down

    # ---------------------------------------------------------- behavior
    def tick(self):
        self._poll_mouse_buttons()
        if not self.dragging:
            self._behave()
        self.anim_frame += 1
        self._render()
        if self.anim_frame % 25 == 0:
            log(f"alive - pos=({int(self.x)},{int(self.y)}) pose={self.pose} state={self.state}")
        if self.bubble is not None:
            bx = int(self.x + self.pet_w / 2 - self.bubble.winfo_width() / 2)
            by = int(self.y - self.bubble.winfo_height() - 4)
            self.bubble.geometry(f"+{bx}+{by}")
        self.root.after(TICK_MS, self.tick)

    def _pick_roam_target(self):
        self.target_x = random.randint(0, self.screen_w - self.pet_w)
        self.target_y = random.randint(TOP_MARGIN, self.screen_h - BOTTOM_MARGIN - self.pet_h)

    def _step_toward(self, tx, ty, speed):
        dx, dy = tx - self.x, ty - self.y
        d = (dx ** 2 + dy ** 2) ** 0.5
        if d < 2:
            return True  # arrived
        self.x += speed * dx / d
        self.y += speed * dy / d
        self.x = max(0, min(self.screen_w - self.pet_w, self.x))
        self.y = max(TOP_MARGIN, min(self.screen_h - BOTTOM_MARGIN - self.pet_h, self.y))
        self.direction = "right" if dx > 0 else "left"
        return False

    def _behave(self):
        mx, my = self.root.winfo_pointerx(), self.root.winfo_pointery()
        cat_cx = self.x + self.pet_w / 2
        cat_cy = self.y + self.pet_h / 2
        dist = ((mx - cat_cx) ** 2 + (my - cat_cy) ** 2) ** 0.5
        now = time.time()

        if abs(mx - self.last_mouse_pos[0]) > 2 or abs(my - self.last_mouse_pos[1]) > 2:
            self.last_mouse_pos = (mx, my)
            self.last_activity_time = now
        elif (now - self.last_activity_time > INACTIVITY_SLEEP_SECS
                and self.state not in ("sleep", "dragged") and not self.chase_mode):
            self.state = "sleep"
            self.state_timer = 0

        if self.chase_mode:
            self.pose = "walk" if dist > 15 else "play"
            self._step_toward(mx - self.pet_w / 2, my - self.pet_h / 2, WALK_SPEED * 2)
            return

        if (self.state in ("idle", "walk") and dist < ALERT_RADIUS
                and now > self.cooldown_until):
            self.state = "alert"
            self.state_timer = 0
            self.cooldown_until = now + 0.8
            self.direction = "right" if mx > cat_cx else "left"

        self.state_timer += 1

        if self.state == "alert":
            self.pose = "alert"
            self.direction = "right" if mx > cat_cx else "left"
            if self.state_timer > 3:
                self.state = "pounce"
                self.state_timer = 0
        elif self.state == "pounce":
            self.pose = "pounce"
            if dist > 25:
                self._step_toward(mx - self.pet_w / 2, my - self.pet_h / 2, 5)
            if self.state_timer > 6:
                self.state = "play" if dist < ALERT_RADIUS * 1.4 else "idle"
                self.state_timer = 0
        elif self.state == "play":
            self.pose = "play"
            self.direction = "right" if mx > cat_cx else "left"
            if self.state_timer > 12 or dist > ALERT_RADIUS * 1.8:
                self.state = "idle"
                self.state_timer = 0
        elif self.state == "stretch":
            self.pose = "stretch"
            if self.state_timer > 8:
                self.state = "idle"
                self.state_timer = 0
        elif self.state == "sleep":
            self.pose = "sleep"
            if self.state_timer > random.randint(40, 90):
                self.state = "stretch"
                self.state_timer = 0
        elif self.state == "walk":
            self.pose = "walk"
            if dist < CURIOUS_RADIUS:
                self._step_toward(mx - self.pet_w / 2, my - self.pet_h / 2, WALK_SPEED)
            else:
                arrived = self._step_toward(self.target_x, self.target_y, WALK_SPEED)
                if arrived:
                    self._pick_roam_target()
            if self.state_timer > random.randint(40, 90):
                self.state = random.choice(["idle", "idle", "walk", "sleep"])
                self.state_timer = 0
        else:  # idle (sitting)
            self.pose = "idle"
            if self.state_timer > random.randint(15, 40):
                self.state = random.choice(["walk", "walk", "idle", "sleep", "stretch"])
                if self.state == "walk":
                    self._pick_roam_target()
                self.direction = random.choice(["left", "right"])
                self.state_timer = 0

        if self.watch_desktop and self.anim_frame % 25 == 0:
            self._check_desktop()

    # ------------------------------------------------------- file tasks --
    def open_in_finder(self, path):
        if not path.exists():
            messagebox.showinfo("Desktop Kitten", f"Couldn't find {path}.")
            return
        subprocess.run(["open", str(path)])
        self.say("here you go!")

    def _check_desktop(self):
        try:
            current = {p.name for p in DESKTOP.iterdir()}
        except FileNotFoundError:
            return
        if self._desktop_snapshot is None:
            self._desktop_snapshot = current
            return
        new_items = current - self._desktop_snapshot
        self._desktop_snapshot = current
        if new_items:
            name = next(iter(new_items))
            self.say(f"new file: {name[:18]}")

    def tidy_desktop(self):
        if not DESKTOP.exists():
            messagebox.showinfo("Desktop Kitten", "Couldn't find your Desktop folder.")
            return
        if not messagebox.askyesno(
            "Desktop Kitten",
            "I'll sort loose files on your Desktop into folders "
            "(Images, Documents, Other, ...) by file type.\n\n"
            "Nothing gets deleted, only moved. Go ahead?"
        ):
            return
        buckets = {
            "Images": {".png", ".jpg", ".jpeg", ".gif", ".heic", ".webp", ".svg"},
            "Documents": {".pdf", ".doc", ".docx", ".txt", ".rtf", ".pages", ".key", ".ppt", ".pptx"},
            "Spreadsheets": {".xls", ".xlsx", ".csv", ".numbers"},
            "Archives": {".zip", ".tar", ".gz", ".dmg"},
            "Code": {".py", ".js", ".html", ".css", ".json", ".sh"},
        }
        moved = 0
        for item in DESKTOP.iterdir():
            if item.is_dir():
                continue
            ext = item.suffix.lower()
            bucket = next((b for b, exts in buckets.items() if ext in exts), "Other")
            dest_dir = DESKTOP / bucket
            dest_dir.mkdir(exist_ok=True)
            try:
                item.rename(dest_dir / item.name)
                moved += 1
            except OSError:
                pass
        self.say(f"tidied {moved} files!")
        messagebox.showinfo("Desktop Kitten", f"Done - moved {moved} file(s) into folders.")

    def find_old_downloads(self):
        if not DOWNLOADS.exists():
            messagebox.showinfo("Desktop Kitten", "Couldn't find your Downloads folder.")
            return
        cutoff = time.time() - 30 * 86400
        old = []
        for item in DOWNLOADS.iterdir():
            if item.is_file():
                try:
                    if item.stat().st_mtime < cutoff:
                        old.append(item.name)
                except OSError:
                    pass
        if not old:
            messagebox.showinfo("Desktop Kitten", "No files older than 30 days in Downloads.")
            return
        preview = "\n".join(old[:25])
        more = f"\n...and {len(old) - 25} more" if len(old) > 25 else ""
        messagebox.showinfo(
            "Desktop Kitten",
            f"{len(old)} file(s) in Downloads are 30+ days old:\n\n{preview}{more}\n\n"
            "(Just a report - I didn't touch anything.)"
        )

    def count_folder(self):
        folder = filedialog.askdirectory(title="Pick a folder for the cat to count")
        if not folder:
            return
        p = Path(folder)
        files = [f for f in p.rglob("*") if f.is_file()]
        total_bytes = sum(f.stat().st_size for f in files if f.exists())
        mb = total_bytes / (1024 * 1024)
        messagebox.showinfo(
            "Desktop Kitten",
            f"{p.name}\n\n{len(files)} file(s)\n{mb:.1f} MB total"
        )

    def run(self):
        log("starting main loop - the cat should be visible now")
        self.root.mainloop()
        log("main loop ended (window was closed)")


if __name__ == "__main__":
    try:
        DesktopPet().run()
    except Exception:
        import traceback
        print("\n--- Desktop Kitten crashed ---")
        traceback.print_exc()
        input("\nPress Enter to close...")

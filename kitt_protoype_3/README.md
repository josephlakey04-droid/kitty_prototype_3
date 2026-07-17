# Desktop Kitten 🐈‍⬛

A pixel-art black cat that lives on your screen: roams anywhere, plays,
sleeps, watches you with its eyes, can be dragged, and does a few small
real file chores. This version draws the cat as a real macOS window
instead of going through Tk, since Tk's own transparency was confirmed
broken on this machine.

## What's new in this version

- **Genuinely see-through background** - no box at all this time. The
  cat is a native macOS image layer (via `pyobjc`), not a Tk widget, so
  it doesn't hit the Tk transparency bug we kept running into.
- **Stretch when set down** - drag the cat somewhere and let go, and
  it stretches before going back to normal (instead of just idling).
- **"Ask a coding question..."** - top of the right-click menu opens a
  small console window where you can ask coding questions and get real
  answers, *if* you've set up your own Anthropic API key (see below).
  This is a separate, paid API - not the same as any Claude subscription
  - and the console will tell you if no key is set.

## Setup (macOS)

1. Install the one new dependency:
   ```
   pip3 install pyobjc-framework-Cocoa
   ```
2. Put `desktop_pet.py` and `sprites.py` together in one folder.
3. **Optional**, for the coding-question console to actually answer:
   ```
   export ANTHROPIC_API_KEY=sk-ant-...
   ```
   (get a key at console.anthropic.com - set this *before* launching the
   cat, in the same Terminal session, or add it to your `~/.zshrc` /
   `~/.bash_profile` so it's always set)
4. Run it:
   ```
   cd /path/to/that/folder
   python3 desktop_pet.py
   ```

It'll print `[kitten] ...` status lines the whole time (set `DEBUG =
False` near the top of `desktop_pet.py` once you don't need them).

## What it does

- **Roams** anywhere on screen, sits, naps, stretches.
- **Reacts to your mouse** - perks up and pounces/paws playfully when
  close, drifts curiously toward it from farther away, eyes track the
  cursor live.
- **Chase mode** - double-click the cat to make it actively follow
  your cursor. Double-click again to stop.
- **Left-click and drag** picks it up; setting it back down triggers a
  stretch. Plain left-click pets it.
- **Right-click** on the cat opens its menu: ask a coding question,
  pet, toggle chase mode, tidy Desktop by file type (moves only, asks
  first, never deletes), find old Downloads, count any folder, open
  Desktop/Downloads in Finder, watch for new files, nap, quit.
- **Auto-naps** after 5 minutes of no mouse movement.

### A note on responsiveness

Dragging and clicking are detected by checking the mouse ~8 times a
second (same as the animation rate) rather than through real-time
event callbacks, since the cat's window deliberately ignores direct
mouse events (that's part of what makes the see-through background
possible). It should feel fine for a desktop pet, just not as
instantaneous as a normal app - if dragging feels laggy, lowering
`TICK_MS` near the top of `desktop_pet.py` (e.g. to `80`) makes it
more responsive at the cost of a bit more CPU use.

### If it overlaps your Dock or menu bar

Adjust `TOP_MARGIN` / `BOTTOM_MARGIN` near the top of `desktop_pet.py`.

### Known limitation

Shows up as a running `python3` process in your Dock while active.

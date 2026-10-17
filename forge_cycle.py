"""Run forges back to back: play the waves, loot, go home, start the next one.

    python forge_cycle.py --live            # full loop; hold F8 to stop
    python forge_cycle.py --live --step loot     # only: walk to the chest, open it, pick up
    python forge_cycle.py --live --step end      # only: chest -> loot -> home
    python forge_cycle.py --live --step start    # only: town -> expedition -> clones -> L

Every step checks the screen before acting (OCR of a known title, or the
chest icon on the minimap) and stops instead of guessing when it doesn't
see what it expects. Positions come from a recorded hand-played cycle
(demos/), in 1920x1080 game coordinates.

Item sorting isn't automated yet: after looting it pauses for SORT_WAIT
seconds so you can sort by hand (0 = skip).
"""
import argparse
import difflib
import os
import time

import cv2
import numpy as np
import pyautogui
from PIL import Image

import forge
import strategy

# --- Positions (1920x1080), from the recorded cycle ------------------------------
MINIMAP = (1662, 10, 1912, 260)          # minimap crop; you are its centre
WAVE_LABEL = (1730, 236, 110, 24)        # "Wave N" under the minimap
KILL_BAR = (1670, 350, 240, 28)          # "Wave 100 : 380 / 440" while a wave is being fought
# Position = how far the minimap's wall layout has shifted from a reference
# minimap taken at the clone spot (icons don't matter, only the grey walls).
MINIMAP_REFERENCE = cv2.imread(os.path.join(os.path.dirname(__file__), "templates", "minimap_reference.png"))
# Map shift at each spot, measured from the recorded cycle:
SPOT_CLONES = (0, 0)                     # arena centre, where the clones are placed
SPOT_CHEST = (0, 47)                     # on the chest (F opens it)
SPOT_PORTAL = (-37, 37)                  # at the open "Head Home" portal
SPOT_TOLERANCE = 3

WAR_CHEST_TITLE = (1300, 80, 320, 50)    # "WAR CHEST"
OPEN_WAR_CHEST = (1428, 813)
VICTORY_TITLE = (700, 50, 520, 90)       # "VICTORY"
VICTORY_CONTINUE = (1335, 763)
TOWN_DIALOG = (780, 680, 600, 50)        # "Let's get back to it, shall we?"
EXPEDITIONS_TITLE = (780, 40, 360, 50)   # "Expeditions"
GREAT_FORGE = (311, 481)
WRATH_10 = (1342, 673)
ELDER_BAR = (1600, 105, 300, 50)         # "177 303 / 177 303 -644"
START = (1678, 901)
# Inventory (open with I): 8x8 slots, slot centre = (x0 + dx*col, y0 + dy*row)
INVENTORY_TITLE = (780, 40, 360, 60)     # "Character"
SLOT_X0, SLOT_DX, SLOT_Y0, SLOT_DY = 1335, 68, 198, 76
TRASH = (1810, 830)
BADGE = cv2.imread(os.path.join(os.path.dirname(__file__), "templates", "new_item_badge.png"))
BADGE_MASK = cv2.imread(os.path.join(os.path.dirname(__file__), "templates", "new_item_badge_mask.png"), 0)
KEEP_MIN_MARKS = 2                       # keep items with a teal !! or !!! stat
# Grate corners where the clones stood in the recording; a clone appears right
# where you right-click, so click the corners themselves.
CLONE_SPOTS = [(470, 305), (1450, 305), (475, 815), (1445, 815)]  # +25 px: feet on the corners
CLONE_CAST_GAP = 1.5                     # seconds between clone casts

TOWN_WALK = [("w", 0.42), ("a", 0.16)]   # spawn -> expedition NPC (recorded)
SORT_WAIT = 0
LOOT_SPEW_WAIT = 15                      # seconds for the chest to finish dropping loot
JIGGLE_STEP = 0.35                       # seconds per back-and-forth step while looting
SECONDS_PER_MINIMAP_PX = 0.012           # walking speed guess; corrected as it walks


GAME = None  # set in main(); used to keep the game focused


class StepFailed(Exception):
    pass


# --- Screen helpers ----------------------------------------------------------------
def text_at(game, box, white_only=True):
    x, y, w, h = box
    crop = game.crop((x, y), (w, h))
    if white_only:
        mask = Image.new("L", crop.size, 255)
        mask.putdata([0 if min(p) > 190 else 255 for p in crop.get_flattened_data()])
        crop = mask
    return forge.ocr(crop).lower()


def fuzzy_in(word, text, cutoff=0.7):
    """word appears in text, allowing a few misread letters ("chav ucter")."""
    if word in text:
        return True
    squashed = text.replace(" ", "")
    n = len(word)
    return any(difflib.SequenceMatcher(None, word, squashed[i:i + n]).ratio() >= cutoff
               for i in range(max(1, len(squashed) - n + 1)))


def sees(game, box, word, white_only=True):
    game.refresh()
    return fuzzy_in(word, text_at(game, box, white_only))


def wait_for(game, box, word, seconds, white_only=True):
    end = time.time() + seconds
    while time.time() < end:
        if forge.stop_pressed():
            raise SystemExit("Stopped.")
        if sees(game, box, word, white_only):
            return True
        time.sleep(0.4)
    return False


def minimap_walls(img_bgr):
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    m = cv2.inRange(hsv, (0, 0, 40), (180, 60, 110)).astype(np.float32)
    m[:30, :] = 0; m[200:, :] = 0; m[:, :8] = 0; m[:, 242:] = 0  # version text, wave label, frame
    m[190:250, 0:70] = 0                                           # forge icon bottom-left
    return cv2.GaussianBlur(m, (5, 5), 0)


REFERENCE_WALLS = minimap_walls(MINIMAP_REFERENCE)
HANNING = cv2.createHanningWindow(REFERENCE_WALLS.shape[::-1], cv2.CV_32F)


def map_shift(game):
    """How far the minimap has scrolled from the reference: your position."""
    game.refresh()
    x0, y0, x1, y1 = MINIMAP
    mm = cv2.cvtColor(np.asarray(game.crop((x0, y0), (x1 - x0, y1 - y0))), cv2.COLOR_RGB2BGR)
    (dx, dy), conf = cv2.phaseCorrelate(REFERENCE_WALLS, minimap_walls(mm), HANNING)
    return (dx, dy) if conf > 0.25 else None


def wave_number(game):
    game.refresh()
    digits = "".join(ch for ch in text_at(game, WAVE_LABEL) if ch.isdigit())
    return int(digits) if digits else None


def focus_game(game):
    """Make sure keys go to the game, not whatever window was used last."""
    user32 = forge.user32
    if user32.GetForegroundWindow() == game.hwnd:
        return
    pyautogui.press("alt")  # lets this process take the foreground
    user32.ShowWindow(game.hwnd, 9)  # SW_RESTORE
    user32.SetForegroundWindow(game.hwnd)
    time.sleep(0.4)
    if user32.GetForegroundWindow() != game.hwnd:
        raise StepFailed("couldn't bring the game window to the front")


def click(game, pos, button="left"):
    """Move, settle, then a held press: the game misses instant clicks."""
    focus_game(GAME or game)
    x, y = game._scale(*pos)
    pyautogui.moveTo(game.left + x, game.top + y, duration=0.15)
    time.sleep(0.15)
    pyautogui.mouseDown(button=button)
    time.sleep(0.1)
    pyautogui.mouseUp(button=button)
    time.sleep(0.3)


def hold(key, seconds):
    focus_game(GAME)
    pyautogui.keyDown(key)
    time.sleep(seconds)
    pyautogui.keyUp(key)
    time.sleep(0.15)


def tap(key):
    focus_game(GAME)
    pyautogui.press(key)
    time.sleep(0.4)


def walk_to(game, spot, tries=25):
    """Walk until the minimap's wall layout is shifted by `spot`."""
    speed = SECONDS_PER_MINIMAP_PX
    for _ in range(tries):
        pos = map_shift(game)
        if pos is None:
            raise StepFailed("can't read the minimap layout")
        # Walking up scrolls the map down (shift y grows); walking left scrolls it right.
        ex, ey = spot[0] - pos[0], spot[1] - pos[1]
        print(f"    position {pos[0]:.0f},{pos[1]:.0f}  target {spot}")
        if abs(ex) <= SPOT_TOLERANCE and abs(ey) <= SPOT_TOLERANCE:
            return
        if abs(ey) >= abs(ex):
            key, wanted = ("w" if ey > 0 else "s"), abs(ey)
        else:
            key, wanted = ("a" if ex > 0 else "d"), abs(ex)
        hold(key, min(wanted * speed, 0.8))
        after = map_shift(game)
        if after:
            moved = abs(after[1] - pos[1]) if key in "ws" else abs(after[0] - pos[0])
            if moved > 0.5:  # adjust speed toward what actually happened
                speed = max(0.003, min(0.05, speed * min(wanted, 60) / moved))
    raise StepFailed(f"couldn't reach {spot} on the minimap")


# --- Steps ---------------------------------------------------------------------------
def open_chest(game):
    print("Walking to the War Chest...")
    walk_to(game, SPOT_CHEST)
    for _ in range(3):
        tap("f")
        if wait_for(game, WAR_CHEST_TITLE, "chest", 3):
            break
    else:
        raise StepFailed("War Chest panel didn't open")
    print("Opening the War Chest.")
    click(game, OPEN_WAR_CHEST)
    if sees(game, WAR_CHEST_TITLE, "chest"):
        tap("esc")  # close the panel before walking
    print(f"Waiting {LOOT_SPEW_WAIT}s for the loot to spew out...")
    time.sleep(LOOT_SPEW_WAIT)
    pick_up_loot()


def pick_up_loot():
    """Materials are picked up by walking over them (jiggle); items need E."""
    print("Picking up loot.")
    for key_a, key_b in [("a", "d"), ("d", "a"), ("w", "s"), ("s", "w")] * 2:
        hold(key_a, JIGGLE_STEP)
        hold(key_b, JIGGLE_STEP)
        tap("e")


def slot_centre(row, col):
    return SLOT_X0 + SLOT_DX * col, SLOT_Y0 + SLOT_DY * row


def new_item_slots(game):
    """Slots showing the orange 'not looked at yet' badge."""
    game.refresh()
    frame = cv2.cvtColor(np.asarray(game.frame), cv2.COLOR_RGB2BGR)
    found = []
    for row in range(8):
        for col in range(8):
            x, y = game._scale(*slot_centre(row, col))
            slot = frame[y - 36:y + 4, x - 14:x + 38]
            score = cv2.minMaxLoc(cv2.matchTemplate(slot, BADGE, cv2.TM_CCORR_NORMED, mask=BADGE_MASK))[1]
            if score > 0.9:
                found.append((row, col))
    return found


def teal_marks(game, cursor_x):
    """Most '!' on any teal special-stat line of the tooltip left of the cursor."""
    import pytesseract as tess
    x0, x1 = max(0, cursor_x - 450), cursor_x - 55
    crop = game.crop((x0, 120), (x1 - x0, 560))
    a = np.asarray(crop).astype(int)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    teal = (g > 140) & (b > 140) & (r < 120) & (abs(g - b) < 70)
    rows = np.where(teal.sum(1) > 3)[0]
    best, start = 0, None
    for k, y in enumerate(rows):
        start = y if start is None else start
        if k == len(rows) - 1 or rows[k + 1] - y > 3:
            line = crop.crop((0, max(0, start - 4), crop.width, y + 5))
            line = line.resize((line.width * 3, line.height * 3), Image.LANCZOS)
            text = tess.image_to_string(line, config="--psm 7").strip()
            if any(ch.isdigit() for ch in text):  # a real stat line, not frame decoration
                best = max(best, text.count("!"))
            start = None
    return best


def slot_fill(game, row, col):
    """How much is drawn in a slot: 0 for an empty slot, ~40+ for an item."""
    game.refresh()
    x, y = game._scale(*slot_centre(row, col))
    return float(np.asarray(game.frame.crop((x - 22, y - 22, x + 22, y + 22))).astype(int).std())


def drag(game, frm, to):
    fx, fy = game._scale(*frm)
    tx, ty = game._scale(*to)
    pyautogui.moveTo(game.left + fx, game.top + fy)
    pyautogui.mouseDown()
    time.sleep(0.3)
    pyautogui.moveTo(game.left + tx, game.top + ty, duration=0.4)
    time.sleep(0.2)
    pyautogui.mouseUp()
    time.sleep(0.5)


def sort_items(game, dry=False):
    """Hover each new item; keep teal !!/!!!, drag the rest to the trash can."""
    if not sees(game, INVENTORY_TITLE, "character"):
        tap("i")
        if not wait_for(game, INVENTORY_TITLE, "character", 3):
            raise StepFailed("inventory didn't open")
    pyautogui.moveTo(game.left + game.width // 2, game.top + 40)
    time.sleep(0.4)
    new = new_item_slots(game)
    print(f"{len(new)} new item(s): {new}")
    for row, col in new:
        x, y = slot_centre(row, col)
        sx, sy = game._scale(x, y)
        pyautogui.moveTo(game.left + sx, game.top + sy)
        time.sleep(0.5)
        game.refresh()
        marks = teal_marks(game, x)
        keep = marks >= KEEP_MIN_MARKS
        verdict = "keep" if keep else ("would trash" if dry else "trash")
        print(f"  slot ({row},{col}): {'!' * marks or 'no teal stat'} -> {verdict}")
        os.makedirs(forge.LOG_DIR, exist_ok=True)
        game.frame.save(os.path.join(forge.LOG_DIR, f"item_{time.strftime('%Y%m%d_%H%M%S')}_{row}{col}.png"))
        forge.log(f"item slot ({row},{col}): {marks} teal ! -> {verdict}")
        if not keep and not dry:
            drag(game, (x, y), TRASH)
            pyautogui.moveTo(game.left + game.width // 2, game.top + 40)
            time.sleep(0.5)
            if slot_fill(game, row, col) > 15:
                raise StepFailed(f"item in slot ({row},{col}) didn't go to the trash")
    tap("i")  # close the inventory


PROMPT_AREA = (700, 330, 600, 260)       # interaction prompts ("HEAD HOME", "OPEN") show here


def nudge_until_prompt(game, word, key, spot, steps=14, max_drift=8):
    """Small steps toward `key` until the interaction prompt `word` shows.

    Stops (instead of walking on) once the minimap says we're more than
    `max_drift` px past `spot` in that direction.
    """
    axis, sign = {"a": (0, 1), "d": (0, -1), "w": (1, 1), "s": (1, -1)}[key]
    for _ in range(steps):
        time.sleep(0.25)  # prompts take a moment to appear
        if sees(game, PROMPT_AREA, word):
            return
        pos = map_shift(game)
        if pos and (pos[axis] - spot[axis]) * sign > max_drift:
            break
        hold(key, 0.05)
    time.sleep(0.25)
    if not sees(game, PROMPT_AREA, word):
        raise StepFailed(f"no '{word}' prompt near the target spot")


def go_home(game):
    print("Walking to the portal...")
    walk_to(game, SPOT_PORTAL)
    nudge_until_prompt(game, "head home", "d", SPOT_PORTAL)  # portal is just right of the spot
    for _ in range(3):
        tap("f")
        if wait_for(game, VICTORY_TITLE, "victory", 6):
            break
    else:
        raise StepFailed("VICTORY screen didn't appear")
    print("Victory screen - continuing to town.")
    for _ in range(6):
        click(game, VICTORY_CONTINUE)
        time.sleep(1.5)
        if not sees(game, VICTORY_TITLE, "victory"):
            return
    raise StepFailed("stuck on the VICTORY screen")


def open_expeditions(game):
    print("Walking to the expedition NPC...")
    time.sleep(3)  # town loading
    for key, seconds in TOWN_WALK:
        hold(key, seconds)
    for _ in range(8):
        if sees(game, EXPEDITIONS_TITLE, "expedition"):
            return
        tap("f")  # talk to Almerolis, then F = "Yes" on "Let's get back to it, shall we?"
        time.sleep(0.8)
    raise StepFailed("Expeditions menu didn't open")


def start_forge(game):
    print("Choosing The Great Forge, Wrath 10.")
    click(game, GREAT_FORGE)
    click(game, WRATH_10)
    game.refresh()
    bar = text_at(game, ELDER_BAR)
    nums = [int(n.replace(" ", "")) for n in __import__("re").findall(r"\d[\d ]*\d", bar)]
    if len(nums) >= 2 and nums[1]:
        print(f"Elder Slorm: {nums[0]} / {nums[1]} ({nums[0] / nums[1]:.0%})")
        forge.log(f"Elder Slorm {nums[0]} / {nums[1]}")
    click(game, START)
    if not wait_for(game, WAVE_LABEL, "wave", 20):
        raise StepFailed("the forge didn't load")


def place_clones(game):
    print("Moving to the centre and placing clones.")
    time.sleep(1)
    walk_to(game, SPOT_CLONES)
    for pos in CLONE_SPOTS:
        click(game, pos, button="right")
        time.sleep(CLONE_CAST_GAP)
    os.makedirs(forge.LOG_DIR, exist_ok=True)
    game.refresh()
    game.frame.save(os.path.join(forge.LOG_DIR, f"clones_{time.strftime('%Y%m%d_%H%M%S')}.png"))
    press_start(game)


def press_start(game):
    """L opens the gate screen; L again closes it. Press once, wait, retry once."""
    for _ in range(2):
        print("Starting the forge (L).")
        tap("l")
        end = time.time() + 6
        while time.time() < end:
            game.refresh()
            if forge.screen_heading(game):
                return
            time.sleep(0.5)
    raise StepFailed("the gate screen didn't open after pressing L")


def end_run(game):
    open_chest(game)
    sort_items(game)
    go_home(game)


def start_run(game):
    open_expeditions(game)
    start_forge(game)
    place_clones(game)


# --- Waves -------------------------------------------------------------------------
def play_waves(game, args, state):
    """Pick cards until wave 100 is over (no pick screen for a while at wave 100)."""
    handled, handled_at, idle_since, retries = None, 0.0, None, 0
    while not forge.stop_pressed():
        game.refresh()
        heading = forge.screen_heading(game)
        if heading is None:
            handled = None
            forge.note_wave(game)
            fighting = fuzzy_in("wave", text_at(game, KILL_BAR))
            if wave_number(game) == 100 and not fighting:
                idle_since = idle_since or time.time()
                if time.time() - idle_since > 20:
                    return
            else:
                idle_since = None
        else:
            idle_since = None
            sig = forge.card_signature(game)
            new_screen = handled is None or forge.cards_changed(sig, handled) > forge.SAME_SCREEN_NOISE
            retry = not new_screen and time.time() - handled_at > forge.RETRY_AFTER
            if new_screen or retry:
                retries = retries + 1 if retry else 0
                if retries > forge.MAX_RETRIES:
                    raise StepFailed("my clicks aren't changing the pick screen")
                time.sleep(0.5)
                game.refresh()
                forge.handle_screen(game, args, heading, state)
                handled, handled_at = forge.card_signature(game), time.time()
        time.sleep(0.5)
    raise SystemExit("Stopped.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live", action="store_true", help="required: this script presses keys and clicks")
    ap.add_argument("--step", choices=["loot", "sort", "end", "start"], help="run one part only")
    ap.add_argument("--dry", action="store_true", help="sort step: hover and report, don't trash")
    ap.add_argument("--runs", type=int, default=1, help="how many forges to play back to back")
    args = ap.parse_args()
    if not args.live:
        raise SystemExit("Add --live: this script moves your character and clicks.")
    args.capture = False
    global GAME
    game = GAME = forge.Game()
    focus_game(game)
    try:
        if args.step == "loot":
            return open_chest(game)
        if args.step == "sort":
            return sort_items(game, dry=args.dry)
        if args.step == "end":
            return end_run(game)
        if args.step == "start":
            return start_run(game)
        for run in range(args.runs):
            state = forge.load_state(new_run=True)
            print(f"=== Forge {run + 1}/{args.runs}: waves")
            if run == 0 and forge.read_wave(game) == 0 and forge.screen_heading(game) is None:
                press_start(game)  # later runs were already started by start_run()
            play_waves(game, args, state)
            forge.log("wave 100 done - ending run")
            end_run(game)
            if run + 1 < args.runs:
                start_run(game)
    except StepFailed as e:
        game.refresh()
        os.makedirs(forge.LOG_DIR, exist_ok=True)
        shot = os.path.join(forge.LOG_DIR, f"failed_{time.strftime('%Y%m%d_%H%M%S')}.png")
        game.frame.save(shot)
        forge.log(f"cycle stopped: {e} ({shot})")
        forge.winsound.MessageBeep(forge.winsound.MB_ICONHAND)
        raise SystemExit(f"Stopped: {e}. Screenshot: {shot}")


if __name__ == "__main__":
    main()

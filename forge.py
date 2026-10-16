"""Read the 3 forge challenge cards, score them, and (with --live) click the best one.

Scoring lives in strategy.py and is reloaded before every pick. Cards the
strategy flags as judgement calls make it beep and leave the pick to you.

All positions are for a 1920x1080 game client and get scaled to the real
window size. The game has to be visible: it reads the screen, not the window.

    python forge.py              # read + score the cards, no clicking
    python forge.py --capture    # also save every region it reads to debug/
    python forge.py --live       # click the best card
    python forge.py --live --loop  # keep going; hold F8 to stop
    python forge.py --image debug/forge_wave1.png  # test on a saved screenshot
"""
import argparse
import base64
import ctypes
import ctypes.wintypes
import difflib
import importlib
import json
import os
import re
import time
import winsound
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import keyboard
import mss
import numpy as np
import pyautogui
import pytesseract as tess
from PIL import Image, ImageOps

import strategy

tess.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
GAME_DIR = r"C:\Program Files (x86)\Steam\steamapps\common\The Slormancer"
pyautogui.FAILSAFE = True  # slam the mouse into a screen corner to abort

BASE_W, BASE_H = 1920, 1080
STOP_KEY = "f8"

# --- Layout (1920x1080 client coordinates), one entry per card -------------
CARD_TEXT_BOX = [(463, 494), (835, 492), (1199, 493)]   # size TEXT_SIZE
TEXT_SIZE = (258, 134)
CARD_DURATION_BOX = [(463, 625), (835, 625), (1199, 625)]  # size DURATION_SIZE
DURATION_SIZE = (245, 37)
CARD_TITLE_BOX = [(455, 350), (823, 350), (1191, 350)]  # name + "Normal Challenge"
TITLE_SIZE = (275, 45)
CARD_AMOUNT_BOX = [(560, 743), (928, 743), (1296, 743)]  # green number on the reward icon
AMOUNT_SIZE = (65, 22)
AMOUNT_COLOR = (97, 236, 42)  # spirit counts are green, percentages white
CARD_CLICK = [(595, 570), (965, 570), (1325, 570)]

# "CHOOSE YOUR PATH" heading, only shown on the forge challenge screen.
SCREEN_TITLE_BOX = (570, 140)
SCREEN_TITLE_SIZE = (780, 90)
CARD_REWARD_ICON = [(592, 728), (959, 728), (1327, 728)]  # hover here for the tooltip
CARD_LEFT = [445, 813, 1181]  # tooltips open to the left of the card
TOOLTIP_TOP, TOOLTIP_W, TOOLTIP_H = 400, 430, 400  # tall enough for effect text

# Reward names as the game's tooltips spell them (dat_str.json forge_random_*).
REWARD_NAMES = ["Equipment Quality", "Slormite Quality", "Slormeline Quality",
                "Fragment Quality", "Goldus Quantity", "Slorm Quantity",
                "War Chest Quality", "War Chest Quantity"]
COLOR_TOLERANCE = 12  # per channel

# Reward icons learned from tooltips: icons/<reward name>__<n>.png. Matching a
# known icon skips the hover. Same reward differs by ~5, different ones by ~40.
ICON_DIR = "icons"
ICON_HALF_W, ICON_TOP, ICON_BOTTOM = 24, 700, 742
ICON_MATCH = 15

RARITIES = ["Normal", "Magic", "Rare", "Epic", "Legendary", "Cursed", "Pause"]
# Rarities whose rewards can be War Chest effects (always hovered).
EFFECT_RARITIES = ("Rare", "Epic", "Legendary", "Pause")


def load_challenge_names():
    """Every challenge name from the game's own data files (base64 JSON)."""
    names = set()
    for file in ("dat_cat.json", "dat_for.json"):
        with open(os.path.join(GAME_DIR, file), "rb") as f:
            for entry in json.loads(base64.b64decode(f.read())):
                if entry.get("EN_NAME"):
                    names.add(entry["EN_NAME"])
    return sorted(names)


CHALLENGE_NAMES = load_challenge_names()


def words(text):
    return re.findall(r"[a-z]{3,}", text.lower())


def load_special_rewards():
    """War Chest effects (dat_for.json categories 98/99).

    Returns (ref -> description words, refs whose text says they last for the
    rest of the expedition).
    """
    with open(os.path.join(GAME_DIR, "dat_for.json"), "rb") as f:
        entries = [e for e in json.loads(base64.b64decode(f.read()))
                   if e.get("CATEGORY") in (98, 99) and e.get("EN_DESCRIPTION")]
    lasting = {e["REF"] for e in entries if "for the rest of the expedition" in e["EN_DESCRIPTION"].lower()}
    return {e["REF"]: words(e["EN_DESCRIPTION"]) for e in entries}, lasting


SPECIAL_REWARDS, LASTING_SPECIALS = load_special_rewards()


def lasts_whole_run(ref):
    return ref in LASTING_SPECIALS or ref in strategy.LASTING_EXTRA


def identify_special(text):
    """(ref, share of the effect's words found in text) for the best match."""
    found = set(words(text))
    best = max(SPECIAL_REWARDS.items(), key=lambda kv: sum(w in found for w in kv[1]) / len(kv[1]))
    ref, template = best
    return ref, sum(w in found for w in template) / len(template)


def identify(ocr_name):
    """Closest game challenge name to what OCR read, or None."""
    by_upper = {n.upper(): n for n in CHALLENGE_NAMES}
    match = difflib.get_close_matches(ocr_name.upper(), list(by_upper), n=1, cutoff=0.75)
    return by_upper[match[0]] if match else None


@dataclass
class Challenge:
    index: int
    name: str | None  # game challenge name, None if not recognised
    rarity: str | None
    text: str
    duration: int | None  # waves; 0 = rest of the expedition; None = unread
    reward_type: str
    reward_amount: int | None
    special: int | None = None  # War Chest effect ref from the game data
    hovered: bool = False  # reward was read from the tooltip
    score: int = 0
    reasons: list = field(default_factory=list)  # how the score was built
    ask: list = field(default_factory=list)  # why you should pick this one yourself
    notes: list = field(default_factory=list)


def is_siege_leader(c):
    return bool(c.name) and c.name.startswith("The Siege Leader")


def score_challenge(c, goal):
    """Rarity/duration/challenge part of the score (no reward needed)."""
    s = strategy
    if c.duration:
        c.score += c.duration * s.POINTS_PER_WAVE
        c.reasons.append(f"{c.duration} waves +{c.duration * s.POINTS_PER_WAVE}")
    elif is_siege_leader(c):
        c.score += s.SIEGE_LEADER_POINTS
        c.reasons.append(f"Siege Leader {s.SIEGE_LEADER_POINTS:+}")
    elif c.duration == 0 and not is_curse(c):
        c.score += s.REST_OF_RUN_CHALLENGE_POINTS
        c.reasons.append(f"challenge lasts the rest of the run {s.REST_OF_RUN_CHALLENGE_POINTS:+}")
        if c.name in s.ASK_IF_REST_OF_RUN:
            c.ask.append(f"{c.name} for the rest of the run")

    overrides = s.GOAL_OVERRIDES.get(goal, {})
    text = c.text.lower()
    for name, contains, points, ask in s.RULES:
        if c.name == name and contains in text:
            points = overrides.get(name, points)
            c.score += points
            c.reasons.append(f"{name}{' (' + contains + ')' if contains else ''} {points:+}")
            if ask:
                c.ask.append(f"strategy says you decide on {name}")
            break

    if c.rarity in s.ASK_ON_RARITY:
        c.ask.append(f"{c.rarity} card")
    if s.ASK_ON_UNKNOWN and c.name is None:
        c.ask.append("challenge not recognised")


def is_curse(c):
    return c.name in strategy.CURSE_CARDS or c.rarity == "Cursed"


def score_reward(c, goal):
    """Reward part of the score. Basic rewards only break ties."""
    s = strategy
    reward = c.reward_type
    if is_curse(c):  # the reward tells which curse it is
        points = s.CURSE_BY_REWARD.get(reward, s.CURSE_UNKNOWN_REWARD)
        c.score += points
        c.reasons.append(f"curse with {reward} reward {points:+}")
        return
    priority = s.REWARD_PRIORITY.get(goal, [])
    if reward in priority:
        rank = priority.index(reward)
        points = s.REWARD_POINTS[rank] if rank < len(s.REWARD_POINTS) else 0
        c.score += points
        c.reasons.append(f"{reward} for {goal} {points:+}")
    elif c.special is not None:
        feeds, tier = s.SPECIAL_REWARDS.get(c.special, ("any", "meh"))
        points = s.TIER_POINTS[tier]
        if tier not in ("giga", "great") and feeds not in ("any", goal):
            points = round(points * s.OFF_GOAL_SHARE)
        c.score += points
        span = "rest of run" if lasts_whole_run(c.special) else "one-off"
        c.reasons.append(f"effect #{c.special} ({tier}, {feeds}, {span}) {points:+}")
    elif reward == "Special":
        c.score += s.UNKNOWN_SPECIAL_POINTS
        c.reasons.append(f"unidentified effect {s.UNKNOWN_SPECIAL_POINTS:+}")
    if s.ASK_ON_UNKNOWN and c.hovered and reward in ("Unknown", "Special") and c.special is None:
        c.ask.append("reward not recognised")


def score(c, goal):
    score_challenge(c, goal)
    score_reward(c, goal)


# --- Game window -----------------------------------------------------------
user32 = ctypes.windll.user32
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # real pixels, not scaled
except OSError:
    pass


GAME_EXE = "The Slormancer.exe"


def process_exe(hwnd):
    """File name of the program that owns a window."""
    pid = ctypes.wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid.value)  # QUERY_LIMITED_INFORMATION
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = ctypes.wintypes.DWORD(1024)
        ctypes.windll.kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size))
        return os.path.basename(buf.value)
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def find_game_window():
    """The game's own window, by process (other windows, e.g. Discord, can share the title)."""
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd) and process_exe(hwnd).lower() == GAME_EXE.lower():
            found.append(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    if not found:
        raise SystemExit("The Slormancer isn't running.")
    return found[0]


class Game:
    """Client-area screenshot plus helpers working in 1920x1080 coordinates."""

    def __init__(self):
        self.hwnd = find_game_window()
        rect = ctypes.wintypes.RECT()
        user32.GetClientRect(self.hwnd, ctypes.byref(rect))
        origin = ctypes.wintypes.POINT(0, 0)
        user32.ClientToScreen(self.hwnd, ctypes.byref(origin))
        self.left, self.top = origin.x, origin.y
        self.width, self.height = rect.right, rect.bottom
        self.sx, self.sy = self.width / BASE_W, self.height / BASE_H
        self.refresh()

    @classmethod
    def from_image(cls, path):
        """A Game backed by a saved screenshot, for testing without the game."""
        game = cls.__new__(cls)
        game.frame = Image.open(path).convert("RGB")
        game.left = game.top = 0
        game.width, game.height = game.frame.size
        game.sx, game.sy = game.width / BASE_W, game.height / BASE_H
        game.refresh = lambda: None
        return game

    def refresh(self):
        with mss.MSS() as sct:
            raw = sct.grab({"left": self.left, "top": self.top,
                            "width": self.width, "height": self.height})
        self.frame = Image.frombytes("RGB", raw.size, raw.rgb)

    def _scale(self, x, y):
        return round(x * self.sx), round(y * self.sy)

    def crop(self, pos, size):
        x, y = self._scale(*pos)
        w, h = self._scale(*size)
        return self.frame.crop((x, y, x + w, y + h))

    def pixel(self, pos):
        return self.frame.getpixel(self._scale(*pos))

    def click(self, pos):
        x, y = self._scale(*pos)
        pyautogui.click(self.left + x, self.top + y)

    def looks_blank(self):
        return self.frame.convert("L").getextrema()[1] < 10


def color_close(a, b, tol=COLOR_TOLERANCE):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


# --- Reading the cards -----------------------------------------------------
def ocr(img, config=""):
    # Upscaling helps tesseract a lot on small game text.
    img = img.resize((img.width * 2, img.height * 2), Image.LANCZOS)
    return tess.image_to_string(img, config=config).strip()


def screen_heading(game):
    """'choose', 'cursed' or 'rest' (Siege Leader beaten) on the pick screens, else None."""
    # Only the bright white heading letters: floating damage numbers drawn over
    # the heading made plain OCR read nothing.
    crop = game.crop(SCREEN_TITLE_BOX, SCREEN_TITLE_SIZE)
    mask = Image.new("L", crop.size, 255)
    mask.putdata([0 if min(p) > 225 else 255 for p in crop.get_flattened_data()])
    text = ocr(mask).lower()
    if "cursed" in text:
        return "cursed"
    if "deserved" in text or "rest" in text.split():
        return "rest"
    if "choose" in text or "path" in text:
        return "choose"
    return None


def read_duration(crop):
    text = ocr(crop)
    if "rest of the exp" in text.lower():
        return 0, text
    m = re.search(r"\d+", text)
    return (int(m.group()) if m else None), text


def read_amount(crop):
    """Reward amount: white percentage or green spirit count."""
    pixels = list(crop.get_flattened_data())
    white = [min(p) > 200 for p in pixels]
    green = [color_close(p, AMOUNT_COLOR, 40) for p in pixels]
    percent = sum(white) >= sum(green)
    keep = white if percent else green  # icon pixels leak into the other
    mask = Image.new("L", crop.size, 255)
    mask.putdata([0 if k else 255 for k in keep])
    # A white border stops tesseract reading the % as extra digits.
    scale = 3 if percent else 2  # what reads best for each, tested on real cards
    mask = ImageOps.expand(mask.resize((mask.width * scale, mask.height * scale), Image.LANCZOS), 20, 255)
    text = tess.image_to_string(mask, config="--psm 7")
    m = re.search(r"([0-9]+)\s*%", text) if percent else None
    m = m or re.search(r"([0-9]+)", text)
    return int(m.group(1)) if m else None


def icon_crop(game, i):
    x, _ = CARD_REWARD_ICON[i]
    return game.crop((x - ICON_HALF_W, ICON_TOP), (2 * ICON_HALF_W, ICON_BOTTOM - ICON_TOP))


def load_icons():
    icons = []
    if os.path.isdir(ICON_DIR):
        for file in os.listdir(ICON_DIR):
            if file.endswith(".png"):
                img = Image.open(os.path.join(ICON_DIR, file)).convert("RGB")
                icons.append((file.split("__")[0], np.asarray(img, dtype=np.int16)))
    return icons


ICONS = load_icons()


def match_icon(crop):
    """(reward name, distance) of the closest learned icon, or (None, inf)."""
    a = np.asarray(crop.resize((2 * ICON_HALF_W, ICON_BOTTOM - ICON_TOP)), dtype=np.int16)
    best = (None, float("inf"))
    for name, b in ICONS:
        d = float(np.abs(a - b).mean())
        if d < best[1]:
            best = (name, d)
    return best


def learn_icon(name, crop):
    os.makedirs(ICON_DIR, exist_ok=True)
    n = sum(1 for other, _ in ICONS if other == name)
    crop = crop.resize((2 * ICON_HALF_W, ICON_BOTTOM - ICON_TOP))
    crop.save(os.path.join(ICON_DIR, f"{name}__{n}.png"))
    ICONS.append((name, np.asarray(crop, dtype=np.int16)))
    print(f"      (learned the {name} icon)")


def read_reward(game, i):
    """Hover the reward icon and read its tooltip.

    Returns (reward type, War Chest effect ref or None, tooltip text). Types are
    a REWARD_NAMES entry, "Spirit", "Special" (an effect) or "Unknown".
    """
    if not hasattr(game, "hwnd"):  # saved screenshot: nothing to hover
        return "Unknown", None, "(no hover on a saved image, no learned icon)"
    x, y = game._scale(*CARD_REWARD_ICON[i])
    pyautogui.moveTo(game.left + x, game.top + y)
    time.sleep(0.4)
    game.refresh()
    tooltip = ocr(game.crop((max(0, CARD_LEFT[i] - TOOLTIP_W), TOOLTIP_TOP), (TOOLTIP_W, TOOLTIP_H)))
    lines = [l.strip() for l in tooltip.splitlines() if l.strip()]
    # Effects first: their text can mention basic names ("War Chest Quality").
    ref, share = identify_special(tooltip)
    if share >= 0.8:
        return "Special", ref, tooltip
    for line in lines:  # a neighbouring card's text can push the name down
        match = difflib.get_close_matches(line, REWARD_NAMES, n=1, cutoff=0.8)
        if match:
            return match[0], None, tooltip
    if any("spirit" in l.lower() for l in lines[:2]):
        return "Spirit", None, tooltip
    return ("Special" if "war chest effect" in tooltip.lower() else "Unknown"), None, tooltip


def read_title(crop):
    """(game challenge name or None, rarity or None, raw OCR) from a title crop."""
    raw = [l.strip() for l in ocr(crop).splitlines() if l.strip()]
    rarity = None
    name_lines = []
    for line in raw:
        word = next((r for r in RARITIES if line.lower().startswith(r.lower())), None)
        if word and (word == "Pause" or "challenge" in line.lower() or "path" in line.lower()):
            rarity = word
        else:
            name_lines.append(line)
    return identify(" ".join(name_lines)), rarity, " / ".join(raw)


OCR_POOL = ThreadPoolExecutor(max_workers=6)


# Challenges whose RULES depend on the description text.
def needs_text(name):
    return any(n == name and contains for n, contains, *_ in strategy.RULES)


def read_cards(game, goal, capture_dir=None):
    """Read the 3 cards: rarity/name/duration first, rewards only where they matter."""
    # Crop everything from one frame first: hovering changes game.frame.
    crops = [{"title": game.crop(CARD_TITLE_BOX[i], TITLE_SIZE),
              "text": game.crop(CARD_TEXT_BOX[i], TEXT_SIZE),
              "duration": game.crop(CARD_DURATION_BOX[i], DURATION_SIZE),
              "amount": game.crop(CARD_AMOUNT_BOX[i], AMOUNT_SIZE),
              "icon": icon_crop(game, i)} for i in range(3)]
    if capture_dir:
        for i, parts in enumerate(crops):
            for label, img in parts.items():
                img.save(f"{capture_dir}/card{i}_{label}.png")
    titles = [OCR_POOL.submit(read_title, parts["title"]) for parts in crops]
    durations = [OCR_POOL.submit(read_duration, parts["duration"]) for parts in crops]

    cards = []
    for i in range(3):
        name, rarity, raw_title = titles[i].result()
        duration, duration_text = durations[i].result()
        text = ocr(crops[i]["text"]) if needs_text(name) else ""
        c = Challenge(i, name, rarity, text, duration, "Unknown", None)
        if name is None:
            c.notes.append(f"title read as {raw_title!r}")
        if duration is None and not name_has_no_duration(name):
            c.notes.append(f"couldn't read duration: {duration_text!r}")
        score_challenge(c, goal)
        cards.append(c)

    # Rewards. Rare+ cards can carry War Chest effects, which share one framed
    # icon, so always hover those and never learn icons from them. Normal/Magic
    # rewards are basic: a learned icon is a free lookup, hover only an unknown
    # icon that could break a duration tie.
    top = max(c.score for c in cards)
    for c in cards:
        if (c.name or "").startswith("Upgrade"):
            continue  # Upgrade cards have no reward
        rare_plus = c.rarity in EFFECT_RARITIES
        name, dist = match_icon(crops[c.index]["icon"])
        if not rare_plus and name is not None and dist < ICON_MATCH:
            c.reward_type = name
        elif rare_plus or is_curse(c) or top - c.score < strategy.POINTS_PER_WAVE:
            reward, special, tooltip = read_reward(game, c.index)
            c.reward_type, c.special, c.hovered = reward, special, True
            if rare_plus and hasattr(game, "hwnd"):
                stamp = time.strftime("%Y%m%d_%H%M%S")
                os.makedirs(LOG_DIR, exist_ok=True)
                game.frame.save(os.path.join(LOG_DIR, f"tooltip_{stamp}_card{c.index + 1}.png"))
                log(f"{c.rarity} {c.name} reward -> {reward}{' #' + str(special) if special else ''}: "
                    f"{' '.join(tooltip.split())[:300]}")
            if special is None and reward in REWARD_NAMES + ["Spirit"] and not rare_plus:
                learn_icon(reward, crops[c.index]["icon"])
            elif special is None and reward not in REWARD_NAMES + ["Spirit"]:
                c.notes.append(f"reward tooltip read as {' '.join(tooltip.split())[:200]!r}")
        score_reward(c, goal)
        if strategy.READ_AMOUNTS:
            c.reward_amount = read_amount(crops[c.index]["amount"])
    return cards


def name_has_no_duration(name):
    """Challenges that only affect the next wave show no duration line."""
    return name in ("Overcrowding", "Ace Combat", "Highlander") or (name or "").startswith(("Upgrade", "Obelisk"))


def show(cards):
    for c in cards:
        dur = {None: "?", 0: "rest of expedition"}.get(c.duration, f"{c.duration} waves")
        amount = "" if c.reward_amount is None else f" x{c.reward_amount}"
        reward = c.reward_type if c.special is None else f"effect #{c.special}"
        print(f"[{c.index + 1}] score {c.score:>4} | {c.name or '???'} ({c.rarity or '?'}) | {dur} | {reward}{amount}")
        print(f"      {' '.join(c.text.split()) or '(no text read)'}")
        print(f"      = {', '.join(c.reasons) or 'nothing scored'}")
        for n in c.notes:
            print(f"      ! {n}")
        for a in c.ask:
            print(f"      ? {a}")


def decide(cards):
    """(best card, reasons to let you pick instead). Empty reasons = safe to click."""
    ranked = sorted(cards, key=lambda c: c.score, reverse=True)
    best = ranked[0]
    # Only judgement calls that could matter: the best card, cards close to it,
    # and unreadable rewards (their real value is unknown).
    in_contention = lambda c: c is best or best.score - c.score < 2 * strategy.POINTS_PER_WAVE
    ask = [f"card {c.index + 1}: {a}" for c in cards for a in c.ask
           if in_contention(c) or a == "reward not recognised"]
    if ranked[0].score - ranked[1].score < strategy.ASK_MARGIN:
        ask.append(f"top two within {strategy.ASK_MARGIN} points")
    return best, ask


STATE_FILE = "run_state.json"
LOG_DIR = "runs"
NEW_RUN_AFTER = 20 * 60  # seconds without a pick before a new run is assumed


def load_state(new_run=False):
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, ValueError):
        state = None
    if new_run or not state or time.time() - state["last_pick"] > NEW_RUN_AFTER:
        state = {"goal": strategy.GOAL, "started": time.time(), "last_pick": time.time(), "picks": []}
    return state


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1)


def log(line):
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(os.path.join(LOG_DIR, "forge_log.txt"), "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {line}\n")


def wait_for_human(game, seconds):
    """True if the pick screen went away (someone picked) within `seconds`."""
    end = time.time() + seconds
    while time.time() < end:
        if stop_pressed():
            raise SystemExit("Stopped.")
        time.sleep(1)
        game.refresh()
        if screen_heading(game) is None:
            return True
    return False


def handle_screen(game, args, heading, state):
    """Read, score and (if --live) click. Assumes the forge screen is up."""
    importlib.reload(strategy)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    capture_dir = None
    if args.capture:
        capture_dir = "debug"
        os.makedirs(capture_dir, exist_ok=True)
        game.frame.save(f"{capture_dir}/game.png")
    shot = game.frame.copy()
    goal = state["goal"]
    print(f"\n--- {time.strftime('%H:%M:%S')} | goal: {goal} | pick {len(state['picks']) + 1}")
    t0 = time.time()
    if hasattr(game, "hwnd"):  # park the mouse so no card is highlighted
        pyautogui.moveTo(game.left + game.width // 2, game.top + 40)
        time.sleep(0.15)
        game.refresh()
    cards = read_cards(game, goal, capture_dir)
    show(cards)
    print(f"(read + scored in {time.time() - t0:.1f}s)")
    best, ask = decide(cards)
    if heading == "cursed" and "Cursed" in strategy.ASK_ON_RARITY:
        ask.append("Cursed Path screen")
    print(f"Best: card {best.index + 1} ({best.name or '???'})")
    if not args.live:
        if ask:
            print(f"Would wait for you first: {'; '.join(ask)}")
        return False

    os.makedirs(LOG_DIR, exist_ok=True)
    shot.save(os.path.join(LOG_DIR, f"pick_{stamp}.png"))
    summary = " | ".join(f"{c.index + 1}:{c.name}/{c.duration}w/{c.reward_type if c.special is None else '#' + str(c.special)}={c.score}"
                         for c in cards)
    if ask:
        print(f"Judgement call ({'; '.join(ask)}) - waiting {strategy.HUMAN_WAIT}s for you to pick.")
        winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        if strategy.HUMAN_WAIT and wait_for_human(game, strategy.HUMAN_WAIT):
            print("You picked.")
            log(f"goal={goal} {summary} -> picked by hand ({'; '.join(ask)})")
            state["picks"].append({"by": "hand", "cards": summary})
            state["last_pick"] = time.time()
            save_state(state)
            return True
        game.refresh()
        if screen_heading(game) is None:
            return True

    game.click(CARD_CLICK[best.index])
    print("Clicked.")
    note = f" (nobody answered: {'; '.join(ask)})" if ask else ""
    log(f"goal={goal} {summary} -> card {best.index + 1}{note}")
    state["picks"].append({"by": "script", "card": best.index + 1, "cards": summary})
    state["last_pick"] = time.time()
    if best.special is not None and strategy.SWITCH_ON_LASTING and lasts_whole_run(best.special):
        feeds, tier = strategy.SPECIAL_REWARDS.get(best.special, ("any", "meh"))
        if feeds not in ("any", goal):
            state["goal"] = feeds
            print(f"Rest-of-run effect #{best.special} taken - goal switches {goal} -> {feeds}.")
            log(f"goal switch {goal} -> {feeds} (effect #{best.special})")
    save_state(state)
    return True


SAME_SCREEN_NOISE = 6  # per-card signature change below this = same cards
RETRY_AFTER = 45  # seconds; longer than HUMAN_WAIT so judgement calls aren't cut short


def card_signature(game):
    """Small grey thumbnail of the 3 card titles: changes when new cards appear."""
    return np.stack([np.asarray(game.crop(CARD_TITLE_BOX[i], TITLE_SIZE).convert("L").resize((40, 8)), dtype=np.int16)
                     for i in range(3)])


def cards_changed(a, b):
    """Largest per-card difference between two signatures."""
    return max(np.abs(a[i] - b[i]).mean() for i in range(3))


def stop_pressed():
    return keyboard.is_pressed(STOP_KEY)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live", action="store_true", help="actually click the best card")
    ap.add_argument("--capture", action="store_true", help="save the regions read to debug/")
    ap.add_argument("--loop", action="store_true", help=f"keep watching until {STOP_KEY.upper()} is held")
    ap.add_argument("--max-picks", type=int, help="stop the loop after this many clicks")
    ap.add_argument("--new-run", action="store_true", help="forget the previous run's goal switches")
    ap.add_argument("--image", help="read a saved screenshot instead of the game (never clicks)")
    args = ap.parse_args()

    if args.image:
        args.live = args.loop = False
        game = Game.from_image(args.image)
    else:
        game = Game()
    print(f"Game client {game.width}x{game.height} at ({game.left}, {game.top})")
    if game.looks_blank():
        raise SystemExit("Game capture is black - is the game minimised or still loading?")

    if not args.loop:
        heading = screen_heading(game)
        if heading is None:
            raise SystemExit("Not on the forge 'Choose your path' screen.")
        state = load_state(args.new_run)
        handle_screen(game, args, heading, state)
        if args.live:
            save_state(state)
        return

    print(f"Watching for the forge screen - hold {STOP_KEY.upper()} to stop.")
    state = load_state(args.new_run)
    print(f"Run goal: {state['goal']} ({len(state['picks'])} picks so far)")
    handled = None  # card signature of the screen already dealt with
    handled_at = 0.0
    picks = 0
    while not stop_pressed():
        game.refresh()
        heading = screen_heading(game)
        if heading is None:
            handled = None
        else:
            sig = card_signature(game)
            new_screen = handled is None or cards_changed(sig, handled) > SAME_SCREEN_NOISE
            # Same cards still up long after a click: the click didn't land.
            retry = not new_screen and time.time() - handled_at > RETRY_AFTER
            if new_screen or retry:
                if retry:
                    print("Same screen is still up - picking again.")
                time.sleep(0.5)  # let the cards finish animating in
                game.refresh()
                picks += handle_screen(game, args, heading, state)
                handled, handled_at = card_signature(game), time.time()
                if args.max_picks and picks >= args.max_picks:
                    print(f"Done: {picks} picks.")
                    return
        time.sleep(0.5)


if __name__ == "__main__":
    main()

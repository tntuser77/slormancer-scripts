Automates picking challenges in The Slormancer's Great Forge.

`forge.py` watches the game, reads the three "Choose your path" cards, scores them with the rules in `strategy.py` and clicks the best one.

## Setup

- Tesseract OCR at `C:\Program Files\Tesseract-OCR\tesseract.exe`
- `python -m venv .venv` then `.venv\Scripts\pip install pyautogui keyboard pytesseract pillow opencv-python numpy mss`
- The game must be visible (the script reads the screen). Any resolution; positions are scaled from 1920x1080.

## Use

```
.venv\Scripts\python forge.py                 # read + score the current screen, no clicking
.venv\Scripts\python forge.py --live --loop   # play the forge; hold F8 to stop
.venv\Scripts\python forge.py --live --loop --max-picks 20 --new-run
.venv\Scripts\python forge.py --image runs\pick_....png   # test on a saved screenshot
```

## Full loop (forge_cycle.py)

`forge_cycle.py --live --runs N` plays N forges back to back: picks cards to
wave 100, opens the War Chest, picks up loot, sorts new items (keeps teal `!!`
and `!!!` special stats, trashes the rest), takes the portal home, talks to
Almerolis, starts The Great Forge at Wrath 10, places the 4 clones and presses
L. Each step checks the screen first and stops with a screenshot in `runs/`
if something isn't what it expects. `--step loot|sort|end|start` runs one part.
Positions come from a recorded hand-played cycle (`record_demo.py`).

## How it decides

1. Card name, rarity and duration (OCR, in parallel). Challenge names are matched against the game's own data files.
2. Score: waves of duration first, then challenge rules (Upgrade, Attrition Battle, curses, Nullifying Shield, Siege Leader, rest-of-forge penalty...).
3. Rewards: basic rewards break ties; War Chest effects (Rare+ cards, read from the hover tooltip) can win outright. An effect that lasts the rest of the run for one resource switches the run's goal to it.
4. Judgement calls (Epic/Legendary, flagged curses, unreadable cards) beep and wait `HUMAN_WAIT` seconds, then the script picks itself.

`strategy.py` holds every weight and rating and is reloaded before each pick, so it can be edited mid-run.

## Files

- `icons/` - reward icons learned from tooltips, so known rewards need no hover
- `runs/` (not committed) - `forge_log.txt` plus a screenshot of every pick
- `run_state.json` (not committed) - current run's goal and picks
- `main.py`, `find_reward_type.py`, `get mouse *.py` - the original 2025 prototype and helpers

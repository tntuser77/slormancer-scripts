"""Record one hand-played forge cycle so its steps can be automated.

Logs every key press and mouse click made while The Slormancer is the active
window (nothing typed in other programs is recorded), with the position in
1920x1080 game coordinates and a screenshot of the game at that moment.
Also saves a screenshot every few seconds so movement between inputs shows.

    python record_demo.py     # play; press F10 to stop

Output: demos/<timestamp>/events.jsonl + numbered screenshots.
"""
import ctypes
import json
import os
import threading
import time

from pynput import keyboard, mouse

import forge

STOP_KEY = keyboard.Key.f10
PERIODIC_SHOT = 3.0  # seconds

out_dir = os.path.join("demos", time.strftime("%Y%m%d_%H%M%S"))
os.makedirs(out_dir)
events = open(os.path.join(out_dir, "events.jsonl"), "a", encoding="utf-8")
lock = threading.Lock()
start = time.time()
shot_n = 0
stop = threading.Event()
held = set()  # keys currently down, so auto-repeat isn't logged as new presses


def game_active():
    return ctypes.windll.user32.GetForegroundWindow() == game.hwnd


def snapshot(label):
    global shot_n
    game.refresh()
    shot_n += 1
    name = f"{shot_n:04d}_{label}.png"
    game.frame.save(os.path.join(out_dir, name))
    return name


def record(kind, **data):
    with lock:
        data.update(kind=kind, t=round(time.time() - start, 2), shot=snapshot(kind))
        events.write(json.dumps(data) + "\n")
        events.flush()
        print(data)


def to_game(x, y):
    """Screen position -> 1920x1080 game coordinates (None if outside the game)."""
    gx, gy = (x - game.left) / game.sx, (y - game.top) / game.sy
    if 0 <= gx < forge.BASE_W and 0 <= gy < forge.BASE_H:
        return round(gx), round(gy)
    return None


def key_name(key):
    return key.char if getattr(key, "char", None) else str(key).replace("Key.", "")


def on_press(key):
    if key == STOP_KEY:
        stop.set()
        return False
    if key in held or not game_active():
        return
    held.add(key)
    record("key", key=key_name(key), mouse=to_game(*mouse_ctl.position))


def on_release(key):
    if key in held:
        held.discard(key)
        if game_active():
            with lock:
                events.write(json.dumps({"kind": "key_up", "key": key_name(key),
                                         "t": round(time.time() - start, 2)}) + "\n")


def on_click(x, y, button, pressed):
    if not game_active():
        return
    pos = to_game(x, y)
    if pos is None:
        return
    if pressed:
        record("click", button=button.name, pos=pos)
    else:
        with lock:
            events.write(json.dumps({"kind": "click_up", "button": button.name, "pos": pos,
                                     "t": round(time.time() - start, 2)}) + "\n")


def on_scroll(x, y, dx, dy):
    pos = to_game(x, y)
    if pos is not None and game_active():
        record("scroll", pos=pos, dy=dy)


game = forge.Game()
mouse_ctl = mouse.Controller()
print(f"Recording to {out_dir} - play the cycle in the game, press F10 to stop.")
mouse.Listener(on_click=on_click, on_scroll=on_scroll).start()
keyboard.Listener(on_press=on_press, on_release=on_release).start()
while not stop.wait(PERIODIC_SHOT):
    if game_active():
        with lock:
            snapshot("tick")
print(f"Stopped. {shot_n} screenshots in {out_dir}")

import pyautogui
import keyboard
import time

ofset = 20



while keyboard.is_pressed('q') == False :
    time.sleep(.1)
    x, y = pyautogui.position()
    px = pyautogui.pixel(x-ofset, y)
    color_to_look_for = (167, 52, 19)
    if px == color_to_look_for:
        print("Found the color at position:", (x-ofset, y))
    print(px)

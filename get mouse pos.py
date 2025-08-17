import pyautogui
import keyboard
import time


while keyboard.is_pressed('q') == False :
    time.sleep(.15)
    print(pyautogui.position())

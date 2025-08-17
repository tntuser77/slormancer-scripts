import pyautogui
import keyboard
import time
import pytesseract as tess
from PIL import Image
from dataclasses import dataclass
import os
tess.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


first_reward_start = (550, 690)
second_reward_start = (925, 690)
third_reward_start = (1280, 690)

first_challenge_duration_start = (463, 625)
second_challenge_duration_start = (835, 625)
third_challenge_duration_start = (1199, 625)


first_box_starting_pos = (463, 494)
second_box_starting_pos = (835, 492)
third_box_starting_pos = (1199, 493)

first_click_pos = (595, 570)
second_click_pos = (965, 570)  
third_click_pos = (1325, 570)

@dataclass
class Challenge:
    text: str
    duration: int
    reward_type: str
    reward_num: int    
    prority: int
    click_pos: tuple = (0, 0)

def get_reward_type(starting_pos):
    reward_width = 100
    reward_height = 50
    reward_type = None
    pyautogui.screenshot("reward.png", region=(starting_pos[0], starting_pos[1], reward_width, reward_height))
    for image_path in os.listdir("images/"):
        if image_path.endswith(".png"):
            try:
                reward_type = pyautogui.locateOnScreen(
                    f"images/{image_path}",
                    region=(starting_pos[0], starting_pos[1], reward_width, reward_height),
                    confidence=0.7
                )
            except Exception as e:
                print(f"Error locating image {image_path}: {e}")
                continue
            if reward_type is not None:
                return image_path.split('.')[0]
    if reward_type is None:
        raise Exception("Could not find reward type")
    

def get_challenge_text(starting_pos):
    width = 258
    hight = 134
    image = pyautogui.screenshot("challenge.png", region=(starting_pos[0], starting_pos[1], width, hight))
    text = tess.image_to_string(image)
    return text

def get_challenge_duration(starting_pos):
    duration_width = 245
    duration_hight = 37
    image = pyautogui.screenshot("duration.png", region=(starting_pos[0], starting_pos[1], duration_width, duration_hight))
    text = tess.image_to_string(image)
    for part in text.split():
        if part.isdigit():
            return int(part)
    if "rest of the exp" in text.lower():
        return 0
    raise Exception("Could not get duration")  

def first_text_priority(text):
    if "decreased" in text.lower():
        return -100000
    elif "duration" in text.lower():
        return 15
    elif "increased" in text.lower():
        return -5
    elif "invin" in text.lower():
        return -5
    elif "ignore" in text.lower():
        return -8 
    elif "clone" in text.lower():
        return -8 
    elif "rarity" in text.lower():
        if "epic" in text.lower():
            return 15
        elif "legendary" in text.lower():
            return 25
        return 0
    elif "attack speed mul" in text.lower():
        return -10 
    elif "Increased Damage mul" in text.lower():
        return -10
    elif "max life mul" in text.lower():
        return -10
    return 0



first_challenge = Challenge(
    text=get_challenge_text(first_box_starting_pos),
    duration=get_challenge_duration(first_challenge_duration_start),
    reward_type=get_reward_type(first_reward_start),
    reward_num=100,
    prority=0,
    click_pos=first_click_pos
)

second_challenge = Challenge(
    text=get_challenge_text(second_box_starting_pos),
    duration=get_challenge_duration(second_challenge_duration_start),
    reward_type=get_reward_type(second_reward_start),
    reward_num=100,
    prority=0,
    click_pos=second_click_pos
)

third_challenge = Challenge(
    text=get_challenge_text(third_box_starting_pos),
    duration=get_challenge_duration(third_challenge_duration_start),
    reward_type=get_reward_type(third_reward_start),
    reward_num=100,
    prority=0,
    click_pos=third_click_pos
)

print(f"First Challenge: {first_challenge.text}, Duration: {first_challenge.duration}, Reward: {first_challenge.reward_type} {first_challenge.reward_num}, Priority: {first_challenge.prority}")
print(f"Second Challenge: {second_challenge.text}, Duration: {second_challenge.duration}, Reward: {second_challenge.reward_type} {second_challenge.reward_num}, Priority: {second_challenge.prority}")
print(f"Third Challenge: {third_challenge.text}, Duration: {third_challenge.duration}, Reward: {third_challenge.reward_type} {third_challenge.reward_num}, Priority: {third_challenge.prority}")
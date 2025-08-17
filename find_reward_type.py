from dataclasses import dataclass
import pyautogui
import time


@dataclass
class Reward:
    reward_type: str
    first_pos: tuple
    color: tuple
    second_pos: tuple = None
    third_pos: tuple = None

    def __post_init__(self):
        self.second_pos = (self.first_pos[0] + 368, self.first_pos[1])
        self.third_pos = (self.first_pos[0] + 736, self.first_pos[1])
    pass
        
""""



Found the color at position: (593, 689)
(167, 52, 19)

"""


rewards = [
    Reward( reward_type="Slorm", first_pos=(586, 729), color=(97, 247, 183)),
    Reward( reward_type="Equipment", first_pos=(578, 714), color=(113, 36, 24)),
    Reward( reward_type="Fragment", first_pos=(594, 710), color=(245, 193, 102)),
    Reward( reward_type="Asotrias", first_pos=(577, 720), color=(180, 38, 16)),
    Reward( reward_type="Goldus", first_pos=(590, 725), color=(222, 213, 85)),
    Reward( reward_type="Fulgororn", first_pos=(581, 744), color=(12, 119, 239)),
    Reward( reward_type="Beigarth", first_pos=(592, 743), color=(253, 227, 67)),
    Reward( reward_type="Slormline", first_pos=(570, 736), color=(26, 116, 195)),
    Reward( reward_type="Adrianne", first_pos=(594, 728), color=(223, 250, 134)),
    Reward( reward_type="Hagan", first_pos=(586, 739), color=(96, 245, 184)),
    Reward( reward_type="Quant", first_pos=(586, 726), color=(221, 156, 35)),
    Reward( reward_type="Smaloron", first_pos=(586, 716), color=(172, 56, 193)),
    Reward( reward_type="Cory", first_pos=(578, 733), color=(208, 20, 43)),

]



def find_leg_reward(num_challenge):
    unit_ofset = 368
    pyautogui.moveTo(591+(unit_ofset*num_challenge), 732) # move mouse to get hover text
    image = pyautogui.screenshot("leg_reward.png", region=(123+(unit_ofset*num_challenge), 520, 405, 135))


def find_reward_type(num_challenge):
    pyautogui.moveTo(972, 55) # Move the mouse to the top center of the screen so that the pixel color can be checked
    unit_ofset = 368
    if pyautogui.pixelMatchesColor(593+(unit_ofset*num_challenge), 689, (167, 52, 19)):
        return find_leg_reward(num_challenge)
    if num_challenge == 0:
        for reward in rewards:
            if pyautogui.pixelMatchesColor(reward.first_pos[0], reward.first_pos[1], reward.color):
                return reward.reward_type
    elif num_challenge == 1:
        for reward in rewards:
            if pyautogui.pixelMatchesColor(reward.second_pos[0], reward.second_pos[1], reward.color):
                return reward.reward_type
    elif num_challenge == 2:
        for reward in rewards:
            if pyautogui.pixelMatchesColor(reward.third_pos[0], reward.third_pos[1], reward.color):
                return reward.reward_type
    return "Unknown"

for i in range(3):
    print(f"Reward type for challenge {i}: {find_reward_type(i)}")
    time.sleep(.1)

colors = []
for reward in rewards:
    colors.append(reward.color)
if len(colors) != len(set(colors)):
    print("Duplicate colors found!")
else:
    print("No duplicate colors found.")

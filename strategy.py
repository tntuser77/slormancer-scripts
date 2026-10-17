"""How forge.py scores cards. Reloaded before every pick, so edit it mid-run.

Based on the "Manipulating The Forge" v1.0 summary:
  - pick the challenge with the most waves (removes it from the pool)
  - prioritise: next challenge Epic/Legendary, +challenge duration,
    War Chest Quantity curse, Slorm conversion rewards
  - avoid: next challenge Magic/Rare, non-duration challenges, obelisks
Plus (Elijah):
  - an effect that lasts the rest of the expedition for one resource switches
    the run's goal to that resource; one-off "you immediately..." effects don't
  - challenges that last the rest of the forge are actively bad, unless the
    reward is a strong rest-of-run effect
"""

# What you're farming at the start of a run: "goldus", "slorm", "slormite",
# "spirits" or "elder_slorm". A rest-of-run effect can switch it mid-run.
GOAL = "slormite"
SWITCH_ON_LASTING = True
# Effects that last the whole run without saying "for the rest of the
# Expedition" (that wording is detected from the game data automatically).
LASTING_EXTRA = {13, 34}

# Reward preference per goal, best first. Names are the game's tooltip names
# (REWARD_NAMES in forge.py). "Spirit" covers every Reapersmith Spirit type.
REWARD_PRIORITY = {
    "goldus": ["Goldus Quantity", "War Chest Quantity", "Slorm Quantity", "Equipment Quality"],
    "slorm": ["Slorm Quantity", "War Chest Quantity", "Equipment Quality"],
    "slormite": ["War Chest Quantity", "Slormite Quality", "Slormeline Quality", "War Chest Quality"],  # quantity: quality has diminishing returns
    "spirits": ["Spirit", "War Chest Quantity"],
    "elder_slorm": ["Slorm Quantity", "War Chest Quantity"],
}
# Rewards worth real points in every goal, not just a tiebreak.
# Priority ladder (Elijah): 1) giga effects 300  2) anything giving War Chest
# Quantity 200  3) upgrades / Attrition / obelisks / good effects 55-70
# 4) duration 10 per wave  5) basic quality rewards only break ties.
REWARD_BONUS = {"War Chest Quantity": 200}  # tier 2: beats a 15-wave card

# Points for 1st, 2nd, 3rd... entry of the goal's list. Anything unlisted gets 0.
# Kept below POINTS_PER_WAVE so reward only breaks ties between equal durations.
REWARD_POINTS = [4, 3, 2, 1]

# Each wave of duration is worth this much. Duration comes first (guide).
POINTS_PER_WAVE = 10
# Challenges lasting the rest of the forge: worse than any normal reward is good.
REST_OF_RUN_CHALLENGE_POINTS = -40
# Cards that show 'Rest of the Expedition' but don't make the fight harder.
NO_REST_OF_RUN_PENALTY = {"Attrition Battle", "Upgrade"}
# Siege Leader challenges are fine against Normal/Magic rewards: score them like
# a 5-wave challenge instead of the rest-of-run penalty.
SIEGE_LEADER_POINTS = 50

# --- Special War Chest effects (Epic/Legendary rewards) ----------------------
# Game ref (dat_for.json) -> (goal it feeds or "any", tier). "run" = lasts the
# rest of the expedition (switches the goal if it feeds one resource); "now" =
# one-off. First-pass ratings: adjust freely.
SPECIAL_REWARDS = {
    4: ("any", "great"),      # run: Chest Quantity becomes equal to Chest Quality (Quality is stacked)
    5: ("any", "good"),       # run: +Chest Quality per type of loot in the chest
    6: ("spirits", "ok"),     # now: every spirit type raised to the highest type's amount
    7: ("goldus", "great"),   # now: Goldus = X% of chest Slorm. Beats basic picks, not giga
    8: ("slorm", "ok"),       # now: +Slorm per Reapersmith Spirit in the chest
    9: ("any", "ok"),         # now: +Equipment Quality per Equipment in the chest
    10: ("slormite", "ok"),   # now: +Slormite Quality per Slormite in the chest
    11: ("slormite", "ok"),   # now: +Slormeline Quality per Slormeline in the chest
    12: ("slormite", "meh"),  # now: +Fragment Quality per Slormite/Slormeline
    13: ("elder_slorm", "giga"),  # run (at looting): X% of Slorm becomes Elder Slorm
    14: ("any", "ok"),        # now: Equipment Quality -> Chest Quality
    15: ("any", "quantity"),  # now: Slorm Quantity -> Chest Quantity (Quantity is king)
    16: ("goldus", "giga"),   # run: +Goldus Quantity per Elite kill
    17: ("goldus", "giga"),   # run: Goldus in chest increased every wave
    18: ("any", "good"),      # run: +Chest Quality every wave
    19: ("any", "giga"),      # run: +Chest Quantity every wave
    20: ("spirits", "giga"),  # run: chance per kill to add spirits
    21: ("any", "good"),      # run: Normal challenge rewards increased
    22: ("spirits", "giga"),  # run: rewards increased while holding every spirit type
    23: ("goldus", "ok"),     # now: all Quality bonuses -> Goldus Quantity
    24: ("slormite", "ok"),   # now: Slorm + Goldus Quantity -> Slormeline Quality
    25: ("spirits", "ok"),    # now: every spirit += Slorm Quantity
    26: ("spirits", "meh"),   # now: convert spirits to your reaper's type
    27: ("spirits", "meh"),   # now: convert spirits to your most common type
    28: ("any", "good"),      # now: spirits -> Goldus; spirits pile up, so this pays a lot (Elijah)
    29: ("spirits", "meh"),   # now: every spirit += Fragment Quality
    30: ("any", "good"),      # now: all loot increased by current Chest Quality
    31: ("any", "meh"),       # spirits per Allied Obelisk each wave
    32: ("any", "meh"),       # run: Allied Obelisk rewards increased
    33: ("any", "meh"),       # run: Equipment Quality per wave with a hostile Obelisk
    34: ("spirits", "giga"),  # run: following rewards are only spirits, but increased
    35: ("any", "good"),      # keep the chest's bonuses if you die (safety)
    # Obelisk card rewards: destroy the obelisk (5-10 waves for this build) and
    # it pays out every wave after. Only worth it before OBELISK_LAST_WAVE.
    36: ("any", "meh"),       # Allied Obelisk: spirits per wave
    37: ("goldus", "ok"),     # Allied Obelisk: Goldus Quantity per wave
    38: ("any", "decent"),    # Allied Obelisk: Chest Quality per wave
    39: ("any", "quantity"),  # Allied Obelisk: Chest Quantity per wave
    40: ("any", "meh"),       # Allied Obelisk: Equipment Quality per wave
}
# Elder Slorm pays the forge entry fee and has a cap. How full you are (0-1,
# check in-game and update): near the cap, the conversion effect barely matters.
ELDER_SLORM_FILL = 1.0  # 177 303 / 177 303 seen on the expedition panel, 2026-10-16
SPECIAL_REWARDS[13] = (
    "elder_slorm" if ELDER_SLORM_FILL < 0.5 else "any",  # "any" = never switches the goal
    "giga" if ELDER_SLORM_FILL < 0.3 else "good" if ELDER_SLORM_FILL < 0.8 else "meh",
)

TIER_POINTS = {"giga": 300, "quantity": 200, "great": 70, "good": 60, "decent": 40, "ok": 20, "meh": 0}
# Effects below "great" for a different goal than the current one get this share.
OFF_GOAL_SHARE = 0.3
# A special reward the script couldn't identify (logged with a screenshot).
UNKNOWN_SPECIAL_POINTS = 30

# --- Challenge rules -----------------------------------------------------------
# (challenge name, text it must contain or "", points, judgement call).
# Names are matched against the game's own list, so spelling matters.
RULES = [
    ("Upgrade", "legendary", 65, False),  # beats any 5-wave card
    ("Upgrade", "epic", 60, False),  # beats any 5-wave card
    ("Upgrade", "rare", -40, False),
    ("Upgrade", "magic", -40, False),
    ("Attrition Battle", "", 60, False),  # +challenge duration; beats any 5-wave card
    ("Nullifying Shield", "", -30, False),  # hard for this build: about -3 waves
    ("Overcrowding", "", -30, False),
    ("Ace Combat", "", -30, False),
    ("Highlander", "", -30, False),
    # Obelisks: destroying one takes this build 5-10 waves, so it counts like a
    # 5-6 wave challenge; its Allied reward (SPECIAL_REWARDS 36-40) is added on top.
    ("Obelisk of Transmutation", "", 55, False),
    ("Obelisk of Destruction", "", 55, False),
    ("Obelisk of Illusion", "", 55, False),
    ("Obelisk of Annihilation", "", 55, False),
    ("Obelisk of Revocation", "", 55, False),
    # Gates (first pick of a run, costs Elder Slorm): always 6 gates.
    # "Let. Them. Come." = 6 locations; the others are 2, 4 or +1.
    ('"Let. Them. Come."', "", 500, False),
    ('"Set up the Barricades!"', "", 0, False),
    ('"Open the Gates!"', "", 0, False),
    ('"Is That All?!"', "", 0, False),
]

# --- Curses ---------------------------------------------------------------------
# There are only 3 curses, and the reward on the curse card says which one:
#   War Chest Quantity (small) -> enemy attack speed, the safest: take it
#   Spirit                     -> big enemy damage boost
#   Goldus                     -> huge enemy HP boost ("murders your computer")
# Curse cards skip the rest-of-run penalty; these points replace the reward score.
CURSE_CARDS = {"Cursed Reward", "Curse"}
CURSE_BY_REWARD = {"War Chest Quantity": 200, "Spirit": -150, "Goldus Quantity": -300}
CURSE_UNKNOWN_REWARD = -150

# Obelisk challenges are fine for this build (turrets handle them), but an
# obelisk taken late doesn't have enough waves left to pay out.
OBELISK_LAST_WAVE = 85
OBELISK_LATE_POINTS = -150  # late obelisks lose to any normal card

# Per-goal tweaks on top of RULES: {goal: {challenge name: points}}.
GOAL_OVERRIDES = {
    "spirits": {name: 0 for name, *_ in RULES if name.startswith("Obelisk")},
}

# --- When to hand the pick to a human --------------------------------------------
# Judgement calls: these rarities, flagged RULES, unrecognised cards, and top
# two scores closer than ASK_MARGIN (0 = never). The script beeps and waits
# HUMAN_WAIT seconds for you to pick; if the screen is still up after that it
# picks the best card itself. 0 = never wait.
ASK_ON_RARITY = {"Epic", "Legendary", "Cursed"}
ASK_ON_UNKNOWN = True
ASK_MARGIN = 0
HUMAN_WAIT = 30
# Rest-of-run versions of these are a judgement call (you might skip them).
ASK_IF_REST_OF_RUN = {"Nullifying Shield"}

# Reading reward amounts costs time and nothing uses them yet.
READ_AMOUNTS = False

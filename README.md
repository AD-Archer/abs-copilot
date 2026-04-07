# ABS Candidate Take-Home Dataset

## Files included
- `abs_challenges.csv`: one row per ABS challenge, with challenge outcomes recomputed from the corrected ABS calls
- `pitches.csv`: all called pitches from games where ABS was available
- `players.csv`: player lookup table

## Scope
- 4 teams
- 56 players total
- 180 games
- 30,559 called pitches
- 859 ABS challenges

## Strike zone assumptions
For simplicity, all players are treated as 6 feet tall (sz = strike zone)
- sz_top = 3.21 feet
- sz_bot = 1.62 feet

The ABS strike zone is defined horizontally as:
- pitch_x between -0.708 and +0.708 feet

A pitch is an ABS strike when:
- -0.708" <= pitch_x <= 0.708"
- 1.62" <= pitch_z <= 3.21"


## Other notes
- challenge_id is the common join column between abs_challenges.csv and pitches.csv
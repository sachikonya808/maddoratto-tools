# CUSTOM SONGS

## WORKFLOW FOR ADDING A NEW SONG

- Grab a copy of your Sound.dat and Rhythm.dat
- With sounddat.py use ``python sounddat.py export Sound.dat songs.json``, this will dump the song list IDs into a JSON file
- [Open a Dec2Hex calculator](https://www.rapidtables.com/convert/number/decimal-to-hex.html)
- Pick a song you want to use as a base! (In this example I will use "MAD RAT, ALIVE?", which has a numeric ID of 15 and a hex value of 0x0F
- Base+DLC songs start at BGM001 and end at BGM043, so BGM044 and onwards are free (In this case I will pick 44, which has a hex value of 2C)
- If you're editing the charts, use ``python rhythm_export.py --target BGM015 --output normal.txt`` to dump the chart for Normal mode; dump the ones from Hard mode with ``python rhythm_export.py --target BGM015 --output hard.txt --hard``
- [Create your custom sound.acb file](SOUND.md)

#### [RattoLauncher](https://github.com/sachikonya808/maddoratto-pc/releases)
- Create a new mod_song.zip (Check instructions below)
- Move the mod_song.zip to %APPDATA%/Roaming/RattoLauncher/mods/songs
- In the launcher, navigate to the Songs tab, and hit "ADD SONGS"
- !!! PROBE YOUR SAVE DATA WITH THE "UNLOCK SAVE" BUTTON !!! This is necessary because if you skip this, the new song will appear locked "???"

#### Python scripts only
- Once you're done with the charts, add them to Rhythm.dat using ``python rhythm_addsong.py --target BGM044 --normal normal.txt --hard hard.txt --bpm N``, where N is your New BPM value (Untested!)
- If you're not editing the charts, just use ``python rhythm_addsong.py --target BGM044 --from-song BGM015``, this will clone the chart from BGM015 (MAD RAT, ALIVE?) into our new entry (BGM044)
- With sounddat.py use ``python.exe .\sounddat.py clone .\Sound.dat Sound_new.dat --from 0x0F --id 0x2C --title "Title of the Song" --composer "Composer" --bpm N --str0c BGM015``
- !!! PROBE YOUR SAVE DATA WITH probe.py ``python probe.py System 0x2C --sound Sound_new.dat`` !!! This is necessary because if you skip this, the new song will appear locked "???"
- Take Rhythm_new.dat, Sound_new.dat and move them into your LayeredFS Data/Database folder, rename them to Rhythm.dat and Sound.dat
- If you changed the song, you need to also add your new BGM044.acb into your LayeredFS Data/Sound folder

<br>

- Test in-game

## How to pack a new mod:

Download ``ExampleMod.zip`` and extract it.<br>

Edit the fields in pack.json:
- Title: Song's title
- Composer: Song's composer
- BPM: Song's BPM (if you don't add a custom chart, use the same BPM as the song you're cloning to avoid chart issues!)
- BaseID: Numeric ID of the song you cloned (ie. 15)
- CustomCharts: true/false depending if you're adding custom charts (true) or reusing the custom ones (false)
- NormalDifficulty: The normal difficulty of the song (displayed as stars on the Selection Screen, goes from 1 to 5, defaults to 1)
- HardDifficulty: The normal difficulty of the song (displayed as stars on the Selection Screen, goes from 1 to 5, defaults to 2)

Add your custom ``pack.png``, ``sound.acb``, and ``normal.txt``/``hard.txt`` charts if you are making custom charts. Once you're done, compress the files back into a .zip and add it to your mods/songs folder to test.

## Known token encodings (Chart editing)

| Observed symbol / form | Bytes | Length | Text symbol (tools) | Count in file | Use |
|---|---|---:|:---:|---:|---:|
| `.` (empty token) | `00` | 1 | `.` | 441,080 | Skip (unconfirmed) |
| `M` | `E3 83 BB 00` | 4 | `M` | 78,610 | Silence (confirmed) |
| `O` | `E2 97 8B 00` | 4 | `O` | 24,592 | End beat (confirmed) |
| `P` | `E2 97 8F 00` | 4 | `P` | 2,655 | Start beat (confirmed) |
| O plus modifier / X-like form | `E2 97 8B E2 96 B2 38 00` | 8 | `X` | 257 | First beat of the song (unconfirmed) |
| P plus modifier | `E2 97 8F E2 96 B2 38 00` | 8 | `Y` | 3 | Unknown |
| M plus modifier | `E3 83 BB E2 96 B2 38 00` | 8 | `Z` | 2 | Unknown |
| O plus modifier (short form) | `E2 97 8B E2 96 B2 00` | 7 | `S` | 1 | Unknown |

# ALWAYS REFER TO THE BASE GAME CHARTS

#### Observed patterns:

#### Example 1:
- OMMM <- Regular notes
- OMMM
- OMMM => ( ( ( O ) ) )

#### Example 2:
- OMMM
- OMPM <- Red note
- OMMM => ( (-( ( O ) )-) )

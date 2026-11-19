 - YKCMP: https://github.com/iltrof/ykcmp


## WORKFLOW FOR ADDING A NEW SONG

- Grab a copy of your Sound.dat and Rhythm.dat
- With sounddat.py use ``python sounddat.py export Sound.dat songs.json``, this will dump the song list IDs into a JSON file
- [Open a Dec2Hex calculator](https://www.rapidtables.com/convert/number/decimal-to-hex.html)
- Pick a song you want to use as a base! (In this example I will use "MAD RAT, ALIVE?", which has a numeric ID of 15 and a hex value of 0x0F
- Base+DLC songs start at BGM001 and end at BGM043, so BGM044 and onwards are free (In this case I will pick 44, which has a hex value of 2C)
- If you're editing the charts, use ``python rhythm_export.py --target BGM015 --output normal.txt`` to dump the chart for Normal mode; dump the ones from Hard mode with ``python rhythm_export.py --target BGM015 --output hard.txt --hard``
- Once you're done with the charts, add them to Rhythm.dat using ``python rhythm_addsong.py --target BGM044 --normal normal.txt --hard hard.txt --bpm N``, where N is your New BPM value (Untested!)
- If you're not editing the charts, just use ``python rhythm_addsong.py --target BGM044 --from-song BGM015``, this will clone the chart from BGM015 (MAD RAT, ALIVE?) into our new entry (BGM044)
- With sounddat.py use ``python.exe .\sounddat.py clone .\Sound.dat Sound_new.dat --from 0x0F --id 0x2C --title "Title of the Song" --composer "Composer" --bpm N --str0c BGM015``
- !!! PROBE YOUR SAVE DATA WITH probe.py ``python probe.py System 0x2C --sound Sound_new.dat`` !!! This is necessary because if you skip this, the new song will appear locked "???"
- Take Rhythm_new.dat, Sound_new.dat and move them into your LayeredFS Data/Database folder, rename them to Rhythm.dat and Sound.dat
- If you changed the song, you need to also add your new BGM044.acb into your LayeredFS Data/Sound folder
- Test in-game

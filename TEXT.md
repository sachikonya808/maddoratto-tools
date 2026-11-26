# TEXT
## Dumping the text strings
- Download ``talkdat.py`` and ``talkrebuild.py``
- Run ``python talkdat.py Talk.dat talk.json`` (You'll need a copy of Talk.dat in the same directory as the script!)

This will output an editable talk.json file

## Rebuilding Talk.dat

- Run ``python talkrebuild.json``

This will take the talk.json file and rebuild it into a Talk_new.dat that you must load through LayeredFS

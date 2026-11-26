# Usage: python talkrebuild.json
# This will take the talk.json file and rebuild it into a Talk_new.dat that you must load through LayeredFS

import json
from talkdat import load, build

flag, ents = load("Talk.dat")
edited = json.load(open("talk.json", encoding="utf8"))

for e, j in zip(ents, edited):
    e["pages"] = j["pages"]
    e["end"] = j["end"]

open("Talk_new.dat", "wb").write(build(ents, flag))
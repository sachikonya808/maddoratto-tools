# Usage: python talkrebuild.json
# This will take the talk.json file and rebuild it into a Talk_new.dat that you must load through LayeredFS

import json
from talkdat import load, build

hdr, flag, ents = load("Talk.dat")        # original, used to keep the storage order
edited = json.load(open("talk.json", encoding="utf8"))

# copy the edited fields back onto the loaded entries
for e, j in zip(ents, edited):
    e["text"] = j["text"]
    e["u"] = j["u"]
    e["tail"] = j["tail"]

open("Talk_new.dat", "wb").write(build(ents, flag))
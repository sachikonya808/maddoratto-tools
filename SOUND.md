# SOUND

## Fields to edit on your custom .xml

#### CRIUTF name="Block"
- SampleCount
- StartPosition = (Sum of previous length values (0 -> 0 | 1 -> length(0) | 2 -> length(0) + length(1) | 3 -> length(0) + length(1) + length(3))
#### CRIUTF name="Block"
- Length = (SampleCount/48000)*1000
#### CRIUTF name="TrackEvent"
- ACBCMD delay value = Length

Anything else can cause odd behavior!

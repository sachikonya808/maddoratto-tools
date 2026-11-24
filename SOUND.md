# SOUND

## Sound basics

For this you'll need ``cri_utf_tool`` from [KwasTools](https://github.com/ThisKwasior/KwasTools/), ``VGAudioCli`` from [VGAudio](https://github.com/Thealexbarney/VGAudio), a sound editor, and preferably (but not required), a code editor like [VSCodium](https://github.com/VSCodium/vscodium)

- If you haven't, pick a song to use as a base and grab the respective ``BGMXXX.acb`` file from romfs/Data/Sound
- Drag the BGM file into ``cri_utf_tool``, this will generate you a ``BGMXXX.acb_00`` folder containing your .hca files and a ``BGMXXX.acb.xml`` file
- Edit your song so it fits the 4-Block structure of MAD RAT DEAD songs (Use the extracted .hca files as reference)
- Once you're done, export your 4 Sound files as ``.wav`` audio, with a sample rate of 48000, and PCM-16 encoding
- Use ``cri_utf_tool`` to convert them to .hca
- Edit your ``BGMXXX.acb.xml`` to match the new sound data (More info down below)
- Replace the old ``.hca`` files inside ``BGMXXX.acb_00`` with your new ones
- Once you're done, drag ``BGMXXX.acb.xml`` into ``cri_utf_tool`` to pack everything back into a ``.acb`` file

## Useful commands

### .hca -> .wav
- ``VGAudioCli 00000.hca 0.wav``
### .wav -> .hca
- ``VGAudioCli 0.wav 00000.hca``
### Get Sample Count from .hca file
- ``VGAudioCli -m 00000.hca``

## Fields to edit on your custom .xml

#### CRIUTF name="Block"
- NumSamples
- StartPosition = (Sum of previous length values (0 -> 0 | 1 -> length(0) | 2 -> length(0) + length(1) | 3 -> length(0) + length(1) + length(3))
#### CRIUTF name="Block"
- Length = (NumSamples/48000)*1000
#### CRIUTF name="TrackEvent"
- ACBCMD delay value = Length

Anything else can cause odd behavior!

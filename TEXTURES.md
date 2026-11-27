# TEXTURES

## Dumping the textures
- Download ``mrd_texture_dumper.py`` and [ykcmp.exe](https://github.com/iltrof/ykcmp)
- Switch version: Run ``python mrd_texture_dumper.py ykcmp.exe --switch Anime_EN.dat --out out``
- PS4 version: Run ``python mrd_texture_dumper.py ykcmp.exe --ps4 Anime_EN.dat --out out``
- Single file extract: Run ``python mrd_texture_dumper.py ykcmp.exe --switch Anime_EN.dat --out out --indices 67``

This will output one or more texture files in .png format, ready for editing

## Applying textures

- Download and set-up [RattoLauncher](https://github.com/sachikonya808/maddoratto-pc/releases)
- Navigate to the "Textures" tab
- First hit the "Prepare" button to index the Anime_EN.dat file and generate a texture_metadata.json file
- This file contains the fingerprint for every texture file, and its Block Number
- Identify the texture you want to edit by it's block number and then copy the fingerprint hash (ie. image with the block 168 could have a hash of 4f1eca1ca5d71b0b)
- Once you have the edited texture ready, export it as .png and name it using this convention: <hash>_WxH.png (Example: a5b0f704f2e9a8fe_2048x2048.png)
- Go back to the mods tab, click browse to open the mods folder, and place the texture there. Finally, hit the "Build" button to write a new Anime_EN.dat to the game's mods folder

# Bundled fonts

Card renderers load these so images look the same on every host instead of
falling back to whatever system font is installed.

| File | Family | Source | Licence |
|---|---|---|---|
| `Roboto-Regular.ttf`, `Roboto-Bold.ttf` | Roboto | Google Fonts | SIL OFL 1.1 (`OFL-Roboto.txt`) |
| `BarlowCondensed-SemiBold.ttf`, `BarlowCondensed-Bold.ttf` | Barlow Condensed | Google Fonts | SIL OFL 1.1 (`OFL-BarlowCondensed.txt`) |
| `Lora-Regular.ttf`, `Lora-Bold.ttf` | Lora | Google Fonts | SIL OFL 1.1 (`OFL-Lora.txt`) |

Roboto covers Latin, Cyrillic and Greek. Barlow Condensed is Latin only, so
text it cannot draw falls back to Roboto (see `graphics/assets.py`).

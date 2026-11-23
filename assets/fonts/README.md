# Bundled fonts

Card renderers load these so images look the same on every host instead of
falling back to whatever system font is installed.

| File | Family | Source | Licence |
|---|---|---|---|
| `Roboto-Regular.ttf`, `Roboto-Bold.ttf` | Roboto | Google Fonts | SIL OFL 1.1 (`OFL-Roboto.txt`) |
| `Lora-Regular.ttf`, `Lora-Bold.ttf` | Lora | Google Fonts | SIL OFL 1.1 (`OFL-Lora.txt`) |

Roboto covers Latin, Cyrillic and Greek. Text with characters it cannot draw
(for example CJK names) falls back to a system font; see `readable_font` in
`graphics/assets.py`.

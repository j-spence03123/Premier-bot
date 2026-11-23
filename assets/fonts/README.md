# Bundled fonts

Card renderers load these so images look the same on every host instead of
falling back to whatever system font is installed.

| File | Family | Source | Licence |
|---|---|---|---|
| `Roboto-Regular.ttf`, `Roboto-Bold.ttf` | Roboto | Google Fonts | SIL OFL 1.1 (`OFL-Roboto.txt`) |
| `Lora-Regular.ttf`, `Lora-Bold.ttf` | Lora | Google Fonts | SIL OFL 1.1 (`OFL-Lora.txt`) |
| `NotoSansSC-Regular.ttf`, `NotoSansSC-Bold.ttf` | Noto Sans SC | Google Fonts | SIL OFL 1.1 (`OFL-NotoSansSC.txt`) |

Roboto covers Latin, Cyrillic and Greek. Text it can't draw uses Noto Sans SC,
which adds Chinese (simplified and traditional), Japanese and more symbols, and
anything neither covers (Korean, Thai, Arabic) uses a system font. See
`readable_font` in `graphics/assets.py`.

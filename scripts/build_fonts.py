"""Build the app's web fonts (app/static/fonts/*.woff2) from the Google Fonts sources.

The pages use 도현 (Do Hyeon) for titles, 나눔고딕 (Nanum Gothic) for text and Rubik for numbers, all under
the SIL Open Font License. The app loads nothing from a CDN, so the fonts ship with it, cut down to what
Korean text needs: ASCII, common punctuation and the 2,350 Hangul syllables of KS X 1001. A rarer syllable
falls back to the phone's own font for that one character.

Needs fonttools and brotli (not app requirements):
    python -m pip install fonttools brotli
    python scripts/build_fonts.py <folder with the .ttf files from github.com/google/fonts/tree/main/ofl>
"""
import sys
from pathlib import Path

from fontTools import subset

OUT = Path(__file__).resolve().parents[1] / "app" / "static" / "fonts"
# Source file in the google/fonts checkout (flattened as dir_file) → output name.
FONTS = {
    "dohyeon_DoHyeon-Regular.ttf": "do-hyeon.woff2",
    "nanumgothic_NanumGothic-Regular.ttf": "nanum-gothic-400.woff2",
    "nanumgothic_NanumGothic-Bold.ttf": "nanum-gothic-700.woff2",
    "rubik_Rubik[wght].ttf": "rubik.woff2",
}
PUNCTUATION = "·…–—‘’“”×÷±≤≥→←↑↓▲▼°%‰€₩·•"


def ks_hangul() -> str:
    """The Hangul syllables EUC-KR can encode: the everyday set."""
    syllables = []
    for code in range(0xAC00, 0xD7A4):
        char = chr(code)
        try:
            char.encode("euc-kr")
        except UnicodeEncodeError:
            continue
        syllables.append(char)
    return "".join(syllables)


def main(source: Path) -> None:
    latin = "".join(chr(code) for code in range(0x20, 0x7F)) + PUNCTUATION
    korean = latin + ks_hangul() + "".join(chr(code) for code in range(0x3131, 0x318F))
    OUT.mkdir(exist_ok=True)
    for name, target in FONTS.items():
        options = subset.Options()
        options.flavor = "woff2"
        options.layout_features = ["*"]
        options.name_IDs = ["*"]  # keep the copyright and licence names
        font = subset.load_font(str(source / name), options)
        subsetter = subset.Subsetter(options)
        subsetter.populate(text=latin if target.startswith("rubik") else korean)
        subsetter.subset(font)
        subset.save_font(font, str(OUT / target), options)
        print(target, (OUT / target).stat().st_size // 1024, "KB")


if __name__ == "__main__":
    main(Path(sys.argv[1]))

"""Interface text is translated, not just present (audit M3).

tests/test_i18n.py checks key parity and non-empty values. That is why 34
strings could sit in the tree as verbatim English in ten of the twelve
languages while the README and the release body advertised "12 languages": the
bulk `update()` pattern adds every key to every language with the English value
first, which guarantees non-emptiness and nothing else. The RECORDING and
CAPTURE tabs were English in French, German, Spanish, Italian, Portuguese,
Polish, Ukrainian, Chinese, Japanese and Korean; Russian was the only table
that had been translated.

This test states the rule the module docstring already warns about: a string
the user reads must be in the user's language. Two things keep it honest:

* a small, explicit list of strings that are NOT translated on purpose - brand
  names, product terms and endonyms (NR, FG, NVOFA, DLSS, Boost, "English",
  "30 fps"). Anything else that matches English in every language is a miss.
* the same check per language: a key translated in nine languages and English
  in the tenth is a miss for that one, which the all-languages rule would hide.

Run:  runtime\\python.exe tests\\test_i18n_translated.py
"""
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from i18n import STRINGS  # noqa: E402

#: Not translated on purpose, in any language.
TERMS = {
    "title",            # the product name
    "nr_short", "fg_short", "fg_on", "fg_off",  # NR / FG indicators
    "motion_nvofa",     # the backend's own name
    "boost",            # the feature's name
    "about_windows",    # "Windows"
    "frame_generation",  # "DLSS Frame Generation"
}
#: Language names are endonyms: each is written in its own language.
LANG_KEYS = {key for key in STRINGS["en"] if key.startswith("lang_")}
#: Numbers with a unit: "30 fps" is the same in every language here.
NUMERIC = {"frame_limit_30", "frame_limit_60"}

SKIP = TERMS | LANG_KEYS | NUMERIC


def main() -> int:
    failures = []
    en = STRINGS["en"]
    langs = [lang for lang in STRINGS if lang != "en"]
    if not langs:
        print("FAIL: there is only one language table - this test covers "
              "nothing")
        return 1

    for key, value in sorted(en.items()):
        if key in SKIP or not isinstance(value, str) or not value.strip():
            continue
        same = [lang for lang in langs if STRINGS[lang].get(key) == value]
        # English itself is the source; "identical in 11 of 11" means never
        # translated. One language left out is a miss for that language.
        if len(same) == len(langs) and len(langs) > 1:
            failures.append(
                f"{key!r} is verbatim English in all {len(langs)} languages: "
                f"{value[:50]!r}")
        elif len(same) >= max(2, len(langs) - 1) and len(langs) > 3:
            failures.append(
                f"{key!r} is English in {len(same)} of {len(langs)} languages "
                f"({', '.join(same[:6])}{'...' if len(same) > 6 else ''}) - "
                f"a translation was missed for those: {value[:40]!r}")

    # Placeholders must survive translation, or an alert raises at runtime.
    for key, value in sorted(en.items()):
        if not isinstance(value, str):
            continue
        for token in ("{path}", "{stage}", "{details}"):
            if token not in value:
                continue
            for lang in langs:
                other = STRINGS[lang].get(key)
                if isinstance(other, str) and token not in other:
                    failures.append(
                        f"{lang}/{key}: lost the {token} placeholder - the "
                        f"message would raise when it is shown")

    for f in failures[:25]:
        print("FAIL:", f)
    if len(failures) > 25:
        print(f"... and {len(failures) - 25} more")
    if failures:
        return 1
    print(f"OK: every user-facing string is translated in all {len(langs)} "
          f"languages (only the {len(SKIP)} brand terms are shared)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Amount in words for printed checks.

Arabic follows the commercial wording used on Egyptian checks:
"فقط مائتان وخمسون ألف جنيه مصري لا غير". English relies on num2words.
"""

from num2words import num2words

AR_ONES = [
    "", "واحد", "اثنان", "ثلاثة", "أربعة", "خمسة", "ستة", "سبعة", "ثمانية", "تسعة", "عشرة",
    "أحد عشر", "اثنا عشر", "ثلاثة عشر", "أربعة عشر", "خمسة عشر", "ستة عشر", "سبعة عشر",
    "ثمانية عشر", "تسعة عشر",
]
AR_TENS = ["", "", "عشرون", "ثلاثون", "أربعون", "خمسون", "ستون", "سبعون", "ثمانون", "تسعون"]
AR_HUNDREDS = ["", "مائة", "مائتان", "ثلاثمائة", "أربعمائة", "خمسمائة", "ستمائة", "سبعمائة", "ثمانمائة", "تسعمائة"]
# (value, one, two, three-to-ten)
AR_SCALES = [
    (10 ** 9, "مليار", "ملياران", "مليارات"),
    (10 ** 6, "مليون", "مليونان", "ملايين"),
    (10 ** 3, "ألف", "ألفان", "آلاف"),
]
AR_JOIN = " و"

CURRENCY_WORDS = {
    "EGP": {"ar": ("جنيه مصري", "قرشاً"), "en": ("Egyptian Pounds", "Piasters")},
    "USD": {"ar": ("دولار أمريكي", "سنتاً"), "en": ("US Dollars", "Cents")},
    "EUR": {"ar": ("يورو", "سنتاً"), "en": ("Euros", "Cents")},
    "SAR": {"ar": ("ريال سعودي", "هللة"), "en": ("Saudi Riyals", "Halalas")},
    "AED": {"ar": ("درهم إماراتي", "فلساً"), "en": ("UAE Dirhams", "Fils")},
}


def _ar_below_thousand(number):
    hundreds, rest = divmod(number, 100)
    parts = [AR_HUNDREDS[hundreds]] if hundreds else []
    if rest:
        if rest < 20:
            parts.append(AR_ONES[rest])
        else:
            tens, ones = divmod(rest, 10)
            parts.append(f"{AR_ONES[ones]}{AR_JOIN}{AR_TENS[tens]}" if ones else AR_TENS[tens])
    return AR_JOIN.join(parts)


def _ar_scale_words(count, one, two, few):
    if count == 1:
        return one
    if count == 2:
        return two
    if count <= 10:
        return f"{_ar_below_thousand(count)} {few}"
    words = _ar_below_thousand(count)
    if words.endswith("مائتان"):
        words = words[:-1]  # مائتا ألف
    return f"{words} {one}"


def number_to_arabic_words(number):
    number = int(number)
    if number == 0:
        return "صفر"
    parts = []
    for value, one, two, few in AR_SCALES:
        count, number = divmod(number, value)
        if count:
            parts.append(_ar_scale_words(count, one, two, few))
    if number:
        parts.append(_ar_below_thousand(number))
    return AR_JOIN.join(parts)


def _split(amount, decimals=2):
    total = round(amount * 10 ** decimals)
    return divmod(int(total), 10 ** decimals)


def _labels(currency, language):
    words = CURRENCY_WORDS.get(currency.name)
    if words:
        return words[language]
    return (currency.currency_unit_label or currency.name, currency.currency_subunit_label or "")


def amount_to_arabic(amount, currency, frame=True):
    units, cents = _split(amount, currency.decimal_places)
    unit_label, subunit_label = _labels(currency, "ar")
    text = f"{number_to_arabic_words(units)} {unit_label}"
    if cents:
        text += f"{AR_JOIN}{number_to_arabic_words(cents)} {subunit_label}".rstrip()
    return f"فقط {text} لا غير" if frame else text


def amount_to_english(amount, currency, frame=True):
    units, cents = _split(amount, currency.decimal_places)
    unit_label, subunit_label = _labels(currency, "en")
    text = f"{num2words(units, lang='en').replace(',', '').title()} {unit_label}"
    if cents:
        text += f" and {num2words(cents, lang='en').title()} {subunit_label}".rstrip()
    return f"{text} Only" if frame else text

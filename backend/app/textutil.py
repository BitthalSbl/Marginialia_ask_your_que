"""Tokenising helpers shared by keyword search and the offline answer writer."""
import re

_WORD = re.compile(r"\w+", re.UNICODE)
_SENTENCE = re.compile(r"(?<=[.!?।])\s+|\n+")

STOPWORDS = frozenset(
    """a an the and or but if of to in on at by for with from into as is are was were be been being am
    do does did done have has had it its this that these those there here what which who whom whose when
    where why how can could should would will shall may might must not no yes than then so such also very
    about over under between after before during i you he she we they me my your our their him her them
    kya hai hain tha thi the ka ki ke ko se mein me par pe aur ya yeh ye woh wo is us un koi kaun kab kahan
    kyun kaise kitna kitni kitne hota hoti hote hua hui hue kar karo kare karna batao bataiye btao
    din milta milti milega milegi jata jati jaata jayega tak liye lie jaise sakta sakte sakti chahiye chahie wala wali wale
    please tell give show explain""".split()
)

SUMMARY_WORDS = frozenset(
    "summary summarise summarize summarising summarizing overview gist outline tldr saransh sar abstract".split()
)


def _stem(word: str) -> str:
    if len(word) > 5 and word.endswith("ing"):
        return word[:-3]
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith("ed"):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def tokenize(text: str, drop_stopwords: bool = True) -> list[str]:
    out = []
    for w in _WORD.findall(text.lower()):
        if len(w) < 2 and not w.isdigit():
            continue
        if drop_stopwords and w in STOPWORDS:
            continue
        out.append(_stem(w))
    return out


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE.split(text) if s and len(s.strip()) >= 25]


def is_summary_request(question: str) -> bool:
    return any(w in SUMMARY_WORDS for w in _WORD.findall(question.lower()))

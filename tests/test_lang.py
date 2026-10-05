from types import SimpleNamespace as Info

from app.lang import pick_language


def test_arabic_and_english_are_kept():
    assert pick_language(Info(language="ar")) == "ar"
    assert pick_language(Info(language="en")) == "en"


def test_other_guesses_fall_back_to_the_likelier_of_arabic_or_english():
    assert pick_language(Info(language="fa", all_language_probs=[("fa", .5), ("ar", .3), ("en", .1)])) == "ar"
    assert pick_language(Info(language="de", all_language_probs=[("de", .5), ("en", .4), ("ar", .01)])) == "en"
    assert pick_language(Info(language="ur")) == "ar"       # no probabilities: Arabic is the safer guess

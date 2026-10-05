from app.tts import MAX_SPEECH_CHARS, clean_for_speech, pick_voice


def test_arabic_text_gets_the_egyptian_voice_and_english_gets_english():
    assert pick_voice("تمام انا جاية دلوقتي") == "ar-EG-SalmaNeural"
    assert pick_voice("on my way") == "en-US-AriaNeural"
    assert pick_voice("تمام ok") == "ar-EG-SalmaNeural"       # mostly Arabic letters


def test_voice_can_be_overridden(monkeypatch):
    monkeypatch.setenv("DASHBOARD_VOICE_AR", "ar-EG-ShakirNeural")
    assert pick_voice("اهلا") == "ar-EG-ShakirNeural"


def test_emoji_and_markdown_are_not_read_out():
    assert clean_for_speech("**تمام** 😂😂 ماشي") == "تمام ماشي"
    assert clean_for_speech("  # hi `there`  ") == "hi there"


def test_long_replies_are_cut_at_a_word_boundary():
    out = clean_for_speech("كلمة " * 400)
    assert 0 < len(out) <= MAX_SPEECH_CHARS and out.endswith("كلمة")


def test_tatweel_is_removed():
    assert clean_for_speech("جاري الارسال لـMom") == "جاري الارسال لMom"


def test_provider_defaults_to_the_free_voice(monkeypatch):
    from app.tts import provider
    monkeypatch.delenv("TTS_PROVIDER", raising=False)
    assert provider() == "edge"
    monkeypatch.setenv("TTS_PROVIDER", " OpenAI ")
    assert provider() == "openai"

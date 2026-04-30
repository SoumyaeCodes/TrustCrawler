from src.utils.language import detect_language


def test_detects_english():
    text = (
        "The quick brown fox jumps over the lazy dog. "
        "Pack my box with five dozen liquor jugs. "
        "How vexingly quick daft zebras jump."
    )
    assert detect_language(text) == "en"


def test_detects_spanish():
    text = (
        "Este es un texto largo escrito en idioma español "
        "para que la detección automática del lenguaje funcione "
        "correctamente. La biblioteca langdetect debería identificar "
        "el idioma sin mayores dificultades en una frase como esta."
    )
    assert detect_language(text) == "es"


def test_short_text_returns_fallback():
    assert detect_language("hi") == "en"
    assert detect_language("hi", fallback="xx") == "xx"


def test_empty_text_returns_fallback():
    assert detect_language("") == "en"
    assert detect_language("", fallback="zz") == "zz"


def test_garbled_text_returns_fallback():
    # Below MIN_TEXT_LEN, so we go through the short-text branch.
    assert detect_language("$$$$$$") == "en"

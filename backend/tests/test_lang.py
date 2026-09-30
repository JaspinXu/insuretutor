from app.lang import chinese_variant, convert_script, detect_language


def test_detects_english_even_with_quoted_chinese_term():
    assert detect_language("What does 保證可保權益 mean?") == "en"


def test_detects_traditional_and_simplified():
    assert detect_language("保證可保權益最多可以行使幾次？") == "zh-Hant"
    assert detect_language("保证可保权益最多可以行使几次？") == "zh-Hans"


def test_chinese_with_product_name_is_chinese():
    assert detect_language("FLEXI-ULife的最低保障額是多少") == "zh-Hant"


def test_script_neutral_chinese_uses_ui_fallback():
    # "保費" vs "保费": use a phrase whose characters are identical in both scripts
    assert chinese_variant("可以提取多少") is None
    assert detect_language("可以提取多少", fallback="zh-Hant") == "zh-Hant"
    assert detect_language("可以提取多少", fallback="en") == "zh-Hans"


def test_empty_or_symbols_use_fallback():
    assert detect_language("??? 123", fallback="zh-Hant") == "zh-Hant"


def test_convert_script_matches_brochure_glyphs():
    assert convert_script("账户价值", "zh-Hant") == "賬戶價值"
    assert convert_script("賬戶價值", "zh-Hans") == "账户价值"
    assert convert_script("Account Value", "zh-Hans") == "Account Value"

from src.trust_score.components import medical_disclaimer as md


def test_non_medical_returns_neutral(make_raw):
    raw = make_raw()
    assert md.score(raw, {"is_medical": False}) == md.NON_MEDICAL_SCORE
    assert md.score(raw, {}) == md.NON_MEDICAL_SCORE  # missing key = non-medical


def test_medical_with_disclaimer_full_score(make_raw):
    raw = make_raw()
    body = (
        "This article is for informational purposes only. "
        "Please consult your doctor before starting any treatment."
    )
    s = md.score(raw, {"is_medical": True, "body_text": body})
    assert s == md.PRESENT_SCORE


def test_medical_without_disclaimer_penalty(make_raw):
    raw = make_raw()
    body = "Take vitamin C and you'll never get sick. Avoid all vaccines."
    s = md.score(raw, {"is_medical": True, "body_text": body})
    assert s == md.ABSENT_SCORE


def test_tier_1_sources_exempt_from_disclaimer_penalty(make_raw):
    """PubMed and tier-1 medical hosts shouldn't be penalized for missing
    a disclaimer — peer review / institutional authority is the caveat.
    """
    body = "Take vitamin C and you'll never get sick. Avoid all vaccines."
    raw_pubmed = make_raw(
        source_url="https://pubmed.ncbi.nlm.nih.gov/12345",
        source_type="pubmed",
    )
    raw_tier1_blog = make_raw(
        source_url="https://nih.gov/some-guide",
        source_type="blog",
    )
    raw_random_blog = make_raw(
        source_url="https://random-health-blog.com/x",
        source_type="blog",
    )
    assert md.score(raw_pubmed, {"is_medical": True, "body_text": body}) == md.PRESENT_SCORE
    assert md.score(raw_tier1_blog, {"is_medical": True, "body_text": body}) == md.PRESENT_SCORE
    # Non-tier-1 still gets the penalty.
    assert md.score(raw_random_blog, {"is_medical": True, "body_text": body}) == md.ABSENT_SCORE


def test_disclaimer_variants_match():
    body_variants = [
        "This is not medical advice.",
        "Consult a healthcare provider.",
        "Consult their physician for any symptoms.",
        "For informational purposes only.",
        "Seek medical attention immediately.",
    ]
    for body in body_variants:
        for pat in md.DISCLAIMER_PATTERNS:
            if pat.search(body):
                break
        else:
            raise AssertionError(f"no pattern matched: {body!r}")


def test_is_medical_topic_via_tags():
    assert md.is_medical_topic(["clinical trial"], "") is True
    assert md.is_medical_topic(["software"], "") is False


def test_is_medical_topic_via_body():
    assert md.is_medical_topic([], "Patients with diabetes should...") is True
    assert md.is_medical_topic([], "We trained the model on a GPU.") is False


def test_is_medical_topic_empty():
    assert md.is_medical_topic([], "") is False

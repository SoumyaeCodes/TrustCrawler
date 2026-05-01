from src.trust_score import abuse_prevention as ap

# ---------- domain_to_score / is_spam_host ----------

def test_tier_1_explicit_domain():
    assert ap.domain_to_score("nature.com") == ap.SCORES["tier_1"]
    assert ap.domain_to_score("nih.gov") == ap.SCORES["tier_1"]


def test_tier_1_subdomain_match():
    # Subdomains of explicit tier_1 still tier 1.
    assert ap.domain_to_score("blog.nature.com") == ap.SCORES["tier_1"]


def test_tier_1_via_suffix():
    assert ap.domain_to_score("hhs.gov") == ap.SCORES["tier_1"]
    assert ap.domain_to_score("mit.edu") == ap.SCORES["tier_1"]


def test_tier_2_explicit_domain():
    assert ap.domain_to_score("bbc.com") == ap.SCORES["tier_2"]


def test_unknown_domain_defaults_to_tier_3():
    assert ap.domain_to_score("randomblog.example") == ap.SCORES["tier_3"]


def test_spam_forces_tier_4():
    assert ap.domain_to_score("ehow.com") == ap.SCORES["tier_4"]
    assert ap.is_spam_host("ehow.com") is True
    assert ap.is_spam_host("nature.com") is False


def test_empty_or_none_host_is_tier_3():
    assert ap.domain_to_score(None) == ap.SCORES["tier_3"]
    assert ap.domain_to_score("") == ap.SCORES["tier_3"]


def test_case_insensitive_lookup():
    assert ap.domain_to_score("NATURE.COM") == ap.SCORES["tier_1"]
    assert ap.domain_to_score("EHow.com") == ap.SCORES["tier_4"]


# ---------- is_fake_author ----------

def test_fake_author_normal_name():
    assert ap.is_fake_author("Jane Doe") is False
    assert ap.is_fake_author("Albert Einstein") is False
    assert ap.is_fake_author("Dr. Jane Doe") is False  # 1 honorific OK


def test_fake_author_too_many_honorifics():
    assert ap.is_fake_author("Dr. Prof. Sir Smith MD PhD MBA EsQ") is True


def test_fake_author_only_honorifics_no_surname():
    # Honorific count >= 2 and ≤1 leftover word triggers.
    assert ap.is_fake_author("Dr. MD PhD") is True
    assert ap.is_fake_author("Prof. Smith") is False  # 1 honorific, 1 surname


def test_fake_author_known_org_passes():
    assert ap.is_fake_author("WHO Collaborating Centre on Mental Health") is False
    assert ap.is_fake_author("From WHO Collaborating Centre on Mental Health staff") is False


def test_fake_author_all_caps_gibberish():
    assert ap.is_fake_author("XQZWPLMQ") is True
    assert ap.is_fake_author("XYZ$$$ABC") is True


def test_fake_author_empty():
    assert ap.is_fake_author("") is False
    assert ap.is_fake_author("   ") is False


# ---------- has_keyword_stuffing ----------

def test_keyword_stuffing_short_body_false():
    assert ap.has_keyword_stuffing("buy buy buy") is False


def test_keyword_stuffing_normal_prose_false():
    body = (
        "The quick brown fox jumps over the lazy dog. "
        "An apple a day keeps the doctor away. "
        "Programming is the art of telling another human what one wants the computer to do. "
        "Software engineering means many things to many people, but ultimately it boils "
        "down to building things that work and continue working as the world changes."
    )
    assert ap.has_keyword_stuffing(body) is False


def test_keyword_stuffing_repeated_keyword_true():
    body = "buy crypto " * 200 + "now"
    assert ap.has_keyword_stuffing(body) is True


def test_keyword_stuffing_ignores_stopwords():
    # "the" repeated heavily but it's a stopword — shouldn't trigger.
    body = ("the " * 200) + "quick brown fox over a lazy dog " * 10
    assert ap.has_keyword_stuffing(body) is False


# ---------- DuplicateTracker ----------

def test_duplicate_tracker_first_seen_false():
    tracker = ap.DuplicateTracker()
    assert tracker.is_duplicate("hello world") is False


def test_duplicate_tracker_second_same_true():
    tracker = ap.DuplicateTracker()
    body = "hello world this is some content " * 50
    assert tracker.is_duplicate(body) is False
    assert tracker.is_duplicate(body) is True


def test_duplicate_tracker_only_hashes_first_1000():
    tracker = ap.DuplicateTracker()
    a = "x" * 1000 + " ENDING_A"
    b = "x" * 1000 + " ENDING_B"
    assert tracker.is_duplicate(a) is False
    assert tracker.is_duplicate(b) is True  # first 1000 identical


# ---------- Monkeypatch the data constants ----------

def test_monkeypatch_spam_domains(monkeypatch):
    monkeypatch.setattr(ap, "SPAM_DOMAINS", frozenset({"good.example.com"}))
    assert ap.is_spam_host("good.example.com") is True
    assert ap.is_spam_host("ehow.com") is False  # not in patched set


def test_monkeypatch_known_orgs(monkeypatch):
    # "Dr. ACME PhD" normally trips the fake-author heuristic (2 honorifics + 1 leftover).
    assert ap.is_fake_author("Dr. ACME PhD") is True
    # Adding "acme" to the known-orgs set suppresses the flag.
    monkeypatch.setattr(ap, "KNOWN_ORGS_LOWER", frozenset({"acme"}))
    assert ap.is_fake_author("Dr. ACME PhD") is False

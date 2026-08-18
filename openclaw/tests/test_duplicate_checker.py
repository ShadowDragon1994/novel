from business.duplicate_checker import DuplicateChecker


def test_duplicate_checker_flags_repeated_paragraphs():
    paragraph = "This paragraph is long enough for duplicate detection and should be recognized as repeated by the checker." * 2
    result = DuplicateChecker().check(paragraph + "\n\n" + paragraph)
    assert not result.passed
    assert result.repeated_paragraphs or result.similar_pairs


def test_duplicate_checker_accepts_varied_narrative():
    content = "\n\n".join([
        "The morning fog pressed against the street while the lead character checked the gate and logged the first clue.",
        "A new rule appeared on the elevator mirror, turning a neighbor's small lie into a dangerous route.",
        "The crowd argued over medicine, so supplies and responsibilities were separated into a public table.",
        "Viewers compared evidence through the live stream and helped the team identify the paper crane condition.",
        "At night, an empty cage dropped a button and created the next chapter's missing-person hook.",
    ])
    result = DuplicateChecker().check(content)
    assert result.passed

"""Code-availability and reproducibility scanning — pure text, no LLM."""

from __future__ import annotations

import pytest

from artifacts import assess, find_repo_links, repro_signals


# ---------------------------------------------------------------------------
# Repo links
# ---------------------------------------------------------------------------

def test_finds_a_plain_github_url():
    assert find_repo_links("Code at https://github.com/google/flax for details.") == [
        "https://github.com/google/flax"
    ]


def test_finds_a_url_without_a_scheme():
    """Papers routinely write the bare host, especially in footnotes."""
    assert find_repo_links("see github.com/openai/gym") == ["https://github.com/openai/gym"]


@pytest.mark.parametrize(
    "text",
    [
        "Code: https://github.com/a/b.",
        "Code (https://github.com/a/b)",
        "Code: https://github.com/a/b,",
        "Code: 'https://github.com/a/b';",
    ],
)
def test_trailing_sentence_punctuation_is_not_part_of_the_path(text):
    """PDF text extraction glues the sentence period onto the URL — keeping
    it produces a dead link, which is worse than no link at all."""
    assert find_repo_links(text) == ["https://github.com/a/b"]


def test_url_broken_by_a_line_break_stops_at_whitespace():
    assert find_repo_links("https://github.com/a/b\nWe also thank") == [
        "https://github.com/a/b"
    ]


def test_recognises_the_other_hosts():
    text = "gitlab.com/x/y and bitbucket.org/p/q and huggingface.co/datasets/z"
    assert find_repo_links(text) == [
        "https://gitlab.com/x/y",
        "https://bitbucket.org/p/q",
        "https://huggingface.co/datasets/z",
    ]


def test_deduplicates_case_insensitively_but_keeps_the_first_spelling():
    text = "github.com/Foo/Bar ... later github.com/foo/bar"
    assert find_repo_links(text) == ["https://github.com/Foo/Bar"]


def test_bare_host_or_non_repo_route_is_not_a_code_link():
    """A link the reader cannot clone is noise on a "does this have code" badge."""
    assert find_repo_links("visit github.com") == []
    assert find_repo_links("see github.com/about") == []


def test_no_links_in_empty_or_missing_text():
    assert find_repo_links("") == []
    assert find_repo_links(None) == []  # type: ignore[arg-type]


def test_a_promise_of_future_code_is_not_a_code_link():
    """The v1 of 'Attention Is All You Need' says exactly this and links
    nothing — reporting it as "has code" would be a lie."""
    text = "We intend to make the code we used to train our models available soon."
    assert find_repo_links(text) == []


# ---------------------------------------------------------------------------
# Reproducibility signals
# ---------------------------------------------------------------------------

def test_detects_hyperparameters():
    assert repro_signals("We use a learning rate of 3e-4 and batch size 64.")["hyperparameters"]


def test_detects_hardware():
    assert repro_signals("Trained on 8 A100 GPUs for 3 days.")["hardware"]


def test_detects_variance_reporting():
    assert repro_signals("We report 82.1 ± 0.4 over 5 runs.")["variance"]


def test_detects_seeds():
    assert repro_signals("Averaged over 5 seeds.")["seeds"]
    assert repro_signals("We fix the random seed.")["seeds"]


def test_the_word_seeded_alone_is_not_a_seed_signal():
    """"Seed" appears in plenty of unrelated ML sentences; matching it bare
    would mark almost every paper as reporting seeds."""
    assert not repro_signals("We seeded the retrieval corpus with documents.")["seeds"]


def test_signals_are_all_false_for_empty_text():
    assert not any(repro_signals("").values())


# ---------------------------------------------------------------------------
# assess
# ---------------------------------------------------------------------------

def test_assess_reports_whether_it_saw_the_full_text():
    """An abstract-only scan finding nothing means very little; a full-text
    scan finding nothing is informative. The UI has to tell them apart."""
    abstract_only = assess("A short abstract.", scanned_full_text=False)
    assert abstract_only["scanned_full_text"] is False
    assert abstract_only["has_code"] is False

    full = assess("Code at github.com/a/b, lr 1e-4, 8 GPUs.", scanned_full_text=True)
    assert full["scanned_full_text"] is True
    assert full["has_code"] is True


def test_assess_counts_signals_against_a_stable_total():
    result = assess("Trained on GPUs with a learning rate of 0.1.", scanned_full_text=True)
    assert result["signal_count"] == 2
    assert result["signal_total"] == len(result["signals"])

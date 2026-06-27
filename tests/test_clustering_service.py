"""Tests for event clustering service."""

import pytest

from app.services.clustering_service import (
    _find_best_cluster_overlap,
    _fingerprint,
)


class TestFingerprint:
    def test_stable_for_same_input(self):
        assert _fingerprint("Hello World") == _fingerprint("Hello World")

    def test_case_insensitive(self):
        assert _fingerprint("Hello World") == _fingerprint("hello world")

    def test_strips_whitespace(self):
        assert _fingerprint("  Hello World  ") == _fingerprint("Hello World")

    def test_different_inputs_differ(self):
        assert _fingerprint("Article A") != _fingerprint("Article B")

    def test_returns_16_char_hex(self):
        fp = _fingerprint("test")
        assert len(fp) == 16
        assert all(c in "0123456789abcdef" for c in fp)


class TestJaccardOverlap:
    def test_exact_match_returns_high_score(self):
        titles = {1: "Google releases new AI model"}
        best_id, score = _find_best_cluster_overlap("Google releases new AI model", titles)
        assert best_id == 1
        assert score == pytest.approx(1.0)

    def test_partial_overlap(self):
        titles = {
            1: "Google releases new AI model",
            2: "Apple launches iPhone 16",
        }
        best_id, score = _find_best_cluster_overlap("Google announces new AI update", titles)
        assert best_id == 1
        assert score > 0.2

    def test_no_overlap_returns_zero(self):
        titles = {1: "Apple launches iPhone"}
        best_id, score = _find_best_cluster_overlap("Quantum computing breakthrough", titles)
        assert score < 0.15

    def test_empty_titles_returns_none(self):
        best_id, score = _find_best_cluster_overlap("anything", {})
        assert best_id is None
        assert score == 0.0

    def test_empty_query_returns_none(self):
        best_id, score = _find_best_cluster_overlap("", {1: "test"})
        assert best_id is None
        assert score == 0.0

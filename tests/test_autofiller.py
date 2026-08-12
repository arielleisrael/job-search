import sys
import os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "autofiller"))

import pytest
from unittest.mock import patch, MagicMock
import autofiller
from autofiller import pick_resume, pick_cover_note, RESUME_DEFAULT, RESUME_VARIANTS, RESUME_BASE, PROFILE


@pytest.fixture(autouse=True)
def reset_resume_forced():
    autofiller._RESUME_FORCED = None
    yield
    autofiller._RESUME_FORCED = None


def test_pick_resume_manager():
    result = pick_resume("Senior QE Manager")
    assert result.endswith("Resume-QE-Manager-ArielleIsrael.pdf")


def test_pick_resume_director():
    result = pick_resume("Director of Quality Engineering")
    assert result.endswith("Resume-QE-Manager-ArielleIsrael.pdf")


def test_pick_resume_lead():
    result = pick_resume("Lead SDET")
    assert result.endswith("Resume-Lead-SDET-ArielleIsrael.pdf")


def test_pick_resume_staff():
    result = pick_resume("Staff Quality Engineer")
    assert result.endswith("Resume-Lead-SDET-ArielleIsrael.pdf")


def test_pick_resume_principal():
    result = pick_resume("Principal Software Engineer in Test")
    assert result.endswith("Resume-Lead-SDET-ArielleIsrael.pdf")


def test_pick_resume_default():
    result = pick_resume("Senior Quality Engineer")
    assert result.endswith("Resume-Senior-Quality-Engineer-ArielleIsrael.pdf")


def test_pick_resume_case_insensitive():
    result = pick_resume("MANAGER quality engineering")
    assert result.endswith("Resume-QE-Manager-ArielleIsrael.pdf")


def test_pick_resume_forced_overrides_keyword():
    forced_path = str(autofiller.RESUME_BASE / "Resume-QE-Manager-ArielleIsrael.pdf")
    autofiller._RESUME_FORCED = forced_path
    # title would normally match IC track (default)
    result = pick_resume("Senior Quality Engineer")
    assert result == forced_path


def test_pick_cover_note_returns_api_text():
    mock_page = MagicMock()
    mock_page.inner_text.return_value = "We are building great software and need a QE Lead."
    job = {"title": "QE Lead", "company": "Acme Corp"}

    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text="  First sentence. Second sentence. Third sentence.  ")]

    with patch("autofiller._anthropic") as mock_anthropic:
        mock_client = MagicMock()
        mock_anthropic.Anthropic.return_value = mock_client
        mock_client.messages.create.return_value = mock_msg

        result = pick_cover_note(mock_page, job)

    assert result == "First sentence. Second sentence. Third sentence."
    call_kwargs = mock_client.messages.create.call_args
    assert call_kwargs.kwargs["model"] == "claude-haiku-4-5-20251001"


def test_pick_cover_note_falls_back_on_api_exception():
    mock_page = MagicMock()
    mock_page.inner_text.return_value = "Job description text"
    job = {"title": "QE Lead", "company": "Acme Corp"}

    with patch("autofiller._anthropic") as mock_anthropic:
        mock_anthropic.Anthropic.side_effect = Exception("network error")
        result = pick_cover_note(mock_page, job)

    assert result == PROFILE["cover_note"]


def test_pick_cover_note_falls_back_when_anthropic_none():
    mock_page = MagicMock()
    job = {"title": "QE Lead", "company": "Acme Corp"}

    with patch("autofiller._anthropic", None):
        result = pick_cover_note(mock_page, job)

    assert result == PROFILE["cover_note"]


def test_scroll_and_fill_all_does_not_mutate_profile():
    """PROFILE["cover_note"] and ["resume_path"] must never be mutated."""
    original_note = PROFILE["cover_note"]
    original_resume = PROFILE["resume_path"]
    # Even after scroll_and_fill_all runs with _JOB_INFO overrides,
    # PROFILE values must be unchanged.
    assert PROFILE["cover_note"] == original_note
    assert PROFILE["resume_path"] == original_resume

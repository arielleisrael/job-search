import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "autofiller"))

import pytest
import autofiller
from autofiller import pick_resume, RESUME_DEFAULT, RESUME_VARIANTS, RESUME_BASE


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

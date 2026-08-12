import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "autofiller"))

from autofiller import pick_resume, RESUME_DEFAULT, RESUME_VARIANTS, RESUME_BASE


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

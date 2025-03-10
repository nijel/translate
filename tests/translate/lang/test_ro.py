import string

from translate.lang.ro import RomanianChecker

from ..filters.test_checks import fails, passes


def test_cedillas():
    """Test that we can detect cedillas."""
    ro_checker = RomanianChecker()
    assert passes(ro_checker.cedillas, "", "")
    assert fails(ro_checker.cedillas, "", "blaŢbla")
    assert fails(ro_checker.cedillas, "", "blaŞbla")
    assert fails(ro_checker.cedillas, "", "blaţbla")
    assert fails(ro_checker.cedillas, "", "blaşbla")
    assert fails(ro_checker.cedillas, "", "blaŢblaŞblaţblaşbla']")
    assert passes(ro_checker.cedillas, "", "blașțăâîbla")
    assert passes(ro_checker.cedillas, "", "blaȘȚĂÂÎbla")
    assert passes(ro_checker.cedillas, "", string.ascii_lowercase)
    assert passes(ro_checker.cedillas, "", string.ascii_uppercase)


def test_niciun():
    """Test that we can detect niciun/nicio."""
    ro_checker = RomanianChecker()
    assert passes(ro_checker.niciun_nicio, "", "")
    assert fails(ro_checker.niciun_nicio, "", "nici un")
    assert fails(ro_checker.niciun_nicio, "", "nici o")
    assert fails(ro_checker.niciun_nicio, "", "bla nici un bla")
    assert fails(ro_checker.niciun_nicio, "", "bla nici o bla")
    assert passes(ro_checker.niciun_nicio, "", "niciun")
    assert passes(ro_checker.niciun_nicio, "", "nicio")
    assert passes(ro_checker.niciun_nicio, "", "bla niciun bla")
    assert passes(ro_checker.niciun_nicio, "", "bla nicio bla")
    assert passes(ro_checker.niciun_nicio, "", "blașțăâîbla")
    assert passes(ro_checker.niciun_nicio, "", "blaȘȚĂÂÎbla")
    assert passes(ro_checker.niciun_nicio, "", string.ascii_lowercase)
    assert passes(ro_checker.niciun_nicio, "", string.ascii_uppercase)

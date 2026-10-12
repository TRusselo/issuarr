"""The wait between GetComics search pages is a setting, kept between 3 and 60 seconds."""
import types

import pytest

import mylar
from mylar import webserve


@pytest.fixture(autouse=True)
def cfg(monkeypatch):
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(DDL_QUERY_DELAY=15), raising=False)


@pytest.mark.unit
@pytest.mark.parametrize('value, want', [('8', 8), (' 5 ', 5), ('1', 3), ('0', 3), ('600', 60), ('60', 60), ('', 15), ('abc', 15), (None, 15), ('7.5', 15)])
def test_query_delay_is_whole_seconds_between_3_and_60(value, want):
    assert webserve.query_delay(value) == want

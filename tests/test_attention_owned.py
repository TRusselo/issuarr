import os

import pytest

import mylar
from mylar import attention, db


@pytest.fixture
def myDB(monkeypatch, tmp_path):
    monkeypatch.setattr(mylar, 'DATA_DIR', str(tmp_path), raising=False)
    monkeypatch.setattr(attention, '_COUNT', [0.0, 0])
    d = db.DBConnection()
    d.action('CREATE TABLE comics (ComicID TEXT, ComicName TEXT, ComicYear TEXT)')
    d.action('CREATE TABLE issues (IssueID TEXT, ComicID TEXT, Issue_Number TEXT)')
    d.action("INSERT INTO comics VALUES ('33350', 'Secret Avengers', '2010')")
    d.action("INSERT INTO issues VALUES ('9001', '33350', '1')")
    return d


@pytest.mark.unit
def test_owned_wins_over_couldnt_tell_which_series():
    assert attention.pick({'series', 'owned'}) == 'owned'
    assert attention.pick({'damaged', 'owned'}) == 'damaged'


@pytest.mark.unit
def test_a_copy_the_duplicate_check_left_behind_says_it_is_already_owned(myDB, tmp_path):
    from mylar import PostProcessor
    path = tmp_path / 'Secret Avengers 001 (2010).cbr'
    path.write_bytes(b'x')
    pp = PostProcessor.PostProcessor.__new__(PostProcessor.PostProcessor)
    pp._att_owned({'action': 'dupe_file'}, str(path), '33350', '9001')
    row = myDB.selectone('SELECT reason, detail, comicid FROM attention WHERE path=?', [str(path)]).fetchone()
    assert (row['reason'], row['comicid']) == ('owned', '33350')
    assert row['detail'] == 'Secret Avengers (2010) #1 is already in your library, and that copy was kept.'


@pytest.mark.unit
@pytest.mark.parametrize('action', ['write', 'dupe_src'])
def test_other_duplicate_outcomes_note_nothing(myDB, tmp_path, action):
    from mylar import PostProcessor
    path = tmp_path / 'x.cbr'
    path.write_bytes(b'x')
    PostProcessor.PostProcessor.__new__(PostProcessor.PostProcessor)._att_owned({'action': action}, str(path), '33350', '9001')
    attention.ensure(myDB)
    assert myDB.selectone('SELECT path FROM attention').fetchone() is None


@pytest.mark.unit
def test_needs_attention_has_an_already_have_tab():
    page = open('data/interfaces/default/attention.html').read()
    assert "owned: ['owned', 'You already have this issue.']" in page
    assert "['owned', 'Already have']" in page

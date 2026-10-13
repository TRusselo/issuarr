import os
import types

import pytest

import mylar
from mylar import archives, attention, db


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(mylar, 'DATA_DIR', str(tmp_path), raising=False)
    review = tmp_path / 'mylar-review'
    review.mkdir()
    ddl = tmp_path / 'mylar-dl'
    ddl.mkdir()
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(DDL_LOCATION=str(ddl) + '/', ARCHIVE_REVIEW_DIR=str(review),
                                                               ATTENTION_TRASH_DAYS=14), raising=False)
    monkeypatch.setattr(archives, 'review_dir', lambda: str(review))
    monkeypatch.setattr(archives, 'PENDING', [])
    from mylar import autoadd
    monkeypatch.setattr(autoadd, 'enabled', lambda: False)
    monkeypatch.setattr(attention, '_COUNT', [0.0, 0])
    return types.SimpleNamespace(root=tmp_path, ddl=ddl, trash=tmp_path / 'mylar-trash')


def put(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, 'wb').close()
    return str(path)


@pytest.mark.unit
def test_a_filed_packs_leftovers_go_to_the_trash_not_needs_attention(env):
    pack = env.ddl / 'Secret Avengers Vol.1 (001 - 037) (2010-2013) [__425938__]'
    a = put(pack / 'inner' / 'Secret Avengers 001 (2010).cbr')
    b = put(pack / 'Secret Avengers 002 (2010).cbr')
    attention.record(a, 'series')
    assert archives.clear_pack(str(pack / 'inner')) == 2
    assert not pack.exists()                                  # emptied folders go too
    assert len(list(env.trash.rglob('*.cbr'))) == 2
    assert db.DBConnection().selectone('SELECT path FROM attention WHERE path=?', [a]).fetchone() is None


@pytest.mark.unit
def test_files_auto_add_may_still_file_stay(env, monkeypatch):
    pack = env.ddl / 'Some Pack'
    keep = put(pack / 'New Series 001 (2024).cbz')
    monkeypatch.setattr(archives, 'PENDING', [keep])
    assert archives.clear_pack(str(pack)) == 0
    assert os.path.exists(keep)


@pytest.mark.unit
def test_only_a_downloads_own_folder_under_the_direct_download_folder_is_cleared(env):
    single = put(env.ddl / 'Batman 001 (2020).cbz')            # a single-issue download sits in the root
    elsewhere = put(env.root / 'library' / 'X' / 'X 001.cbz')
    assert archives.clear_pack(single) == 0 and os.path.exists(single)
    assert archives.clear_pack(str(env.ddl)) == 0 and os.path.exists(single)
    assert archives.clear_pack(os.path.dirname(elsewhere)) == 0 and os.path.exists(elsewhere)


@pytest.mark.unit
@pytest.mark.parametrize('ddl, pack, issueid, unpacked, cleared', [
    (True, True, '5', False, True),       # a pack grabbed for one issue
    (True, None, None, False, True),      # a pack filed against its series
    (True, False, '5', True, True),       # a single download that unpacked into a pack
    (True, False, '5', False, False),     # a single issue: unmatched, it belongs in Needs attention
    (False, True, None, False, False),    # torrents keep seeding
])
def test_only_direct_download_packs_are_cleared(monkeypatch, ddl, pack, issueid, unpacked, cleared):
    from mylar import PostProcessor
    seen = []
    monkeypatch.setattr(PostProcessor.archives, 'clear_pack', seen.append)
    pp = PostProcessor.PostProcessor.__new__(PostProcessor.PostProcessor)
    pp.ddl, pp.pack, pp.issueid, pp.nzb_folder = ddl, pack, issueid, '/dl/x'
    if unpacked:
        pp._unpacked_pack = True
    pp._clear_pack()
    assert (seen == ['/dl/x']) is cleared

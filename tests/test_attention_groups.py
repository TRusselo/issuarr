import os
import types

import pytest

import mylar
from mylar import attention, autoadd, db


@pytest.fixture
def env(monkeypatch, tmp_path):
    review = tmp_path / 'mylar-review'
    review.mkdir()
    ddl = tmp_path / 'mylar-dl'
    ddl.mkdir()
    monkeypatch.setattr(mylar, 'DATA_DIR', str(tmp_path), raising=False)
    monkeypatch.setattr(mylar, 'CONFIG', mylar.config.Config('./nothing'), raising=False)
    for k, v in dict(ARCHIVE_REVIEW_DIR=str(review), DDL_LOCATION=str(ddl) + '/', ATTENTION_TRASH_DAYS=14, COMICVINE_API='key',
                     ARCHIVE_AUTO_ADD=False, CHECK_FOLDER=None).items():
        monkeypatch.setattr(mylar.CONFIG, k, v, raising=False)
    for name in ('fdebug', 'info', 'warn'):
        monkeypatch.setattr(attention.logger, name, lambda *a, **k: None)
    monkeypatch.setattr(attention, '_COUNT', [0.0, 0])
    return types.SimpleNamespace(root=tmp_path, review=review, ddl=ddl)


def put(path, size=1):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(b'x' * size)
    return str(path)


@pytest.mark.unit
def test_files_group_by_collection_download_or_folder(env):
    assert attention.group_of(str(env.review / 'Star Wars' / 'KOTOR' / 'a.cbz'))[:2] == (str(env.review / 'Star Wars'), 'Star Wars')
    assert attention.group_of(str(env.review / 'loose.cbz'))[1] == 'Review folder (loose files)'
    assert attention.group_of(str(env.ddl / 'Thunderbolts v1 (001-174)' / 'x' / 'b.cbr'))[1] == 'Thunderbolts v1 (001-174)'
    assert attention.group_of('/somewhere/else/c.cbz') == ('/somewhere/else', 'else', '/somewhere/else')


@pytest.mark.unit
def test_groups_count_files_and_reasons_biggest_first(env):
    for n in range(3):
        put(env.review / 'Star Wars' / ('Star Wars %03d.cbz' % n), size=10)
    p = put(env.ddl / 'Secret Avengers Vol.1' / 'Secret Avengers 001 (2010).cbr')
    attention.record(p, 'owned')
    gs = attention.groups()
    assert [(g['label'], g['count']) for g in gs] == [('Star Wars', 3), ('Secret Avengers Vol.1', 1)]
    assert gs[0]['reasons'] == {'unclaimed': 3} and gs[0]['size'] == 30
    assert gs[1]['reasons'] == {'owned': 1}


@pytest.mark.unit
def test_trash_all_and_ignore_all_act_on_one_group_only(env):
    sw = [put(env.review / 'Star Wars' / ('Star Wars %03d.cbz' % n)) for n in range(3)]
    other = put(env.review / 'Terminator' / 'Terminator 001.cbz')
    out = attention.group_action(str(env.review / 'Star Wars'), 'trash')
    assert out == {'ok': True, 'note': 'Moved 3 files to the trash.'}
    assert not any(os.path.exists(p) for p in sw) and os.path.exists(other)
    assert len(list((env.root / 'mylar-trash').rglob('*.cbz'))) == 3
    out = attention.group_action(str(env.review / 'Terminator'), 'ignore')
    assert out['ok'] is True and attention.groups() == []
    assert attention.group_action(str(env.review / 'Terminator'), 'trash')['ok'] is False   # nothing left waiting


@pytest.mark.unit
def test_add_their_series_runs_auto_add_for_the_group_even_when_it_is_off(env, monkeypatch):
    paths = [put(env.review / 'Star Wars' / ('Star Wars %03d.cbz' % n)) for n in range(2)]
    started = []
    monkeypatch.setattr(autoadd.threading, 'Thread', lambda target, args, **k: types.SimpleNamespace(start=lambda: started.append(args)))
    out = attention.group_action(str(env.review / 'Star Wars'), 'add')
    assert out['ok'] is True
    [(files, folder)] = started
    assert sorted(files) == sorted(paths) and folder == str(env.review / 'Star Wars')
    monkeypatch.setattr(mylar.CONFIG, 'COMICVINE_API', None, raising=False)
    assert attention.group_action(str(env.review / 'Star Wars'), 'add') == {'ok': False, 'note': 'Adding series needs a ComicVine API key (Settings).'}


@pytest.mark.unit
def test_auto_add_on_its_own_still_needs_switching_on(env, monkeypatch):
    started = []
    monkeypatch.setattr(autoadd.threading, 'Thread', lambda target, args, **k: types.SimpleNamespace(start=lambda: started.append(args)))
    assert autoadd.queue(['/x.cbz']) == 'Auto-add is off.'
    assert started == []

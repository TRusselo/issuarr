import json
import types

import cherrypy
import pytest

import mylar
from mylar import api, logger

API_KEY = 'a' * 32
SSE_KEY = 'b' * 32


@pytest.fixture(autouse=True)
def api_env(monkeypatch, tmp_path):
    monkeypatch.setattr(mylar, 'DATA_DIR', str(tmp_path), raising=False)
    monkeypatch.setattr(mylar, 'SSE_KEY', SSE_KEY, raising=False)
    monkeypatch.setattr(mylar, 'CONFIG', types.SimpleNamespace(
        API_ENABLED=True, API_KEY=API_KEY, ANNUALS_ON=False, CACHE_DIR=str(tmp_path)), raising=False)
    for name in ('fdebug', 'info', 'warn', 'error'):
        monkeypatch.setattr(logger, name, lambda *a, **k: None)
    monkeypatch.setattr(cherrypy.request, 'headers', {}, raising=False)

    from mylar import db
    myDB = db.DBConnection()
    myDB.action('CREATE TABLE comics (ComicID TEXT, ComicName TEXT, ComicSortName TEXT, ComicImageURL TEXT, Status TEXT, '
                'ComicPublisher TEXT, ComicPublished TEXT, ComicYear TEXT, LatestIssue TEXT, Total INTEGER, '
                'DetailURL TEXT, AlternateSearch TEXT, ComicLocation TEXT, Type TEXT, Corrected_Type TEXT)')
    myDB.action('CREATE TABLE issues (IssueID TEXT, ComicID TEXT, IssueName TEXT, ImageURL TEXT, Issue_Number TEXT, '
                'Int_IssueNumber INTEGER, ReleaseDate TEXT, IssueDate TEXT, Status TEXT, ComicName TEXT, Location TEXT)')
    myDB.action('CREATE TABLE upcoming (ComicID TEXT)')
    for cid, name in (('1001', 'Alpha'), ('1002', 'Beta')):
        myDB.action("INSERT INTO comics (ComicID, ComicName, ComicSortName, Status, ComicYear, Type) VALUES (?, ?, ?, 'Active', '2020', 'Print')",
                    [cid, name, name])
        myDB.action("INSERT INTO issues (IssueID, ComicID, Issue_Number, Int_IssueNumber, Status, ComicName) VALUES (?, ?, '1', 1000, 'Wanted', ?)",
                    [cid + '1', cid, name])
    yield


def call(**kwargs):
    a = api.Api()
    a.checkParams(**kwargs)
    return a.fetchData()


@pytest.mark.unit
def test_api_key_in_query_still_works():
    out = json.loads(call(cmd='getIndex', apikey=API_KEY))
    assert out['success'] is True
    assert [c['name'] for c in out['data']] == ['Alpha', 'Beta']


@pytest.mark.unit
def test_api_key_in_header(monkeypatch):
    monkeypatch.setattr(cherrypy.request, 'headers', {'X-Api-Key': API_KEY}, raising=False)
    assert json.loads(call(cmd='getIndex'))['success'] is True


@pytest.mark.unit
@pytest.mark.parametrize('key,message', [
    (None, 'Missing API key'),
    ('c' * 32, 'Incorrect API key'),
])
def test_bad_keys_rejected(key, message):
    kwargs = {'cmd': 'getIndex'}
    if key:
        kwargs['apikey'] = key
    out = json.loads(call(**kwargs))
    assert out['success'] is False and out['error']['message'] == message


@pytest.mark.unit
def test_api_disabled(monkeypatch):
    monkeypatch.setattr(mylar.CONFIG, 'API_ENABLED', False)
    assert json.loads(call(cmd='getIndex', apikey=API_KEY))['error']['message'] == 'API not enabled'


@pytest.mark.unit
@pytest.mark.parametrize('cmd', ['shutdown', 'delComic', 'getIndex'])
def test_sse_key_only_reads_messages(cmd, monkeypatch):
    monkeypatch.setattr(mylar.CONFIG, 'API_ENABLED', False)
    called = []
    monkeypatch.setattr(api.Api, '_' + cmd, lambda self, **k: called.append(cmd))
    out = json.loads(call(cmd=cmd, apikey=SSE_KEY, id='1001'))
    assert out['success'] is False and 'checkGlobalMessages' in out['error']['message']
    assert called == []


@pytest.mark.unit
def test_sse_key_reads_messages_with_api_disabled(monkeypatch):
    monkeypatch.setattr(mylar.CONFIG, 'API_ENABLED', False)
    monkeypatch.setattr(mylar, 'GLOBAL_MESSAGES', None, raising=False)
    assert call(cmd='checkGlobalMessages', apikey=SSE_KEY) == '\ndata: \n\n'


@pytest.mark.unit
@pytest.mark.parametrize('cmd', ['getComicInfo', 'getComic'])
def test_ids_are_not_sql(cmd):
    out = json.loads(call(cmd=cmd, apikey=API_KEY, id="1001' OR '1'='1"))
    if cmd == 'getComicInfo':
        assert out['success'] is False
    else:
        assert out['data']['comic'] == [] and out['data']['issues'] == []
    out = json.loads(call(cmd='getComicInfo', apikey=API_KEY, id='1 OR 1=1'))
    assert out['success'] is False


@pytest.mark.unit
def test_get_comic_info_by_id():
    out = json.loads(call(cmd='getComicInfo', apikey=API_KEY, id='1002'))
    assert out['success'] is True and out['data'][0]['name'] == 'Beta'


@pytest.mark.unit
def test_del_comic_does_not_run_injected_sql():
    out = json.loads(call(cmd='delComic', apikey=API_KEY, id="x' OR '1'='1"))
    assert out['success'] is False
    assert len(json.loads(call(cmd='getIndex', apikey=API_KEY))['data']) == 2


@pytest.mark.unit
def test_unknown_and_unimplemented_commands():
    for cmd in ('nope', 'addIssue'):
        out = json.loads(call(cmd=cmd, apikey=API_KEY))
        assert out['success'] is False and out['error']['message'] == 'Unknown command: %s' % cmd


@pytest.mark.unit
def test_bad_parameters_return_an_error():
    out = json.loads(call(cmd='downloadIssue', apikey=API_KEY, issueid='1'))
    assert out['success'] is False
    out = json.loads(call(cmd='findComic', apikey=API_KEY))
    assert out['success'] is False and out['error']['message'] == 'Missing a Comic name'


@pytest.mark.unit
def test_change_status_needs_both_fields():
    out = json.loads(call(cmd='changeStatus', apikey=API_KEY, id='1001', status_to='Skipped'))
    assert out['success'] is False and 'status_from' in out['error']['message']


@pytest.mark.unit
def test_command_exception_becomes_json_error(monkeypatch):
    def boom(self, **kwargs):
        raise RuntimeError('kaboom')
    monkeypatch.setattr(api.Api, '_getIndex', boom)
    out = json.loads(call(cmd='getIndex', apikey=API_KEY))
    assert out['success'] is False and 'kaboom' in out['error']['message']


@pytest.mark.unit
def test_download_nzb_rejects_paths():
    out = json.loads(call(cmd='downloadNZB', apikey=API_KEY, nzbname='../mylar.db'))
    assert out['success'] is False


@pytest.mark.unit
def test_jsonp_callback_must_be_a_name():
    assert call(cmd='getComicInfo', apikey=API_KEY, id='1001', callback='cb').startswith('cb(')
    out = json.loads(call(cmd='getIndex', apikey=API_KEY, callback='alert(1)//'))
    assert out['success'] is False


@pytest.mark.unit
def test_rest_key_check(monkeypatch):
    v = api.REST.verify_api()
    assert v.validate() is not True
    monkeypatch.setattr(cherrypy.request, 'headers', {'Api-Key': API_KEY}, raising=False)
    assert v.validate() is True


@pytest.mark.unit
def test_command_in_path():
    a = api.Api()
    a.checkParams('getIndex', apikey=API_KEY)
    assert json.loads(a.fetchData())['success'] is True

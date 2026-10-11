import pytest

from mylar import db

MOUNTS = """/dev/nvme0n1p1 / ext4 rw 0 0
/dev/sdb1 /mnt/cache btrfs rw 0 0
shfs /mnt/user fuse.shfs rw 0 0
//nas/appdata /mnt/nas/appdata cifs rw 0 0
nas:/export /mnt/nas/nfs nfs4 rw 0 0
/dev/sdc1 /mnt/nas/nfs/local xfs rw 0 0
"""


@pytest.fixture
def mounts(tmp_path):
    f = tmp_path / 'mounts'
    f.write_text(MOUNTS)
    return str(f)


@pytest.mark.unit
@pytest.mark.parametrize('path,expected', [
    ('/mnt/cache/appdata/mylar3', 'btrfs'),
    ('/mnt/user/appdata/mylar3', 'fuse.shfs'),
    ('/mnt/nas/appdata/mylar3', 'cifs'),
    ('/mnt/nas/nfs/x', 'nfs4'),
    ('/mnt/nas/nfs/local/x', 'xfs'),
    ('/config', 'ext4'),
])
def test_fs_type_uses_longest_mount(mounts, path, expected):
    assert db.fs_type(path, mounts) == expected


@pytest.mark.unit
@pytest.mark.parametrize('path,setting,expected', [
    ('/mnt/cache/appdata/mylar3', 'auto', 'wal'),
    ('/mnt/user/appdata/mylar3', 'auto', 'delete'),
    ('/mnt/nas/appdata/mylar3', 'auto', 'delete'),
    ('/mnt/nas/nfs/local/x', 'auto', 'wal'),
    ('/mnt/nas/appdata/mylar3', 'WAL', 'wal'),
    ('/mnt/cache/appdata/mylar3', 'delete', 'delete'),
    ('/mnt/cache/appdata/mylar3', None, 'wal'),
])
def test_wanted_journal_mode(mounts, path, setting, expected):
    assert db.wanted_journal_mode(path, setting, mounts) == expected


@pytest.mark.unit
def test_unknown_filesystem_defaults_to_wal(tmp_path):
    assert db.wanted_journal_mode('/anything', 'auto', str(tmp_path / 'missing')) == 'wal'

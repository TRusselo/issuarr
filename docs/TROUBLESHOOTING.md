# Troubleshooting

Start with **Tasks > Logs**. Most problems leave a warning there that names the file or setting involved. When you report a bug, attach a **Care package** from the **About** page: it bundles your logs and settings with passwords and keys removed.

## "Database is locked"

Issuarr keeps its database in SQLite. Older Mylar installs used SQLite's rollback journal, where a long write (a big import, a library refresh) blocks every read until it finishes, and pages fail with "database is locked".

Issuarr switches the database to WAL mode when it is on a local disk, so reads carry on during writes. On a network or FUSE filesystem (NFS, SMB/CIFS, sshfs, rclone, mergerfs, Unraid's `/mnt/user`) WAL isn't safe, so Issuarr keeps the rollback journal there. The log shows the choice at startup as `[DB] Journal mode ...`.

If you still see locking errors:

- Check where the data folder is (`/config` in Docker). If it is on a network share or Unraid's `/mnt/user`, moving it to a local disk lets Issuarr use WAL. On Unraid, `/mnt/cache/appdata/...` or `/mnt/diskN/...` paths are local.
- To force a mode, stop Issuarr and set `db_journal_mode` under `[General]` in `config.ini` to `auto` (the default), `wal` or `delete`. Only use `wal` on a local disk.

In WAL mode, `mylar.db-wal` and `mylar.db-shm` sit next to `mylar.db`. They are part of the database: don't delete them, and back up all three together with Issuarr stopped.

## Tagging fails on cbr files

With **Write metadata into files** on, Issuarr copies each file to a temporary `mylar_...` folder inside its cache folder, tags it there (converting cbr to cbz if you chose that), and files the tagged copy. The temporary folder is deleted afterwards, so seeing one appear and vanish is normal.

The warning `Failed to convert cbr to cbz - check permissions on folder ...` is logged for any failure while ComicTagger converts a cbr file, not only for permissions. When tagging fails during post-processing, Issuarr carries on and files the issue untagged. Things to check:

- **unrar.** cbr files are RAR archives and need `unrar`. The Docker image includes it. On a source install, check that `unrar` runs from the same user and `PATH` Issuarr uses.
- **The cache folder.** By default it is `cache` in the data folder (`/config/mylar/cache` in Docker), or whatever `cache_dir` in `config.ini` says. A `config.ini` restored from another machine can point `cache_dir` at a path that doesn't exist or isn't writable here. The user Issuarr runs as (`PUID`/`PGID` in Docker) must be able to create and delete folders there. If it is on a network share, try a local folder.
- **The library folder.** Issuarr writes the tagged file into the series folder, so it needs write access to the folder, not only to the file.
- **The file itself.** `file is not expected size` or `Failed the read` in the log means the archive is damaged or incomplete. Issuarr marks it as bad and doesn't file it.

## A series' files aren't found after moving

Issuarr stores the full path of every series folder. If the library now has a different path (a new machine, a new Docker volume path, Windows to Linux), see [Moving to a new machine or new paths](MIGRATING.md#moving-to-a-new-machine-or-new-paths).

## Importing comics that aren't in your library yet

Use **Tools > Import & scan**. See [Bringing in comics Mylar never knew about](MIGRATING.md#bringing-in-comics-mylar-never-knew-about) for the options.

## Direct downloads stay at Snatched

Watch **Downloads > Queue** for the download's progress, and **Tasks > Logs** for `[DDL]` lines. If you use JDownloader 2 for mirror links, see [Checking it works](JDOWNLOADER2.md#checking-it-works).

## This week's issues aren't on ComicVine yet

**Calendar > Upcoming** lists issues from this week's pull list for series you follow that ComicVine doesn't have an entry for yet. Issuarr takes its issue details from ComicVine, so it can't add the issue to the series until ComicVine does. ComicVine's volunteers often add new issues a little after release day. When the issue appears on ComicVine, refresh the series (Issuarr also refreshes followed series when the weekly list updates) and it shows up like any other issue.

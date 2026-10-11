# Moving from Mylar3 to Issuarr

Issuarr continues from the Mylar3 codebase, so it reads Mylar3's settings file (`config.ini`) and database (`mylar.db`) as they are. Your watchlist, issue statuses, history, story arcs and settings all carry over. Your comic files are not touched by the switch.

This guide covers installs of [mylar3/mylar3](https://github.com/mylar3/mylar3) and [MylarComics/mylar3](https://github.com/MylarComics/mylar3), in Docker or run from source.

- [1. Back up](#1-back-up)
- [2a. Switch a Docker install](#2a-switch-a-docker-install)
- [2b. Switch a source install](#2b-switch-a-source-install)
- [3. Check things after the first start](#3-check-things-after-the-first-start)
- [Where things are now](#where-things-are-now)
- [What works differently](#what-works-differently)
- [Moving to a new machine or new paths](#moving-to-a-new-machine-or-new-paths)
- [Bringing in comics Mylar never knew about](#bringing-in-comics-mylar-never-knew-about)
- [Going back to Mylar3](#going-back-to-mylar3)

## 1. Back up

Stop Mylar first, so the database isn't copied halfway through a write. Then copy its whole data folder somewhere safe:

| Install | Data folder |
|---|---|
| Docker (linuxserver image) | `mylar` inside the folder you mapped to `/config`, e.g. `/path/to/config/mylar` |
| From source | The folder you passed with `--datadir`, or the program folder itself if you never set one |

The files that matter are `config.ini`, `mylar.db`, and, if they exist, `mylar.db-wal` and `mylar.db-shm` (see [the journal note](#the-database-journal) below). The `cache` folder holds cover art and can be rebuilt, but copying it saves Issuarr downloading every cover again.

## 2a. Switch a Docker install

The Issuarr image is a drop-in replacement for `linuxserver/mylar3`. It uses the same `/config` layout, the same `PUID`, `PGID`, `UMASK` and `TZ` settings, and the same port 8090.

Change the image and keep everything else:

```diff
 services:
-  mylar3:
-    image: lscr.io/linuxserver/mylar3:latest
-    container_name: mylar3
+  issuarr:
+    image: ghcr.io/issuarr/issuarr:latest
+    container_name: issuarr
     environment:
       - PUID=1000
       - PGID=1000
       - TZ=Etc/UTC
     volumes:
       - /path/to/config:/config
       - /path/to/comics:/comics
       - /path/to/downloads:/downloads
     ports:
       - 8090:8090
     restart: unless-stopped
```

Renaming the service and container is optional. What matters is that every volume points to the same host folder **at the same path inside the container** as before. Mylar stored the full path of every series folder in its database, so if `/comics` becomes `/library`, Issuarr won't find your files. See [Moving to a new machine or new paths](#moving-to-a-new-machine-or-new-paths) if you need to change them.

Then pull and recreate the container:

```sh
docker compose pull issuarr
docker compose up -d issuarr
```

With `docker run`, stop and remove the old container and start a new one with the same `-v` and `-e` options and the image `ghcr.io/issuarr/issuarr:latest`.

> Issuarr's data folder is still `/config/mylar`, as in Mylar3, so nothing needs moving.

## 2b. Switch a source install

Clone Issuarr next to your old install rather than over it:

```sh
git clone https://github.com/issuarr/issuarr.git issuarr
cd issuarr
python3 -m venv venv && . venv/bin/activate
pip install -r requirements.txt
```

Then either point Issuarr at your existing data folder:

```sh
python3 Mylar.py --datadir /path/to/old/mylar-data
```

or copy `config.ini`, `mylar.db` (plus `mylar.db-wal` and `mylar.db-shm` if present) and the `cache` folder into the new `issuarr` folder and start it with `python3 Mylar.py`.

If your service file or init script (systemd, init.d) runs Mylar, change its path to the new folder. The examples in [init-scripts](../init-scripts) still use Mylar's names and paths, so adjust them to match yours.

**Update checks.** Mylar's update check follows the repository named in the `[Git]` section of `config.ini`, which on most installs says `MylarComics`. On its first start Issuarr changes that to `git_user = issuarr` and `git_branch = main`, so it compares you against Issuarr (`git_repo` defaults to `Issuarr`). If it pointed at your own fork, it is left alone.

## 3. Check things after the first start

Open `http://<your-server>:8090` and check:

1. **Library** lists your series, with the same have/total counts as before.
2. **Settings > General** shows the right **Comic folder**.
3. **Tasks > Logs** has no errors about paths that don't exist. Settings you restored from another machine (watch folder, download folder, review folder, cache folder, log folder) must exist where Issuarr runs.
4. **Settings > Download clients** and **Settings > Search providers**: use the **Test** buttons.
5. **Calendar** shows this week's releases. If it is empty, open the **⋯** menu on the Calendar and choose **Download the list again**.

### The database journal

On its first start Issuarr may switch the database to SQLite's WAL mode. Reads then no longer wait behind writes, which stops most "database is locked" errors. In WAL mode you'll see `mylar.db-wal` and `mylar.db-shm` next to `mylar.db`. They are part of the database: leave them alone, and back up all three together, with Issuarr stopped.

WAL is only safe on a local disk. If the data folder is on a network or FUSE filesystem (NFS, SMB/CIFS, sshfs, rclone, mergerfs, or Unraid's `/mnt/user`), Issuarr keeps the old rollback-journal mode, and switches back to it if the database is moved onto one. The log says which mode it chose (`[DB] Journal mode ...`).

To choose yourself, stop Issuarr and set `db_journal_mode` in the `[General]` section of `config.ini`:

| Value | Meaning |
|---|---|
| `auto` (default) | WAL on a local disk, rollback journal on a network or FUSE filesystem |
| `wal` | Always WAL. Only for a local disk Issuarr fails to recognise as local |
| `delete` | Always the old rollback journal, as Mylar3 did |

On Unraid, mapping `/config` to `/mnt/cache/appdata/...` or a disk path (`/mnt/diskN/...`) instead of `/mnt/user/appdata/...` keeps the database on a local filesystem, so `auto` can use WAL.

## Where things are now

The menus moved to a sidebar on the left. Press **Ctrl K** on any page to jump to a series or a page by name.

| In Mylar3 | In Issuarr |
|---|---|
| Home / series list | **Library > Series** |
| Manage Comics | **Library > Series**, then **Select** to act on several series at once |
| Manage Issues | **Library > Manage issues** (Wanted issues are on the **Wanted** page) |
| Search box, add series | **Add series** in the sidebar, or Ctrl K |
| Weekly pull list | **Calendar > This week** |
| Upcoming | **Calendar > Upcoming** |
| Manage > Scan Comic Library / Import | **Tools > Import & scan**, results under **Tools > Import results** |
| Manual post-processing | **Tools > Post-processing** |
| Export wanted / downloaded lists | **Tools > Export** |
| History | **Downloads > History** |
| Manage Failed | **Downloads > Failed** |
| DDL queue | **Downloads > Queue** |
| Activity / Jobs | **Tasks > Jobs** |
| Logs | **Tasks > Logs** |
| Settings (gear icon) | **Settings**, split into General, Appearance, Download clients, Search providers, Files & post-processing, and Notifications & advanced |
| Version info, CarePackage | **About** (the button is now called **Care package**) |
| Story arcs, reading list | **Story Arcs > Arcs**, **Story Arcs > Reading list**, **Story Arcs > CBL import** |

New pages with no Mylar3 equivalent: **Ledger** (gaps in every series, and which trades would fill them), **Library > Trades**, and **Tools > WebP conversion**.

Settings were reworded, but each one is the same `config.ini` key as before, so nothing needs re-entering.

## What works differently

- **Week numbers follow TalkHard.** Week N is the Sunday to Saturday week holding the year's Nth Wednesday, so a year has 52 or 53 weeks and there is no week 0. Around the new year, a week can carry a different number than Mylar3 gave it.
- **Volume 1 is kept.** When ComicVine sets a volume for a series, Issuarr uses it, v1 included. Mylar3 dropped v1.
- **"Wipe the NZB log"** is now **Clear the download log…** on **Downloads > History**, and explains what it affects first.
- **Manage issues** opens on Skipped and has no Wanted tab. Wanted issues are managed on the **Wanted** page.
- **GetComics searches** now also look for packs and series-and-year posts, so issues that only exist inside a pack can be found.
- **Notifications say Issuarr.** Snatch, download and tagging-error messages say Issuarr instead of Mylar, and Discord posts appear under the name Issuarr. If you filter or route notifications by the word "Mylar", update those rules.
- **The API is the same, with tighter checks.** Scripts that use your API key keep working unchanged, and the key can now also be sent as an `X-Api-Key` header. The web UI's internal message key no longer works for other commands, and IDs with quotes or spaces in them are now treated as IDs rather than SQL. See [API.md](API.md).

## Moving to a new machine or new paths

The simplest route is to give the library the same path it had before. In Docker that just means mapping the new host folder to the old container path (for example, keep `/comics`).

If the path has to change, Issuarr has no built-in way to rewrite every series folder at once. You can do it in the database:

1. Stop Issuarr and back up the data folder.
2. Change the library path in the database (this needs the `sqlite3` command):

   ```sh
   sqlite3 mylar.db "UPDATE comics SET ComicLocation = replace(ComicLocation, '/old/library', '/new/library');"
   ```

3. Change `destination_dir` in `config.ini` to the new path, along with any other paths that moved (`check_folder`, `ddl_location`, `cache_dir`, `log_dir`).
4. Start Issuarr and refresh a few series to confirm their files are found.

Moving between Windows and Linux also changes the slash direction. `python3 Mylar.py maintenance --fixslashes` corrects double slashes left in series paths.

## Bringing in comics Mylar never knew about

For comics that were never in Mylar's database, such as an old collection on another drive:

1. Map the folder into the container (for example `-v /path/to/old-comics:/import`), or note its path on a source install.
2. Go to **Tools > Import & scan**, enter that folder, and choose:
   - **Read the metadata inside the files** to use ComicInfo tags as well as file names to identify each issue.
   - **Move the files into your library**, and **Rename them to your naming settings** if you want your naming format applied. With moving off, files stay where they are and their issues are marked Archived.
3. **Save and scan**, then open **Tools > Import results** to choose which matched series to add.

Files are matched most reliably when their names follow `Series Name (Year) Issue.cbz` or similar. If a series isn't recognised, add it with **Add series** first and then scan again.

## Going back to Mylar3

Keep the backup from step 1. To go back, stop Issuarr and restore that copy of the data folder, rather than pointing Mylar3 at the database Issuarr has been using. The backup doesn't know about anything Issuarr downloaded since the switch, so rescan those series in Mylar3 to pick up their files.

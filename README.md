<img width="571" height="571" alt="Issuarr logo" src="https://github.com/user-attachments/assets/ab2c575b-db53-489e-aba5-ffe01bc0debb" />

# Issuarr

[![Build & Publish Docker Image](https://github.com/TRusselo/Issuarr/actions/workflows/docker_ghcr.yml/badge.svg?branch=main)](https://github.com/TRusselo/Issuarr/actions/workflows/docker_ghcr.yml)

**Issuarr is an automated comic book collection manager.** Tell it which series you follow and it watches for new and missing issues, downloads them, files and renames them, tags them with metadata, and keeps track of what your collection has and lacks.

It works with cbr and cbz files and gets its series and issue information from [ComicVine](https://comicvine.gamespot.com/). It downloads from Usenet, torrents or direct-download sites. You run it on your own computer or server and use it from a web browser.

Issuarr is the actively developed successor to **Mylar3**, so existing Mylar3 users can switch with their settings and database intact ([how](docs/MIGRATING.md)). It fits into a self-hosted *arr setup next to Sonarr, Radarr, Prowlarr, SABnzbd and qBittorrent, and its files work in comic readers and servers such as Komga, Kavita and ComicRack.


## How it works

1. **Build a watchlist.** Search for a series by name and add it, or point Issuarr at the comics you already have and it imports them.
2. **Issuarr learns the series.** It pulls every issue, annual and release date from ComicVine and checks which issues you already own.
3. **It finds what's missing.** Missing and newly released issues are marked *Wanted* and searched for on a schedule and through RSS feeds.
4. **It downloads them.** Results go to your Usenet or torrent client, or are downloaded directly.
5. **It files them.** Finished downloads are unpacked, matched to the right series and issue, renamed, moved into your library and tagged with ComicInfo metadata.

New issues of the series you follow arrive the same way, week after week.

## Features

### Your library
- Watchlist of series with per-issue status, cover art, publication details and progress at a glance.
- **Import an existing collection.** Issuarr scans your folders, reads existing ComicInfo tags and filenames, and matches files to ComicVine series. A status panel shows progress live, and large imports can be stopped and resumed, even across restarts.
- Configurable folder and file naming, for example `Marvel/Uncanny X-Men (1963)/Uncanny X-Men 141 (1981).cbz`.
- Annuals tracked inside their series or as series of their own.
- Duplicate handling: choose whether the larger file, the cbz or the cbr wins when two copies of an issue turn up.
- Handles libraries with thousands of series.

### Finding and downloading
- **Usenet:** any number of Newznab indexers, sent to SABnzbd, NZBGet or a blackhole folder.
- **Torrents:** Torznab indexers, sent to qBittorrent, Transmission, Deluge, rTorrent or uTorrent.
- **Direct download from GetComics.** Issuarr picks the right file even from posts with many links. You can order or switch off download hosts (GetComics' own server, Mega, Mediafire, Pixeldrain and others). Cloudflare is cleared with [FlareSolverr](https://github.com/FlareSolverr/FlareSolverr), and mirror links can be handed to [JDownloader 2](docs/JDOWNLOADER2.md).
- **Scheduled searches and RSS.** Recent releases are searched actively; older wanted issues are caught as they appear in RSS feeds.
- **Calendar (weekly pull list).** See every comic released this week, and look weeks ahead or months back. Weeks are numbered the way [TalkHard](https://talkhard.notaninja.party) numbers its pull lists. Upcoming issues of your series are wanted automatically.
- **Failed download handling:** a failed download is marked Failed and, with auto-retry on, searched for again.
- A live download queue with speed, progress and time left, and controls to abort, remove or restart a download.

### Filing and post-processing
- **Folder monitor** picks up anything that lands in your downloads folder. Your download client can also call Issuarr when a download finishes.
- Unpacks zip and rar downloads, including multi-issue packs. Every issue in a pack is matched against your whole watchlist, not only the issue you searched for.
- Issues nothing on your watchlist wants are moved to a review folder or deleted, your choice. Issuarr can also add their series automatically.
- Never silently replaces an issue you own: upgrades follow your duplicate rules.
- Manual post-processing for a folder of files you drop in yourself.

### Metadata
- Writes ComicInfo.xml into each file using a built-in copy of [ComicTagger](https://github.com/comictagger/comictagger). Readers such as Komga, Kavita and ComicRack use it to show titles, credits, story arcs and more.
- **Fill mode (default)** writes every field ComicVine has but never overwrites a value already in the file, so your hand-made corrections stay put. Skip and overwrite modes are available too.
- Optional conversion of cbr to cbz during tagging.
- series.json files for third-party apps.

### WebP conversion (optional)
- Converts the pages of new or existing comics to WebP to save space while keeping the pages looking the same.
- It only converts pages that benefit. Pages that are low quality, CMYK, unreadable, or that would grow are left as they are. Files that don't shrink by at least 10% are left untouched.
- Can run on import, for issues from a chosen year onward.
- **Bulk converter** with filters, a preview, confirmation steps and an optional folder that keeps your originals.
- Uses every CPU core.

### Knowing your collection: the Ledger
- **Missing issues:** every gap in every series, in one list.
- **Collected editions:** which trade paperbacks and omnibuses would fill your gaps, and which trades you own whose single issues you also have.
- **Trade management:** act on a trade, its missing singles or its duplicate singles, with an undo list when files are moved.

### Reading lists and story arcs
- Track story arcs across many series and keep them in reading order, optionally in their own folder.
- Import [CBL reading lists](https://github.com/DieselTech/CBL-ReadingLists) to add a whole event to your wanted list.
- A reading list, with optional syncing to a tablet.

### Integrations
- **OPDS** catalogue for reading apps on phones and tablets.
- **Notifications** on snatches and downloads via Discord, Slack, Mattermost, Telegram, Pushover, Pushbullet, Prowl, Boxcar, Gotify or email.
- **Web API** for scripts and other apps (see [API_REFERENCE](API_REFERENCE)).
- Login protection and HTTPS for the web interface.

## Requirements

- A free **ComicVine API key**, from [comicvine.gamespot.com/api](https://comicvine.gamespot.com/api/). Issuarr can't look up series without one.
- **Docker**, or **Python 3** with `unrar` installed (needed to read cbr files).
- At least one place to download from: a Newznab indexer plus SABnzbd or NZBGet, a Torznab indexer plus a torrent client, or GetComics direct download.
- Optional: FlareSolverr (for GetComics) and JDownloader 2 (for mirror links).

<img width="144" height="100" alt="Issuarr library cover wall" src="https://github.com/user-attachments/assets/5727ca6c-643e-41e2-8fa1-02b8389f2abd" /><img width="144" height="100" alt="Ledger showing missing issues per series" src="https://github.com/user-attachments/assets/13241f68-2c42-41eb-aa6d-a3e60bd11127" /><img width="144" height="100" alt="Wanted issues page" src="https://github.com/user-attachments/assets/2444ea0e-275c-4f5c-8ca4-adc964e616ac" /><img width="144" height="100" alt="Upcoming releases calendar" src="https://github.com/user-attachments/assets/69b87e52-3dc9-4d63-9cc1-c7bdebfb4a82" /><img width="144" height="100" alt="Trades and collected editions" src="https://github.com/user-attachments/assets/8d19055f-a237-4d29-af5d-098df06aa9d1" /><img width="144" height="130" alt="WebP conversion" src="https://github.com/user-attachments/assets/3f8f698a-43bf-4ef3-b2c5-ef47b908fe0e" />






## Installation

> **A note on the name.** Issuarr is newly renamed. The Docker image (`ghcr.io/trusselo/mylar3`) and the data folder (`/config/mylar`) keep Mylar's names so existing installs can switch without moving anything, and old links to `TRusselo/mylar3` lead here. The commands below are correct as written.

**Coming from Mylar3?** Your settings and database carry over. Follow [Moving from Mylar3 to Issuarr](docs/MIGRATING.md).

### Docker (recommended)

```sh
docker run -d --name issuarr \
  -e PUID=1000 -e PGID=1000 -e TZ=Etc/UTC \
  -p 8090:8090 \
  -v /path/to/config:/config \
  -v /path/to/comics:/comics \
  -v /path/to/downloads:/downloads \
  --restart unless-stopped \
  ghcr.io/trusselo/mylar3:latest
```

Or with Docker Compose:

```yaml
services:
  issuarr:
    image: ghcr.io/trusselo/mylar3:latest
    container_name: issuarr
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

| Setting | What it is |
|---|---|
| `PUID` / `PGID` | User and group that own your files (run `id` on the host to find them) |
| `TZ` | Your time zone, e.g. `America/Edmonton` |
| `UMASK` | Optional file permission mask |
| `/config` | Settings, database and cover cache (data lives in `/config/mylar`) |
| `/comics` | Your comic library |
| `/downloads` | Where your download clients put finished downloads |

The image follows the [linuxserver.io](https://www.linuxserver.io/) conventions and is a drop-in replacement for `linuxserver/mylar3`. To switch an existing Mylar3 container, change its image and keep your volumes at the same container paths; see [the migration guide](docs/MIGRATING.md#2a-switch-a-docker-install).

Issuarr's database works best on a local disk. If `/config` is on a network share or Unraid's `/mnt/user`, see ["Database is locked"](docs/TROUBLESHOOTING.md#database-is-locked).

### From source

```sh
git clone https://github.com/TRusselo/Issuarr.git issuarr
cd issuarr
python3 -m venv venv && . venv/bin/activate
pip install -r requirements.txt
python3 Mylar.py
```

Useful options: `-p <port>` to change the port, `--datadir <dir>` and `--config <file>` to keep data elsewhere, `-d` to run in the background, and `--nolaunch` to skip opening a browser. `python3 Mylar.py --help` lists them all.

## Getting started

Open `http://<your-server>:8090`. Every page is in the sidebar on the left, and **Ctrl K** jumps to any series or page by name.

1. **Settings > General:** enter your **ComicVine API key** and set the **Comic folder** to your library (`/comics` in Docker).
2. **Settings > Download clients:** connect your Usenet or torrent client.
3. **Settings > Search providers:** add your Newznab or Torznab indexers, or turn on **Download directly from sites** for GetComics. If you use direct downloads, set its **Download folder** there too, and see [Using JDownloader 2](docs/JDOWNLOADER2.md) if you want JDownloader 2 to handle mirror links.
4. **Settings > Files & post-processing:** turn on **Post-process downloads** and **Watch a folder for new comics**, and point it at the folder where finished downloads land. Turn on **Write metadata into files** if you want ComicInfo written to your files.
5. **Settings > Notifications & advanced:** check the **Series folder name** and **File name** formats.
6. **Add comics.** Use **Add series** in the sidebar to search for a series and add it, or **Tools > Import & scan** to import the comics you already have.

Issuarr marks the missing issues of new series *Wanted* and starts searching. Watch progress on the **Wanted** page, **Downloads > Queue**, and **Tasks > Jobs**.

## Key concepts

**Issue status.** Every issue has one:

| Status | Meaning |
|---|---|
| Wanted | Missing; Issuarr will search for it |
| Snatched | Found and sent to a downloader |
| Downloaded | In your library |
| Skipped | Missing, but not searched for |
| Archived | You own it but keep it outside Issuarr's folder |
| Ignored | Never search for it |
| Failed | The download failed; with failed-download handling and auto-retry on, it is searched for again |

**Series status.** A series is *Active* (checked for new issues) or *Paused* (left alone). It is shown as *Continuing* or *Ended* depending on recent releases.

**Search tiers.** Wanted issues added in the last 14 days are searched on every scheduled search. Older wanted issues are left to RSS so indexers aren't hammered. You can force a search for any issue at any time.

**Naming.** Folders and files are built from tokens such as `$Series`, `$Year`, `$Issue`, `$Annual`, `$Publisher`, `$VolumeN` and `$Type`. The defaults are `$Series ($Year)` for folders and `$Series $Annual $Issue ($Year)` for files.

**Your metadata comes first.** With the default fill mode, Issuarr adds tags your files are missing and never overwrites ones that are already there.

## Documentation

- [Moving from Mylar3 to Issuarr](docs/MIGRATING.md): switching an existing install, where pages moved, and changing library paths.
- [Using JDownloader 2](docs/JDOWNLOADER2.md) for direct-download mirror links.
- [Troubleshooting](docs/TROUBLESHOOTING.md): database locking, tagging failures, moved libraries.
- [API_REFERENCE](API_REFERENCE) for the web API.

This README and the `docs` folder are Issuarr's documentation. Mylar's old documentation website is no longer run by the Mylar team, so don't rely on it or follow its links.

## Getting help

- [Troubleshooting](docs/TROUBLESHOOTING.md) covers the common problems.
- [Issues](https://github.com/TRusselo/Issuarr/issues): bug reports and feature requests.
- **Tasks > Logs** shows the log. **About** shows version details and health checks, and its **Care package** button bundles logs and settings, with passwords and keys removed, to attach to a bug report.

## History and credits

Issuarr is the spiritual successor to Mylar. **evilhero** created Mylar and wrote most of it. It was rewritten for Python 3 as [mylar3/mylar3](https://github.com/mylar3/mylar3), and the community carried it on as [MylarComics/mylar3](https://github.com/MylarComics/mylar3). Both have now wound down: mylar3/mylar3 is no longer developed, and MylarComics/mylar3 is maintenance-only while its team works on a separate project.

Issuarr continues from that codebase and keeps adding to it. It is independent and not affiliated with or endorsed by the Mylar3 or MylarComics teams, so please bring Issuarr questions here rather than to them.

Thank you to:
- **evilhero**, for creating Mylar.
- Everyone who contributed to [mylar3/mylar3](https://github.com/mylar3/mylar3/graphs/contributors) and [MylarComics/mylar3](https://github.com/MylarComics/mylar3/graphs/contributors), with code, by helping others, or by donating.
- [ComicTagger](https://github.com/comictagger/comictagger), [ComicVine](https://comicvine.gamespot.com/), and [linuxserver.io](https://www.linuxserver.io/) for the container base.

## The Backstory
A couple of years ago, a multi-drive failure caused by bad HDD power splitters (lesson learned: don't use power splitters) left me with around 4,000 corrupted files out of 33,000. Paralyzed by the scale of it, I put off fixing it for a long time.

Recently, I teamed up with Claude to clean up the mess, get Mylar3 running, and backfill the missing issues. In the process, I fixed a few bugs and submitted some PRs. When I finally tracked down the right Discord, I found out active development on Mylar3 had effectively wrapped up as the devs moved on to new projects.

That left me with a choice: fork Mylar3 or find something else. I looked into a newer project on the scene, but it was missing several key features I relied on. Wanting to collaborate and avoid duplicating effort, I reached out to the dev and offered to help port over missing features from Mylar.

My offer was promptly—and surprisingly rudely—rejected.

So, here is Issuarr: an AI-assisted rewrite, redesign, and expansion of Mylar.

## License

GNU General Public License v3, the same as Mylar. See [LICENSE](LICENSE).

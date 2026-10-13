# Changelog

What changed in Issuarr, newest first. Each line ends with the commit that made the change; click it to see the code.

Releases come from the `main` branch and are the `latest` Docker image. Changes land on the `dev` branch first and are in the `dev` image before they are released.

## Unreleased (on dev)

Nothing yet.

## 0.8.3 (12 October 2026)

### Searching

- Searches keep going while a folder of files waits its turn to be filed (like Needs attention's Try filing again queued behind File as choices), except for the series in that folder. ([`71fc5d1`](https://github.com/issuarr/issuarr/commit/71fc5d1))

## 0.8.2 (12 October 2026)

### Searching

- Searching GetComics reuses results from the last 3 hours, stops reading single-issue results after 3 pages, and no longer waits after an issue's last search, so Wanted searches finish sooner. ([`845828f`](https://github.com/issuarr/issuarr/commit/845828f))
- Searches no longer all wait while a folder of files is being filed, only searches for the series in that folder. ([`03b01bc`](https://github.com/issuarr/issuarr/commit/03b01bc))

### Filing and Needs attention

- Packs grabbed for one series (say, its Annual) now file the other issues they contain too, instead of leaving them in Needs attention. ([`5a45280`](https://github.com/issuarr/issuarr/commit/5a45280))
- Filing accepts a filename year anywhere from the year a series began to a year after the issue came out, so pack issues labelled with the series' start year are filed. ([`8a02e55`](https://github.com/issuarr/issuarr/commit/8a02e55))
- Needs attention has a "Try filing again" button that runs filing over every listed file in the background, and does so by itself once after each update. Choices made with "File as" survive a restart, and every button answers straight away. ([`f1fdfbe`](https://github.com/issuarr/issuarr/commit/f1fdfbe))
- "File as" no longer fails with "__init__() should return None" while a download is being filed. ([`ffa8e6b`](https://github.com/issuarr/issuarr/commit/ffa8e6b))
- Needs attention shows each file's full folder with a Copy path button, its covers keep loading, and the page says it can be slow while downloads run. ([`63ee92a`](https://github.com/issuarr/issuarr/commit/63ee92a), [`f7d0963`](https://github.com/issuarr/issuarr/commit/f7d0963))
- Cover galleries ("007 03 of 03 covers") are read as the issue, not the cover count. ([`c43eb46`](https://github.com/issuarr/issuarr/commit/c43eb46))

### WebP conversion

- The library can be converted to WebP gradually: a set number of files each night in a time window, largest first. Damaged files go to Needs attention. ([`e01046a`](https://github.com/issuarr/issuarr/commit/e01046a), [`b3f250c`](https://github.com/issuarr/issuarr/commit/b3f250c), [`c39edf2`](https://github.com/issuarr/issuarr/commit/c39edf2))
- Conversion choices are remembered, start from modest defaults (2 threads, 1 file at a time), and quality, threads or keeping the originals can change without a new preview. ([`52748e2`](https://github.com/issuarr/issuarr/commit/52748e2), [`a8ffc4f`](https://github.com/issuarr/issuarr/commit/a8ffc4f))

### Ledger

- The Ledger shows whole-library totals above the missing-issues bar, its legend reads Have and Missing, not marked Wanted, and the Missing column sorts by total missing. ([`087a485`](https://github.com/issuarr/issuarr/commit/087a485))

## 0.8.1 (12 October 2026)

The first release: Issuarr is in Unraid Community Applications. It's still beta, below 1.0.

### Searching

- Searching is much faster: GetComics no longer sends the same search twice, stops reading result pages once they stop naming the series (at most 10 pages), and skips "None" searches for issues with no number. ([`906331f`](https://github.com/issuarr/issuarr/commit/906331f), [`12000ae`](https://github.com/issuarr/issuarr/commit/12000ae), [`a13311e`](https://github.com/issuarr/issuarr/commit/a13311e))
- The wait between GetComics search pages is a setting under Search providers > GetComics (3 to 60 seconds, 15 by default). ([`d149695`](https://github.com/issuarr/issuarr/commit/d149695))
- A search waits only while the same issue is being filed, not the whole series; packs still hold their series so nothing downloads twice. ([`e973a28`](https://github.com/issuarr/issuarr/commit/e973a28), [`aba8857`](https://github.com/issuarr/issuarr/commit/aba8857), [`c758d34`](https://github.com/issuarr/issuarr/commit/c758d34))
- Searches show what's being searched, Tier 1 searches are no longer dropped, and new releases wait for release day. ([`83fc80e`](https://github.com/issuarr/issuarr/commit/83fc80e), [`3dc3bcf`](https://github.com/issuarr/issuarr/commit/3dc3bcf))
- GetComics posts that add words inside the series name are matched. ([`dfb61c9`](https://github.com/issuarr/issuarr/commit/dfb61c9))
- The Internet Archive (archive.org) is a direct-download source, set in the download sources list as its own group; its torrents rank with the torrent group. ([`1fe01fd`](https://github.com/issuarr/issuarr/commit/1fe01fd), [`f4cb176`](https://github.com/issuarr/issuarr/commit/f4cb176))

### Downloads

- Download sources are four groups you can order and switch off: GetComics direct, cloud shares, torrent or magnet links (including GetComics posts' torrents), and the Internet Archive. ([`cc77073`](https://github.com/issuarr/issuarr/commit/cc77073), [`1585739`](https://github.com/issuarr/issuarr/commit/1585739), [`d6bebdf`](https://github.com/issuarr/issuarr/commit/d6bebdf))
- Downloaders and JDownloader 2 get the file host's address instead of the GetComics button, so JD2 no longer saves a web page instead of the comic. ([`5159a61`](https://github.com/issuarr/issuarr/commit/5159a61))
- The queue says who is downloading ("Issuarr · Mega", "JDownloader 2 · Mega or another mirror"). ([`203f965`](https://github.com/issuarr/issuarr/commit/203f965))
- "Finished" means filed: the queue shows Waiting to file, Filing, Finished, or Not filed with a pointer to Needs attention. ([`472a98b`](https://github.com/issuarr/issuarr/commit/472a98b), [`bbdd17a`](https://github.com/issuarr/issuarr/commit/bbdd17a))
- Clear finished and Clear failed buttons tidy the queue in one go; downloads still stopping are kept. ([`ff679ba`](https://github.com/issuarr/issuarr/commit/ff679ba), [`1a4928d`](https://github.com/issuarr/issuarr/commit/1a4928d))
- JDownloader 2 jobs that can never finish (expired file-host links, removed items, no progress for 6 hours) are let go and fail over instead of being watched forever; removing a JD2 download sticks. ([`eef9e27`](https://github.com/issuarr/issuarr/commit/eef9e27), [`5caed2e`](https://github.com/issuarr/issuarr/commit/5caed2e))
- The "downloads look stalled" notice ignores downloads JD2 is handling, and Restart queue clears what it counts. ([`9950f49`](https://github.com/issuarr/issuarr/commit/9950f49), [`5aef6bb`](https://github.com/issuarr/issuarr/commit/5aef6bb))
- Clicking Restart twice downloads an item once. ([`e6d1d84`](https://github.com/issuarr/issuarr/commit/e6d1d84))
- After a restart, finished downloads that were never filed are filed again, including partly filed packs. ([`f1b2600`](https://github.com/issuarr/issuarr/commit/f1b2600), [`316bf91`](https://github.com/issuarr/issuarr/commit/316bf91))
- Removing, stopping or clearing a download that never finished puts its issues back to Wanted, and Wanted > Reset stuck snatched issues fixes ones already stuck. ([`e35cb6a`](https://github.com/issuarr/issuarr/commit/e35cb6a), [`6852979`](https://github.com/issuarr/issuarr/commit/6852979))

### Filing and the library

- Downloads > Needs attention lists files Issuarr couldn't file on its own, with the file's cover next to the suggested issue's, to file, rename, ignore or trash them; it opens about 9 times faster on large libraries. ([`b3891e2`](https://github.com/issuarr/issuarr/commit/b3891e2), [`413fb22`](https://github.com/issuarr/issuarr/commit/413fb22))
- The sidebar shows the Needs attention count on Needs attention itself. ([`4111968`](https://github.com/issuarr/issuarr/commit/4111968))
- The folder monitor reports what each pass filed and sent to Needs attention, says when a check was skipped, and Running now no longer shows Idle while auto-add is still working. ([`45c3205`](https://github.com/issuarr/issuarr/commit/45c3205), [`b6672d3`](https://github.com/issuarr/issuarr/commit/b6672d3))
- A series keeps its issue list after Recheck files. ([`3d76fad`](https://github.com/issuarr/issuarr/commit/3d76fad))

### Screens

- Wanted and Queue show the way from Wanted to the library as a flow line. ([`fde40e0`](https://github.com/issuarr/issuarr/commit/fde40e0))
- Running now uses the flow line's colours and shows a WebP library conversion while it runs. ([`bc668d1`](https://github.com/issuarr/issuarr/commit/bc668d1), [`9ba96f1`](https://github.com/issuarr/issuarr/commit/9ba96f1), [`741f55c`](https://github.com/issuarr/issuarr/commit/741f55c))
- Ledger: yellow means only Snatched; trades and Duplicates singles have their own colours, and hovering a bar explains it. ([`617c13e`](https://github.com/issuarr/issuarr/commit/617c13e), [`7f670e9`](https://github.com/issuarr/issuarr/commit/7f670e9))
- Search providers explain missing providers, the search order can be reordered, and wide screens use two columns. ([`d04531e`](https://github.com/issuarr/issuarr/commit/d04531e), [`202bab6`](https://github.com/issuarr/issuarr/commit/202bab6))
- Issuarr has a version number, shown at the bottom of the sidebar and on the About page with the commit it was built from. ([`eec78d3`](https://github.com/issuarr/issuarr/commit/eec78d3), [`a401ba4`](https://github.com/issuarr/issuarr/commit/a401ba4))

### Project

- Development happens on the `dev` branch (`:dev` image); `main` is for releases (`:latest`). Version tags like `v0.8.1` also build `0.8.1` and `0.8` images, and each image checks for updates against the branch it was built from. ([`40f171a`](https://github.com/issuarr/issuarr/commit/40f171a), [`bda8495`](https://github.com/issuarr/issuarr/commit/bda8495))
- This changelog, also a page on the website. ([`eb1311b`](https://github.com/issuarr/issuarr/commit/eb1311b))

## Before releases (2 to 11 October 2026)

These changes were made straight on `main`, before Issuarr had releases.

### 11 October 2026

- Unraid Community Applications search finds Issuarr when people look for Kapowarr. ([`d1dc0cd`](https://github.com/issuarr/issuarr/commit/d1dc0cd), [`430e1ad`](https://github.com/issuarr/issuarr/commit/430e1ad))
- Direct downloads that a restart left behind after an old JDownloader 2 attempt are picked up again instead of sitting in the queue. ([`7e0a9d8`](https://github.com/issuarr/issuarr/commit/7e0a9d8))
- Fixes from the review of parallel downloads: tidier failover, abort and restart handling. ([`f93dc41`](https://github.com/issuarr/issuarr/commit/f93dc41))
- Issuarr is listed in Unraid Community Applications, and the Unraid guide covers both ways to install it. The template moved to `templates/`. ([`c914c5a`](https://github.com/issuarr/issuarr/commit/c914c5a), [`a5b4e4f`](https://github.com/issuarr/issuarr/commit/a5b4e4f), [`4b6d95f`](https://github.com/issuarr/issuarr/commit/4b6d95f))
- Wanted has a "Search all" button that queues every wanted issue. The scheduled search still only queues issues added in the last 14 days. ([`73980e2`](https://github.com/issuarr/issuarr/commit/73980e2))
- A one-issue series matches its file on rescan even when the file name has no issue number. ([`6b66a68`](https://github.com/issuarr/issuarr/commit/6b66a68))
- File hosts (Mega, Mediafire, Pixeldrain) download several files at once; GetComics' own server still takes one at a time. ([`b1584f1`](https://github.com/issuarr/issuarr/commit/b1584f1))
- When a direct download fails, one failover worker picks the next source to try, for every failed download. ([`adc4aab`](https://github.com/issuarr/issuarr/commit/adc4aab))
- When JDownloader 2 gives up, Issuarr tries its own downloaders before GetComics direct. ([`cca7cae`](https://github.com/issuarr/issuarr/commit/cca7cae))
- GetComics downloads no longer block each other, record where the file went, and save cookies safely. ([`16a5ee7`](https://github.com/issuarr/issuarr/commit/16a5ee7))
- File-host downloads record their path, stop when aborted, and Mega gives up instead of hanging. ([`3003d0b`](https://github.com/issuarr/issuarr/commit/3003d0b))
- The queue shows progress and speed for every active direct download. ([`923c7d7`](https://github.com/issuarr/issuarr/commit/923c7d7))
- No failover loop on hosts only JDownloader 2 can fetch, one GetComics download survives a restart, and abort is honoured during failover. ([`217d27f`](https://github.com/issuarr/issuarr/commit/217d27f))
- Design notes for parallel direct downloads. ([`009e93a`](https://github.com/issuarr/issuarr/commit/009e93a), [`f361944`](https://github.com/issuarr/issuarr/commit/f361944), [`68e1a50`](https://github.com/issuarr/issuarr/commit/68e1a50))
- GetComics pack grabs no longer crash on a typo or on posts with a TPBs section. ([`f24e48c`](https://github.com/issuarr/issuarr/commit/f24e48c), [`d0c780b`](https://github.com/issuarr/issuarr/commit/d0c780b))
- Wanted hides "Show more" when nothing is left to show. ([`1ac5944`](https://github.com/issuarr/issuarr/commit/1ac5944))
- One download queue for every source (Usenet, torrents, direct downloads, JDownloader 2) with live progress, including annuals, story-arc issues and one-offs. ([`ca397f9`](https://github.com/issuarr/issuarr/commit/ca397f9), [`2f95cc4`](https://github.com/issuarr/issuarr/commit/2f95cc4), [`53166a9`](https://github.com/issuarr/issuarr/commit/53166a9))
- Pages fill the window width, and Library bars use the Ledger's issue-order bar. ([`9e916bb`](https://github.com/issuarr/issuarr/commit/9e916bb), [`69c9c26`](https://github.com/issuarr/issuarr/commit/69c9c26))
- An Unraid template, ready for Community Applications. ([`d88d734`](https://github.com/issuarr/issuarr/commit/d88d734), [`5f23e41`](https://github.com/issuarr/issuarr/commit/5f23e41))
- Issuarr ships its own publisher imprints list and fetches updates to it daily, so fresh installs map imprints too. ([`42bdfbe`](https://github.com/issuarr/issuarr/commit/42bdfbe))
- The web API is documented, including an OpenAPI 3.1 description; the docs say the update command only restarts in Docker. ([`9d699a8`](https://github.com/issuarr/issuarr/commit/9d699a8), [`8746803`](https://github.com/issuarr/issuarr/commit/8746803))
- Web API security: the UI's key is locked down, database queries are parameterized, and commands that crashed are fixed. ([`e14924f`](https://github.com/issuarr/issuarr/commit/e14924f))
- The documentation is published as a website on GitHub Pages. ([`0fc44a0`](https://github.com/issuarr/issuarr/commit/0fc44a0))
- The repository moved to the `issuarr` organization; links, update checks and the Docker image name (`ghcr.io/issuarr/issuarr`) followed. ([`b4acf2f`](https://github.com/issuarr/issuarr/commit/b4acf2f), [`d734e68`](https://github.com/issuarr/issuarr/commit/d734e68), [`1a40db7`](https://github.com/issuarr/issuarr/commit/1a40db7), [`2dc53a7`](https://github.com/issuarr/issuarr/commit/2dc53a7), [`7cdff95`](https://github.com/issuarr/issuarr/commit/7cdff95), [`eaf7175`](https://github.com/issuarr/issuarr/commit/eaf7175))
- Notifications say Issuarr instead of Mylar, and update checks follow Issuarr rather than the retired Mylar repository. ([`b4acf2f`](https://github.com/issuarr/issuarr/commit/b4acf2f), [`fa616bd`](https://github.com/issuarr/issuarr/commit/fa616bd))
- Guides for moving from Mylar3, JDownloader 2, and troubleshooting. ([`6fceed5`](https://github.com/issuarr/issuarr/commit/6fceed5))
- GetComics search fixes: pack search, digital series, unnumbered #1 issues and pack issue ranges. ([`10b24dc`](https://github.com/issuarr/issuarr/commit/10b24dc))
- Search accepts several words, and Manage issues no longer repeats what Wanted shows. ([`b115451`](https://github.com/issuarr/issuarr/commit/b115451))
- Redesigned Add series results, series settings, manage issues and rename preview. ([`2bc8763`](https://github.com/issuarr/issuarr/commit/2bc8763))
- Pull-list week numbers match TalkHard (weeks run Sunday to Saturday, no week 0), the database uses WAL mode only on local disks, and a volume ComicVine sets explicitly is kept, Volume 1 included. ([`be1cc45`](https://github.com/issuarr/issuarr/commit/be1cc45))
- Library bars show where the gaps are; missing issues are split into before, gap and after, with clearer buttons. ([`0e5c4ba`](https://github.com/issuarr/issuarr/commit/0e5c4ba))
- Settings rebuilt as labelled rows; About is its own page. ([`e08fee0`](https://github.com/issuarr/issuarr/commit/e08fee0))

### 10 October 2026

- The download log explains what clearing it does. ([`36dc5e6`](https://github.com/issuarr/issuarr/commit/36dc5e6))
- Fixed bugs reported on the retired Mylar3 project that still applied: post-processing could stop for good, story-arc searches queued the wrong issues, `*` stayed in renamed file names, SABnzbd failures were missed, and titles ending in a year lost the year. ([`9426f5e`](https://github.com/issuarr/issuarr/commit/9426f5e))

### 8 October 2026

- The series page's issue table has status pills, labelled actions and filter chips. ([`fb08363`](https://github.com/issuarr/issuarr/commit/fb08363))

### 7 October 2026

- The new Issuarr interface: one sidebar, a Ctrl K search, and custom CSS. ([`5998138`](https://github.com/issuarr/issuarr/commit/5998138))
- Issuarr logo in the sidebar, as the favicon and as the home-screen icon. ([`b00f383`](https://github.com/issuarr/issuarr/commit/b00f383), [`f7cdd83`](https://github.com/issuarr/issuarr/commit/f7cdd83), [`a459906`](https://github.com/issuarr/issuarr/commit/a459906), [`4459015`](https://github.com/issuarr/issuarr/commit/4459015), [`7b8d861`](https://github.com/issuarr/issuarr/commit/7b8d861))
- Tasks > Jobs and Downloads > Queue are real pages, plus Downloads > History and Failed, and Tasks > Logs. ([`d32e045`](https://github.com/issuarr/issuarr/commit/d32e045), [`05786ab`](https://github.com/issuarr/issuarr/commit/05786ab))
- Library as a wall of covers, a new series page header, and Add series separate from Ctrl K. ([`4aa9d2a`](https://github.com/issuarr/issuarr/commit/4aa9d2a))
- New Wanted, Calendar (pull list) and Upcoming pages. ([`1ec3f53`](https://github.com/issuarr/issuarr/commit/1ec3f53))
- New Tools pages: import and scan, post-processing, export, import results and WebP. ([`ef2845a`](https://github.com/issuarr/issuarr/commit/ef2845a))
- Ledger and Trades in the Issuarr style, with status bars. ([`7cf4b44`](https://github.com/issuarr/issuarr/commit/7cf4b44))
- Story Arcs: arc list, arc detail, reading list and CBL import. ([`2707e6d`](https://github.com/issuarr/issuarr/commit/2707e6d))
- README updates: images, backstory and how to help. ([`0c2f4f2`](https://github.com/issuarr/issuarr/commit/0c2f4f2), [`0a1faec`](https://github.com/issuarr/issuarr/commit/0a1faec), [`8d8f30b`](https://github.com/issuarr/issuarr/commit/8d8f30b))

### 6 October 2026

- A README that introduces Issuarr, the successor to Mylar, to new users. ([`8cc001b`](https://github.com/issuarr/issuarr/commit/8cc001b), [`51f1f3d`](https://github.com/issuarr/issuarr/commit/51f1f3d))
- A setting for the direct-download folder on the settings page. ([`559773b`](https://github.com/issuarr/issuarr/commit/559773b))
- Manage Comics loads its rows as data, so big libraries don't crash the tab. ([`01ef053`](https://github.com/issuarr/issuarr/commit/01ef053))

### 5 October 2026

- A wanted issue is downloaded from its own line in a GetComics post instead of the whole post. ([`b81b437`](https://github.com/issuarr/issuarr/commit/b81b437))
- Aborting a pack download undoes its Snatched marks. ([`6e9108f`](https://github.com/issuarr/issuarr/commit/6e9108f))
- Packs titled "<series> Complete" are accepted for that series. ([`9c13730`](https://github.com/issuarr/issuarr/commit/9c13730))
- Numbered annual series are searched by issue number. ([`8421b37`](https://github.com/issuarr/issuarr/commit/8421b37))
- File names with zero-padded reading-order numbers, or story-arc labels after them, are read correctly. ([`2791cb3`](https://github.com/issuarr/issuarr/commit/2791cb3), [`49561ba`](https://github.com/issuarr/issuarr/commit/49561ba))
- New API command `setComicLocation` points a series at another existing folder. ([`7dd18fb`](https://github.com/issuarr/issuarr/commit/7dd18fb))
- WebP conversion is faster: pages are encoded by a shared pool of workers and several files convert at once. The holding folder for originals is remembered after a preview. ([`7af0913`](https://github.com/issuarr/issuarr/commit/7af0913), [`25d3658`](https://github.com/issuarr/issuarr/commit/25d3658))

### 4 October 2026

- Optional WebP conversion on import, plus a guarded bulk converter. ([`961d49c`](https://github.com/issuarr/issuarr/commit/961d49c))
- Tagging fills in missing tags without overwriting existing ones; the WebP step repacks cbr files as cbz. ([`64823ef`](https://github.com/issuarr/issuarr/commit/64823ef))
- Post-processing unpacks zip and rar downloads from direct downloads, torrents, JDownloader 2 and the folder monitor, and finds GetComics packs. Pack issues upgrade owned files only under the normal duplicate rules. ([`599d8c5`](https://github.com/issuarr/issuarr/commit/599d8c5), [`fcb4e80`](https://github.com/issuarr/issuarr/commit/fcb4e80))
- Settings to delete archives after extraction and to ignore archives without enough comic pages. ([`05e9906`](https://github.com/issuarr/issuarr/commit/05e9906))
- Packs are matched against the whole watchlist; what nothing wants is moved or deleted so the monitored folder stays clear. ([`ffeb321`](https://github.com/issuarr/issuarr/commit/ffeb321))
- Optional: add the series of comics nothing on the watchlist wants, using ComicVine and the pack's release week. ([`9e4724c`](https://github.com/issuarr/issuarr/commit/9e4724c))
- Issues in dated pack folders are matched to their series by release date. ([`deabf38`](https://github.com/issuarr/issuarr/commit/deabf38))
- Only one post-processing job runs at a time, searches wait while post-processing or auto-add runs, and auto-added series are filed straight away. ([`e367a77`](https://github.com/issuarr/issuarr/commit/e367a77), [`a7bc268`](https://github.com/issuarr/issuarr/commit/a7bc268))
- A folder monitor and post-processing activity panel; the monitor no longer stays paused when enabled, and its passes never stack. ([`ff33be1`](https://github.com/issuarr/issuarr/commit/ff33be1), [`d77d06c`](https://github.com/issuarr/issuarr/commit/d77d06c))
- Job intervals can be edited from Activity / Jobs. ([`d77d06c`](https://github.com/issuarr/issuarr/commit/d77d06c))
- A failed direct or JDownloader 2 download retries the search when failed-download handling and auto-retry are on. ([`ccd3436`](https://github.com/issuarr/issuarr/commit/ccd3436))
- Abort and remove actually stop a running download. ([`cd08282`](https://github.com/issuarr/issuarr/commit/cd08282))
- Queue Management updates itself, reloads at startup, never queues the same thing twice, and shows speed, progress and time left. ([`5bcf12a`](https://github.com/issuarr/issuarr/commit/5bcf12a), [`70fe813`](https://github.com/issuarr/issuarr/commit/70fe813))
- Option to try GetComics direct last for large files; post sizes are read correctly. ([`62ac81c`](https://github.com/issuarr/issuarr/commit/62ac81c))
- Ledger: Trade Management tab, trade column, "Complete series" on missing issues, duplicate singles with an undo list, and better matching of collected issues. ([`b0b2cb7`](https://github.com/issuarr/issuarr/commit/b0b2cb7), [`fe507da`](https://github.com/issuarr/issuarr/commit/fe507da), [`4b7014a`](https://github.com/issuarr/issuarr/commit/4b7014a), [`919b708`](https://github.com/issuarr/issuarr/commit/919b708), [`20f9535`](https://github.com/issuarr/issuarr/commit/20f9535))
- Ledger: Wanted counts, status filter, keyboard selection and sticky action bars; select-all can unselect again. ([`2727ee9`](https://github.com/issuarr/issuarr/commit/2727ee9), [`8dea186`](https://github.com/issuarr/issuarr/commit/8dea186))
- Metron was tried as a second source for collected-edition contents and then removed. ([`5556c34`](https://github.com/issuarr/issuarr/commit/5556c34), [`5ed829a`](https://github.com/issuarr/issuarr/commit/5ed829a), [`00483c7`](https://github.com/issuarr/issuarr/commit/00483c7), [`a36b727`](https://github.com/issuarr/issuarr/commit/a36b727))
- Refreshing skips annual lookups when annual integration is off, and pack dates refresh only the newest volume of a series. ([`186ea36`](https://github.com/issuarr/issuarr/commit/186ea36), [`bbfe98a`](https://github.com/issuarr/issuarr/commit/bbfe98a))
- A solid header with a Library link and the current page, page actions beside the title, and underlined tabs. ([`3c3ed09`](https://github.com/issuarr/issuarr/commit/3c3ed09))
- The direct-download queue worker survives an item error; mirror routing and Cloudflare handling on the GetComics file server are fixed; JDownloader 2 jobs are tracked by package. ([`3e949d9`](https://github.com/issuarr/issuarr/commit/3e949d9), [`b7bd77f`](https://github.com/issuarr/issuarr/commit/b7bd77f))

### 3 October 2026

- The Ledger: a missing-issue list and collected-edition coverage page. ([`038c71f`](https://github.com/issuarr/issuarr/commit/038c71f))
- Metron reprint lists and a Metron token setting (later removed). ([`25abf90`](https://github.com/issuarr/issuarr/commit/25abf90), [`b51c41a`](https://github.com/issuarr/issuarr/commit/b51c41a))
- Direct downloads try the GetComics server through FlareSolverr first and send mirrors to JDownloader 2 if that fails. Download sources can be ordered, Pixeldrain usage is shown and a Pixeldrain API key can be set. ([`34f4c97`](https://github.com/issuarr/issuarr/commit/34f4c97), [`86e81ee`](https://github.com/issuarr/issuarr/commit/86e81ee))
- FlareSolverr can be set up in Search providers > DDL. ([`5bb4e90`](https://github.com/issuarr/issuarr/commit/5bb4e90))
- JDownloader 2 downloads are judged per package and fall back to the built-in downloader; finished jobs are cleared. ([`ec31023`](https://github.com/issuarr/issuarr/commit/ec31023))
- An issue is marked Failed when every download link fails or a JDownloader 2 download can't complete. ([`7b06962`](https://github.com/issuarr/issuarr/commit/7b06962), [`80382d8`](https://github.com/issuarr/issuarr/commit/80382d8))
- Annuals aren't counted in Have when annual integration is off, and annual groups show expanded on the series page. ([`ab4fdd5`](https://github.com/issuarr/issuarr/commit/ab4fdd5), [`07b8f73`](https://github.com/issuarr/issuarr/commit/07b8f73))

### 2 October 2026

- Library scans and mass imports can be guarded, stopped, resumed and tracked, with a status panel and a header indicator. ([`f71c530`](https://github.com/issuarr/issuarr/commit/f71c530), [`2f5583b`](https://github.com/issuarr/issuarr/commit/2f5583b), [`27e88da`](https://github.com/issuarr/issuarr/commit/27e88da), [`3b95746`](https://github.com/issuarr/issuarr/commit/3b95746), [`9cc5407`](https://github.com/issuarr/issuarr/commit/9cc5407), [`6385a1a`](https://github.com/issuarr/issuarr/commit/6385a1a), [`f3debb1`](https://github.com/issuarr/issuarr/commit/f3debb1), [`4fee17d`](https://github.com/issuarr/issuarr/commit/4fee17d))
- ComicVine rate limits are waited out instead of being read as empty results, and missing ComicVine data fails cleanly. ([`0e4319b`](https://github.com/issuarr/issuarr/commit/0e4319b), [`51dac34`](https://github.com/issuarr/issuarr/commit/51dac34), [`a5124fb`](https://github.com/issuarr/issuarr/commit/a5124fb))
- Library sync never drops files the ComicVine lookup couldn't match. ([`5d247df`](https://github.com/issuarr/issuarr/commit/5d247df))
- Weekly pull-list week numbers are handled as numbers. ([`e6bd061`](https://github.com/issuarr/issuarr/commit/e6bd061))
- The API's refreshComic includes the series year. ([`39bb4a4`](https://github.com/issuarr/issuarr/commit/39bb4a4))
- The Discord test reports success correctly. ([`c4703b1`](https://github.com/issuarr/issuarr/commit/c4703b1))
- A linuxserver.io-compatible Docker image published to GitHub's container registry. ([`e33d667`](https://github.com/issuarr/issuarr/commit/e33d667), [`088dce0`](https://github.com/issuarr/issuarr/commit/088dce0), [`4965931`](https://github.com/issuarr/issuarr/commit/4965931))

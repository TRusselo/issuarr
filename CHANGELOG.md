# Changelog

What changed in Issuarr, newest first. Each line ends with the commit that made the change; click it to see the code.

Releases come from the `main` branch and are the `latest` Docker image. Changes land on the `dev` branch first and are in the `dev` image before they are released.

## Unreleased (on dev)

- Development now happens on the `dev` branch, which builds the `ghcr.io/issuarr/issuarr:dev` image. `main` is for releases and keeps building `latest`; version tags like `v1.0.0` also build `1.0.0` and `1.0` images. ([`40f171a`](https://github.com/issuarr/issuarr/commit/40f171a))
- The Docker image checks for updates against the branch it was built from, so a `dev` container compares itself with `dev` and a `latest` container with `main`. ([`40f171a`](https://github.com/issuarr/issuarr/commit/40f171a))
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

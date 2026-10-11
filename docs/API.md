# Issuarr web API

Issuarr has the same web API as Mylar3, so scripts and apps written for Mylar keep working. This page describes how it actually behaves today.

## Turning it on

1. **Settings > General > API and OPDS:** turn on **Issuarr API** and click **New key** to create a 32-character API key.
2. Save. The key is stored in `config.ini` as `api_key`.

## Making a call

```
GET http://HOST:8090/HTTP_ROOT/api?cmd=COMMAND&apikey=KEY[&param=value...]
```

You can also send the key in a header instead of the URL, which keeps it out of proxy and access logs:

```
curl -H "X-Api-Key: KEY" "http://localhost:8090/api?cmd=getIndex"
```

`Api-Key` works as a header name too. The `/api` path doesn't use the web UI login, so the key is the only protection. Don't expose the port to the internet without a reverse proxy.

The web UI has a second, internal key that it uses to poll for status messages. That key only works for `checkGlobalMessages`. Use the real API key for everything else.

## Responses

Most commands return JSON in this shape:

```json
{"success": true, "data": ...}
{"success": false, "error": {"code": 460, "message": "Missing parameter: id"}}
```

Things to know before you write a client:

- **Errors come back with HTTP status 200.** Check `success`, not the status code. `error.code` is 460 for bad input and 500 when the command itself failed.
- **A few commands don't use the `success`/`data` envelope**, for compatibility with old Mylar clients. They're marked *bare* below: they return a plain JSON list or object. On failure they still return the error shape above.
- **Some commands return the text `OK`** once the action has been handed off. They're marked *OK* below. `OK` means the request was accepted, not that the work finished.
- `getArt` returns a JPEG image, and `downloadIssue` / `downloadNZB` return the file.
- Add `callback=NAME` to get JSONP (`NAME(...)`). The name must be a plain JavaScript identifier.

## Commands

IDs are ComicVine IDs. `id` on series commands is the ComicID (a `4050-` prefix is stripped by `delComic` and `refreshComic`). Issue commands take the IssueID.

### Reading the library

| Command | Parameters | Returns |
|---|---|---|
| `getIndex` | | Every series on the watchlist: `id, name, imageURL, status, publisher, publishYear, year, latestIssue, totalIssues, detailsURL, alternateSearch`. |
| `getComic` | `id` | `{comic: [...], issues: [...], annuals: [...]}` for one series. |
| `getComicInfo` | `id` | One series, as a one-item list. Fails if not found. |
| `getIssueInfo` | `id` (IssueID) | One issue, as a one-item list. Fails if not found. |
| `getUpcoming` | `include_downloaded_issues=Y` (optional) | *bare.* This week's pull-list issues for watched series that are Wanted (or also Snatched/Downloaded with `Y`). |
| `getWanted` | `story_arcs=true` (optional) | *bare.* `{issues: [...]}`, plus `story_arcs` and `annuals` when those features are on. |
| `getHistory` | | Every row of the snatch history, newest first. |
| `getReadList` | | The reading list. |
| `getStoryArc` | `id` (optional), `customOnly` (optional) | *bare.* All arcs, or the issues in one arc in reading order. |
| `listAnnualSeries` | `list_issues` or `group_series` | Annuals that were merged into series. |
| `seriesjsonListing` | `missing` (optional) | ComicID and folder for each series, optionally only those without a `series.json`. |
| `getArt` | `id` | The series cover as a JPEG. |
| `downloadIssue` | `id` (IssueID) | The issue file, if it has been downloaded. |
| `downloadNZB` | `nzbname` | An NZB file from the cache folder (file name only). |
| `getLogs` | | *bare.* Recent log lines. |
| `getVersion` | | `git_path, install_type, current_version, latest_version, commits_behind`. |
| `checkGithub` | | Checks for an update, then returns the same as `getVersion`. |
| `listProviders` | | Newznab and Torznab providers, including their API keys. |
| `getAPI` | `username`, `password` | The API key. Works only when a web UI username and password are set. Doesn't need `apikey`. |

### Searching ComicVine

| Command | Parameters | Returns |
|---|---|---|
| `findComic` | `name`, optional `issue`, `type_` (`comic` or `story_arc`), `mode` (`series`, `pullseries`, `want`), `page`, `pageSize` | *bare.* Matching series, newest first. |

### Changing things

| Command | Parameters | Effect |
|---|---|---|
| `addComic` | `id` | Adds a series by ComicID (runs in the background). |
| `refreshComic` | `id` (comma-separated for several) | Queues series for a metadata refresh. |
| `pauseComic` / `resumeComic` | `id` | *OK.* Sets the series to Paused or Active. |
| `queueIssue` | `id` (IssueID) | *OK.* Marks the issue Wanted and searches for it right away. |
| `unqueueIssue` | `id` (IssueID) | *OK.* Marks the issue Skipped. |
| `changeStatus` | `status_from`, `status_to`, `id` (ComicID or `all`) | Changes every issue in the series (or library) from one status to another. |
| `changeBookType` | `id`, `booktype` (`Print`, `Digital`, `TPB`, `GN`, `HC`, `One-Shot`) | Forces the series' book type. |
| `recheckFiles` | `id` | Rescans the series folder. |
| `setComicLocation` | `id`, `location` | Points the series at an existing folder, then rescans it. |
| `regenerateCovers` | `id` (ComicID, comma list, `all` or `missing`) | Re-downloads covers in the background. |
| `refreshSeriesjson` | `comicid` (ComicID, `all`, `missing` or `refresh-missing`) | Rewrites `series.json` files. |
| `addStoryArc` | `id` or `storyarcname`, plus `issues` (IssueIDs) or `arclist` | Creates an arc or adds issues to one. |
| `addProvider` | `providertype` (`newznab`/`torznab`), `name`, `host`, `prov_apikey`, `enabled`, optional `categories`, `uid` | Adds an indexer. |
| `changeProvider` | `providertype`, `prov_id` or `name`, then any of `altername`, `host`, `prov_apikey`, `enabled`/`disabled`, `categories`, `uid` | Edits an indexer. |
| `delProvider` | `providertype`, `prov_id` or `name` | Removes an indexer. |
| `forceSearch` | | *OK.* Searches for every Wanted issue. The call doesn't return until the search finishes. |
| `forceProcess` | `nzb_name`, `nzb_folder`, optional `issueid`, `comicid`, `failed`, `ddl`, `oneoff=True` | Queues a download folder for post-processing. Returns a plain sentence. Used by download-client scripts. |
| `clearLogs` | | Clears the in-memory log. Returns the text `Cleared log`. |

### Destructive commands

These run as soon as they're called. There's no confirmation step, so don't give them to an automated agent unless you mean to.

| Command | Parameters | Effect |
|---|---|---|
| `delComic` | `id`, `directory=true` (optional) | Removes the series from the database. With `directory=true` it also **deletes the series folder from disk**. |
| `changeStatus` with `id=all` | | Changes issue status across the whole library. |
| `shutdown` / `restart` / `update` | | *OK.* Stops, restarts or updates Issuarr. In Docker, `update` only restarts; pull a new `ghcr.io/issuarr/issuarr` image to update. |

## The `/rest` endpoints

`/rest/watchlist`, `/rest/comics` and `/rest/comic/COMICID[/issues | /issue/ISSUEID]` are an older, unfinished read-only API. They need the key in an `Api-Key` header. `/rest/comics` returns text rather than JSON. Use `/api` instead.

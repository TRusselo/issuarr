# Using JDownloader 2 for direct downloads

When Issuarr downloads from GetComics, it can download from GetComics' own server and some hosts itself. [JDownloader 2](https://jdownloader.org/) (JD2) can take over the mirror links (Mega, Mediafire, Pixeldrain and other hosts), which helps when those hosts need a premium account or the built-in downloader keeps failing on them.

This is optional. Direct downloads work without it.

## How Issuarr uses JD2

- Issuarr still tries the GetComics server itself first. The mirror links go to JD2 when that fails, or straight away when a post only has hosts JD2 handles.
- Mirrors get JD2 priorities in the host order you set under **Settings > Search providers > Direct downloads**, highest first.
- If JD2 can't be reached or refuses the links, Issuarr hands the download back to its built-in downloader.
- If a job never shows up in JD2's download list (for example because every link is offline), Issuarr gives up after about three minutes and marks the issue Failed, so it doesn't sit at Snatched.
- When JD2 finishes, Issuarr post-processes the download from JD2's download folder like any other download.

## 1. Set up JD2

JD2 has to accept links from Issuarr over its local API, which is turned off by default.

1. In JD2, open **Settings > Advanced Settings** and search for `Remote API`.
2. Turn on the deprecated API (listed as **Enable Deprecated Api**).
3. If Issuarr runs on another computer or in another container, also turn off the setting that limits the deprecated API to localhost. Otherwise JD2 only answers requests from its own machine.
4. Note the API port (3128 by default) and make sure Issuarr can reach it. In Docker, publish the port or put both containers on the same Docker network.

The deprecated API has no password. Anyone who can reach that port can add downloads, so don't expose it to the internet.

## 2. Share the download folder

Issuarr tells JD2 where to save each download, then opens that same folder to file it. The folder has to have **the same path in both programs**.

In Docker, map the same host folder to the same container path in both containers:

```yaml
services:
  issuarr:
    image: ghcr.io/issuarr/issuarr:latest
    volumes:
      - /path/to/config:/config
      - /path/to/comics:/comics
      - /path/to/downloads:/downloads
  jdownloader2:
    image: jlesage/jdownloader-2
    volumes:
      - /path/to/jd2-config:/config
      - /path/to/downloads:/downloads
```

Here both see the folder as `/downloads`, so `/downloads/jd2` works in both. The JD2 image is only an example; any JD2 install works as long as the paths match.

The user JD2 runs as must be able to write there, and the user Issuarr runs as (`PUID`/`PGID` in Docker) must be able to read and move the files. Keep this folder out of the folder Issuarr watches for new comics, so it doesn't pick up downloads before they finish.

## 3. Set up Issuarr

1. Go to **Settings > Search providers > Direct downloads** and turn on **Download directly from sites**.
2. Turn on **Send other hosts to JDownloader 2**.
3. **JDownloader 2 address:** the API address, for example `http://jdownloader2:3128` or `http://192.168.1.20:3128`. Include the port.
4. **Download folder:** the shared folder from step 2, for example `/downloads/jd2`.
5. Make sure **Settings > Files & post-processing > Post-process downloads** is on, or finished JD2 downloads won't be filed.
6. Save.

## Checking it works

Search for a wanted issue whose GetComics post has mirror links. **Tasks > Logs** shows `[JD2]` lines when links are sent, and `[JD2-QUEUE]` lines as the job is watched and filed. In JD2 the package is named after the series and year.

| Log line | What it means |
|---|---|
| `Submission failed ... falling back to DDL queue` | Issuarr couldn't reach JD2. Check the address, the port, and the two Remote API settings. |
| `never reached the JD2 download list` | JD2 got the links but didn't start them, usually because the host is offline or needs an account. |
| `JD2 destination is not configured` | The **Download folder** setting is empty. |

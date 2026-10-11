#!/bin/sh
# Stage the website's pages in build/site-src for MkDocs (see mkdocs.yml).
# The home page is made from README.md so the two never drift apart, and each
# page gets the title and description search engines show, which would clutter
# the files if they lived there on GitHub.
set -e
cd "$(dirname "$0")/.."
src=build/site-src
rm -rf "$src"
mkdir -p "$src"
cp -r docs/assets docs/robots.txt "$src"/

page() {  # page <file in docs/ or README.md> <output name> <title> <description>
    {
        printf -- '---\ntitle: "%s"\ndescription: "%s"\n---\n\n' "$3" "$4"
        sed -e 's#](docs/#](#g' \
            -e 's#width="571" height="571"#width="280" height="280"#' \
            -e 's#](LICENSE)#](https://github.com/issuarr/issuarr/blob/main/LICENSE)#g' \
            "$1"
    } > "$src/$2"
}

page README.md index.md \
    "Issuarr: self-hosted comic book manager and Mylar3 alternative" \
    "Issuarr automatically finds, downloads, renames, tags and organizes your comic books (cbz and cbr). A free, open-source, self-hosted successor to Mylar3 for Usenet, torrents and GetComics, with Docker images."
page docs/MIGRATING.md MIGRATING.md \
    "Moving from Mylar3 to Issuarr" \
    "Switch from Mylar3 to Issuarr in Docker or from source, keeping your settings, watchlist, history and database."
page docs/UNRAID.md UNRAID.md \
    "Installing Issuarr on Unraid" \
    "Install Issuarr on Unraid with its Docker template, choose appdata and library paths, or switch an existing Mylar3 container."
page docs/JDOWNLOADER2.md JDOWNLOADER2.md \
    "Using JDownloader 2 with Issuarr" \
    "Hand GetComics mirror links (Mega, Mediafire, Pixeldrain) from Issuarr to JDownloader 2."
page docs/API.md API.md \
    "Issuarr web API" \
    "The Issuarr web API, compatible with Mylar3 scripts and apps: keys, commands and responses."
page docs/TROUBLESHOOTING.md TROUBLESHOOTING.md \
    "Troubleshooting Issuarr" \
    "Fixes for common Issuarr problems, including database is locked errors, moved paths and direct-download issues."

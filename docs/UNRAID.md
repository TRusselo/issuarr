# Installing Issuarr on Unraid

Issuarr has an Unraid template in this repository, [`unraid/issuarr.xml`](https://github.com/issuarr/issuarr/blob/main/unraid/issuarr.xml). It runs the `ghcr.io/issuarr/issuarr:latest` image with the usual Unraid defaults (user `99`, group `100`, appdata under `/mnt/user/appdata`).

## Add the template

1. Open a terminal on the server (**>_** in the top-right of the web UI) and download the template into your user templates folder:

    ```sh
    wget -O /boot/config/plugins/dockerMan/templates-user/my-issuarr.xml \
      https://raw.githubusercontent.com/issuarr/issuarr/main/unraid/issuarr.xml
    ```

2. Go to **Docker > Add Container** and choose **issuarr** from the **Template** list.
3. Fill in the paths (see below) and click **Apply**.
4. Open the web UI from the container's icon, or at `http://<your-server>:8090`, and follow [Getting started](https://issuarr.github.io/issuarr/#getting-started).

## Paths and settings

| Setting | Container path | What to put there |
|---|---|---|
| Appdata | `/config` | Settings, database and cover cache. Defaults to `/mnt/user/appdata/issuarr`. |
| Comics | `/comics` | Your comic library share, e.g. `/mnt/user/comics/`. Set **Settings > General > Comic folder** to `/comics`. |
| Downloads | `/downloads` | The folder your download client puts finished downloads in. |
| WebUI | `8090` | The port for the web interface. |
| PUID / PGID | | `99` / `100` (nobody / users) unless your shares use another owner. |
| UMASK | | `022` by default. |

Unraid sets the container's time zone (`TZ`) from **Settings > Date and Time** on its own.

### Where to keep Appdata

Issuarr's database is fastest on a local filesystem, where it can use SQLite's WAL mode. Unraid's `/mnt/user` paths normally go through its FUSE layer (`shfs`), where WAL isn't safe, so Issuarr falls back to the slower rollback journal there. Both work; WAL just means fewer "database is locked" waits.

To get WAL, point Appdata at a pool or disk path instead, such as `/mnt/cache/appdata/issuarr` (use your pool's name if it isn't `cache`). If your appdata share is set to **Exclusive access** (Unraid 6.12 and later), `/mnt/user/appdata` skips FUSE and is fine as it is.

The log tells you which mode Issuarr picked at startup (`[DB] Journal mode ...`). More on this in [Database is locked](TROUBLESHOOTING.md#database-is-locked).

## Coming from Mylar3 on Unraid

Your Mylar3 settings and database carry over. Either way below, keep the Comics and Downloads paths **at the same container paths** as before, because Mylar stored full paths in its database.

- **Switch the existing container:** stop it, click its icon, choose **Edit**, change **Repository** to `ghcr.io/issuarr/issuarr:latest` and click **Apply**. Optionally rename it to `issuarr`.
- **Use the Issuarr template:** stop the Mylar3 container, add Issuarr as above and set Appdata to your old Mylar3 folder (for example `/mnt/user/appdata/mylar3`), with the same Comics and Downloads mappings. Remove the Mylar3 container once Issuarr is working.

See [Moving from Mylar3 to Issuarr](MIGRATING.md) for what to check afterwards.

## Updates

The template follows the `latest` tag, which is rebuilt whenever Issuarr's main branch changes. Unraid shows **update ready** on the Docker tab when a new image is out; click it to update.

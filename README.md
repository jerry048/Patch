# Patch
These are patches for compiling qBittorrent & libtorrent

Best to be used with [userdocs' qbittorrent-nox-static script](https://github.com/userdocs/qbittorrent-nox-static)

The libtorrent patch is also compatible with [Swizzin](https://github.com/swizzin/swizzin) but would require renaming. Please refer to their [Docs](https://swizzin.ltd/applications/deluge/#libtorrent-patching) for instructions.

## New release patches

| Project | Upstream tag | Patch |
| --- | --- | --- |
| libtorrent | `v2.0.15` | [2.0.15](patches/libtorrent/2.0.15/patch) |
| libtorrent | `v2.1.2` | [2.1.2](patches/libtorrent/2.1.2/patch) |
| qBittorrent | `release-5.2.4` | [5.2.4](patches/qbittorrent/5.2.4/patch) |
| qBittorrent | `release-5.3.0` | [5.3.0](patches/qbittorrent/5.3.0/patch) |

Apply each patch from the root of its matching upstream source checkout, before
building. For example, from the libtorrent `v2.1.2` checkout:

```sh
git apply --check /absolute/path/to/Patch/patches/libtorrent/2.1.2/patch
git apply /absolute/path/to/Patch/patches/libtorrent/2.1.2/patch
```

Apply the matching qBittorrent patch in its own source checkout too; patching
libtorrent alone does not prevent qBittorrent from replacing its defaults.

### Default alignment

Both libtorrent patches carry forward the 50 settings tuned by the existing
2.0.13 patch, with one deliberate change: the disk queue is now **250 MiB**
(`262144000` bytes) instead of 10 MiB. This raises the upstream defaults of
1 MiB in libtorrent 2.0.15 and 100 MiB in libtorrent 2.1.2 to the same value.

The qBittorrent patches carry forward the existing 5.2.2 tuning, with these
additional corrections so fresh-profile defaults agree with patched libtorrent:

| qBittorrent setting | New default | libtorrent setting |
| --- | --- | --- |
| `DiskQueueSize` | 250 MiB with either libtorrent version | `max_queued_disk_bytes` |
| `MaxOutstandingBlockRequests` (new in 5.3.0) | 10,000 instead of 2,000 | `max_allowed_in_request_queue` |
| `SocketBacklogSize` | 3,000, not the older patch's 30,000 | `listen_queue_size` |
| `MaxConnections` | 500,000, not the older patch's unlimited value | `connections_limit` |
| `Network/PortForwardingEnabled` | `false` | `enable_upnp` / `enable_natpmp` |

5.2.4 does not set `max_allowed_in_request_queue`, so it inherits 10,000 directly
from patched libtorrent. Other new 5.3.0 controls (seeding outgoing connections,
multiple connections per peer ID, I2P length variance, NAT-PMP lease duration and
WebTorrent STUN server) do not conflict with settings modified by these patches.
Existing matching defaults, including TCP mixed mode and fastest-upload seed
choking, are retained. Unit conversions are respected: 128 MiB checking memory
corresponds to 8,192 libtorrent blocks, and send-buffer watermarks use KiB in
qBittorrent but bytes in libtorrent.

These are **fallback defaults**, not forced overrides. Explicit settings already
saved in a profile (including upstream defaults persisted by an earlier version)
still take precedence. To adopt the new defaults, review/reset the corresponding
settings or test with a fresh profile; no existing configuration is rewritten.

**Security:** Like the existing qBittorrent patch, these patches disable WebUI
CSRF protection by default. Re-enable it for an exposed WebUI. The 5.3.0 patch
uses the renamed `WebUI/CSRFProtection` key; 5.2.4 uses
`Preferences/WebUI/CSRFProtection`.

### Validation

With clean upstream Git checkouts named `libtorrent-2.0.15`, `libtorrent-2.1.2`,
`qbittorrent-5.2.4` and `qbittorrent-5.3.0` under one source directory, run:

```sh
python tests/validate_patches.py /absolute/path/to/source-directory
```

The test checks the release tags, applies/reverse-checks all four patches in
temporary repositories, verifies all 50 libtorrent tuning values, and statically
compares qBittorrent defaults against both libtorrent versions. It also rejects
unreviewed assignments to patched settings. Source checkouts are not modified.
Use `--scratch-dir PATH` to choose where temporary test repositories are created.

Validation covers patch application and source-level default alignment, **not
compilation or runtime performance**. In particular, checking defaults for all
four version combinations does not prove upstream API/build compatibility.

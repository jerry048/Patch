"""Check release patches and statically audit qBittorrent's fresh-profile defaults.

Requires Python 3 and Git, not Qt or a compiled libtorrent. Source directories
must be named libtorrent-2.0.15, libtorrent-2.1.2, qbittorrent-5.2.4 and
qbittorrent-5.3.0, each checked out at its corresponding upstream release tag.
No upstream working-tree files are modified.
"""

import argparse
import ast
import operator
from pathlib import Path
import re
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
RELEASES = {
    "libtorrent": ("2.0.15", "2.1.2"),
    "qbittorrent": ("5.2.4", "5.3.0"),
}
SESSION = "src/base/bittorrent/sessionimpl.cpp"
FORWARDER = "src/base/bittorrent/portforwarderimpl.cpp"
PREFERENCES = "src/base/preferences.cpp"

# libtorrent setting: (qBittorrent configuration key, unit conversion).
SCALARS = {
    "enable_dht": ("DHTEnabled", 1),
    "enable_lsd": ("LSDEnabled", 1),
    "aio_threads": ("AsyncIOThreadsCount", 1),
    "hashing_threads": ("HashingThreadsCount", 1),
    "file_pool_size": ("FilePoolSize", 1),
    "checking_mem_usage": ("CheckingMemUsageSize", 64),
    "max_queued_disk_bytes": ("DiskQueueSize", 1),
    "send_buffer_watermark": ("SendBufferWatermark", 1024),
    "send_buffer_low_watermark": ("SendBufferLowWatermark", 1024),
    "send_buffer_watermark_factor": ("SendBufferWatermarkFactor", 1),
    "connection_speed": ("ConnectionSpeed", 1),
    "listen_queue_size": ("SocketBacklogSize", 1),
    "peer_dscp": ("PeerToS", 1),
    "max_concurrent_http_announces": ("MaxConcurrentHTTPAnnounces", 1),
    "connections_limit": ("MaxConnections", 1),
    "unchoke_slots_limit": ("MaxUploads", 1),
    "allow_multiple_connections_per_ip": ("MultiConnectionsPerIp", 1),
    "max_out_request_queue": ("RequestQueueSize", 1),
    "max_allowed_in_request_queue": ("MaxOutstandingBlockRequests", 1),
}
SPECIAL = {
    "enable_upnp", "enable_natpmp", "enable_incoming_utp", "enable_outgoing_utp",
    "active_downloads", "active_seeds", "active_limit", "suggest_mode",
    "mixed_mode_algorithm", "seed_choking_algorithm",
}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def git(directory, *args):
    return subprocess.check_output(
        ["git", "-C", str(directory), *args], stderr=subprocess.STDOUT
    ).decode("utf-8")


def value(expression):
    """Evaluate only the numeric/boolean arithmetic used by these defaults."""
    if expression in ("true", "false"):
        return expression == "true"

    def walk(node):
        if isinstance(node, ast.Constant) and type(node.value) is int:
            return node.value
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -walk(node.operand)
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mult)):
            operation = operator.add if isinstance(node.op, ast.Add) else operator.mul
            return operation(walk(node.left), walk(node.right))
        raise RuntimeError(f"Unsupported default expression: {expression}")

    return walk(ast.parse(expression, mode="eval").body)


def lt_defaults(text):
    return dict(re.findall(r"\bSET\((\w+), ([^,\n]+),", text))


def patched_sources(source_root, project, version, scratch):
    source = source_root / f"{project}-{version}"
    tag = f"v{version}" if project == "libtorrent" else f"release-{version}"
    require(git(source, "rev-parse", "HEAD").strip()
            == git(source, "rev-parse", f"{tag}^{{commit}}").strip(),
            f"{source} is not at {tag}")
    patch = ROOT / "patches" / project / version / "patch"
    text = patch.read_text(encoding="utf-8")
    files = re.findall(r"^--- a/(.+)$", text, re.M)
    require(bool(files), f"Empty patch: {patch}")
    destination = scratch / f"{project}-{version}"
    destination.mkdir()
    # A separate repository prevents Git from discovering a parent repository.
    git(destination, "init", "--quiet")
    for name in files:
        original = git(source, "show", f"{tag}:{name}")
        require((source / name).read_text(encoding="utf-8") == original,
                f"Modified upstream source: {source / name}")
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(original.encode("utf-8"))
    git(destination, "apply", "--check", "--whitespace=error-all", str(patch))
    git(destination, "apply", "--whitespace=error-all", str(patch))
    git(destination, "apply", "--reverse", "--check", str(patch))
    return {name: (destination / name).read_text(encoding="utf-8") for name in files}


def audit_qbt(files, version, defaults, tuned):
    session = files[SESSION]
    constructor = session.split("SessionImpl::SessionImpl(QObject *parent)", 1)[1]
    # The constructor's initializer list ends before this common statement.
    constructor = constructor.split("m_asyncWorker->setMaxThreadCount", 1)[0]
    entries = re.findall(
        r'BITTORRENT_SESSION_KEY\(u"(\w+)"_s\), '
        r'(\([^()]*\)|-?0x[0-9a-fA-F]+|-?\d+|true|false|\w+::\w+)',
        constructor,
    )
    # libtorrent 2.x is the first arm of the file-pool conditional.
    settings = {}
    for key, expression in entries:
        settings.setdefault(key, expression)
    require([v for k, v in entries if k == "FilePoolSize"] == ["100", "5000"],
            "File-pool defaults must keep the libtorrent 2.x/1.2 conditional")
    require(len([k for k, _ in entries if k == "DiskQueueSize"]) == 1,
            "Disk queue must use the tuned default with both libtorrent branches")
    written = set(re.findall(r"set_(?:int|bool)\(lt::settings_pack::(\w+),", session))
    require(not ((written & tuned) - SCALARS.keys() - SPECIAL),
            f"Unreviewed overridden settings: {(written & tuned) - SCALARS.keys() - SPECIAL}")
    for name, (key, scale) in SCALARS.items():
        if name not in written:
            require(version == "5.2.4" and name == "max_allowed_in_request_queue",
                    f"Missing expected libtorrent assignment: {name}")
            continue  # 5.2.4 inherits this value directly from libtorrent.
        require(key in settings, f"Missing qBittorrent default: {key}")
        require(value(settings[key]) * scale == value(defaults[name]),
                f"{version}: {key} overrides patched {name}")
    for key, expected in {
        "PeXEnabled": "false", "QueueingSystemEnabled": "false",
        "SuggestMode": "true", "BTProtocol": "BTProtocol::TCP",
        "uTPMixedMode": "MixedModeAlgorithm::TCP",
        "SeedChokingAlgorithm": "SeedChokingAlgorithm::FastestUpload",
        "MaxConnectionsPerTorrent": "-1", "MaxUploadsPerTorrent": "-1",
    }.items():
        require(settings.get(key) == expected, f"{version}: unexpected {key} default")
    for name in ("active_downloads", "active_seeds", "active_limit"):
        require(f"settingsPack.set_int(lt::settings_pack::{name}, -1);" in session,
                f"Queueing-disabled path no longer preserves {name}")
    require('m_storeActive {u"Network/PortForwardingEnabled"_s, false}' in files[FORWARDER],
            "Port forwarding would re-enable patched UPnP/NAT-PMP defaults")
    key = "Preferences/WebUI/CSRFProtection" if version == "5.2.4" else "WebUI/CSRFProtection"
    require(f'return value(u"{key}"_s, false);' in files[PREFERENCES],
            "Legacy CSRF default was not ported to the current configuration key")
    require("m_port = Utils::Random::rand(15000, 65535);" in session,
            "Legacy random listening-port range was not preserved")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path)
    parser.add_argument("--scratch-dir", type=Path, help="Parent for temporary test repositories")
    args = parser.parse_args()
    legacy = (ROOT / "patches/libtorrent/2.0.13/patch").read_text(encoding="utf-8")
    expected = lt_defaults("\n".join(line[1:] for line in legacy.splitlines() if line.startswith("+")))
    require(len(expected) == 50, "Unexpected legacy tuning baseline")
    # Deliberate change from the legacy tuning: use 250 MiB with every release.
    expected["max_queued_disk_bytes"] = "262144000"
    with tempfile.TemporaryDirectory(prefix="patch-validation-", dir=args.scratch_dir) as tmp:
        patched = {}
        for project, versions in RELEASES.items():
            for version in versions:
                patched[project, version] = patched_sources(
                    args.source_root.resolve(), project, version, Path(tmp))
                print(f"PASS apply/reverse: {project} {version}")
        for lt_version in RELEASES["libtorrent"]:
            defaults = lt_defaults(patched["libtorrent", lt_version]["src/settings_pack.cpp"])
            for key, expression in expected.items():
                require(defaults.get(key) == expression,
                        f"libtorrent {lt_version}: unexpected tuning for {key}")
            for qbt_version in RELEASES["qbittorrent"]:
                audit_qbt(patched["qbittorrent", qbt_version], qbt_version, defaults, set(expected))
                print(f"PASS static defaults: qBittorrent {qbt_version} / libtorrent {lt_version}")
    print("All patch checks passed (not a compilation or runtime test).")


if __name__ == "__main__":
    main()

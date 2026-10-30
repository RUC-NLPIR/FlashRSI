"""Resolve pinned FlashRSI Hub packages into existing benchmark inputs.

Prepared Parquet files are records or indexes, not replacement environments.
Native resources stay in the host cache, outside evolvable harness Snapshots.
"""

import ast
import copy
import hashlib
import io
import json
import os
import re
import tarfile
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from filelock import FileLock
from huggingface_hub import constants, hf_hub_download

from flashrsi._hf import (
    ALIASES,
    LEGACY_REVISIONS,
    PROFILES,
    REPO,
)
from flashrsi._hf import (
    BENCHMARKS as BENCHMARKS,
)
from flashrsi._hf import (
    REVISION as REVISION,
)
from flashrsi._hf import (
    selected as selected,
)
from flashrsi.benchmarks._archive import _extract, _is_safe


def prepare(config):
    """Return run-local paths and verified membership; do not mutate the YAML."""
    config = copy.deepcopy(dict(config))
    name, source = config["name"], config["dataset"]
    profile = ALIASES.get(source.get("config"), source.get("config"))
    if profile not in PROFILES or PROFILES[profile][0] != name:
        raise ValueError("Prepared dataset.config must match a supported benchmark")
    for option, value in PROFILES[profile][1].items():
        configured = config.get(option, value)
        if name == "livemathbench" and option == "version":
            configured = str(configured)
        if configured != value:
            raise ValueError(
                f"Prepared dataset.config must match benchmark.{option}: {value}"
            )
        config[option] = copy.deepcopy(value)
    if name == "aime" and "year" in config:
        raise ValueError("Prepared AIME uses 2025 train/dev and 2026 test; omit year")
    revision = source.get("revision")
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Prepared dataset.revision must be an immutable HF commit")
    if config.get("split", "auto") != "auto" or config.get("split_counts") is not None:
        raise ValueError(
            "Prepared datasets preserve split_ids; use split: auto, without split_counts"
        )
    if config.get("data_path") is not None or any(
        k.startswith("evolution_") for k in config
    ):
        raise ValueError(
            "Prepared datasets cannot be combined with data_path or evolution_* overrides"
        )
    if name == "terminal_bench" and str(config.get("version", "2.0")) != "2.0":
        raise ValueError(
            "This prepared Terminal-Bench release contains version 2.0, not 2.1"
        )
    if name == "spreadsheetbench2" and config.get("category", "all") != "all":
        raise ValueError("Prepared SpreadsheetBench2 membership requires category: all")
    download = {"repo_id": REPO, "repo_type": "dataset", "revision": revision}
    if revision in LEGACY_REVISIONS:
        package = f"tau2_{config.get('domain', 'telecom')}" if name == "tau2" else name
        release = (
            "20261030-batch2"
            if name
            in {"alfworld", "math", "tau2", "travelplanner", "twowiki_multihopqa"}
            else "20261030"
        )
        prefix = f"prepared/{release}/{package}"
    elif profile == "searchqa":
        prefix, package = "searchqa", "searchqa"
    else:
        catalog = json.loads(
            Path(
                hf_hub_download(filename="metadata/catalog.json", **download)
            ).read_text(encoding="utf-8")
        )
        if catalog.get("layout") != "benchmark-directories.v1":
            raise ValueError("Unsupported HF prepared catalog layout")
        entries = [
            entry
            for entry in catalog["configurations"]
            if entry["name"] == profile and entry["kind"] == "experiment"
        ]
        if len(entries) != 1 or not _is_safe(entries[0]["directory"]):
            raise ValueError(
                "Requested HF experiment profile is not in the pinned catalog"
            )
        prefix = entries[0]["directory"]
        package = None
    manifest = json.loads(
        Path(hf_hub_download(filename=prefix + "/manifest.json", **download)).read_text(
            encoding="utf-8"
        )
    )
    if profile == "searchqa":
        return _searchqa(config, source, manifest, download)
    if manifest.get("schema") != "flashrsi.prepared-dataset.v1" or (
        package is not None
        and manifest.get("benchmark") != package
        or package is None
        and (
            manifest.get("config_name") != profile
            or manifest.get("directory") != prefix
        )
    ):
        raise ValueError("Prepared manifest does not match the requested benchmark")

    def entry(relative):
        return manifest["files"][
            relative if relative in manifest["files"] else "native/" + relative
        ]

    def get(relative):
        if not _is_safe(relative):
            raise ValueError("Unsafe prepared resource path")
        filename = relative if relative in manifest["files"] else "native/" + relative
        path = Path(hf_hub_download(filename=prefix + "/" + filename, **download))
        _verify(path, entry(relative))
        return path

    splits = json.loads(get("split_ids.json").read_text(encoding="utf-8"))
    if not isinstance(splits, dict) or set(splits) != {"train", "dev", "test"}:
        raise ValueError("Prepared split_ids must declare train/dev/test")
    ids = []
    for role, values in splits.items():
        if (
            not isinstance(values, list)
            or len(values) != manifest["counts"][role]
            or any(not isinstance(v, str) or not v for v in values)
        ):
            raise ValueError("Prepared split membership/count mismatch")
        ids.extend(values)
    if len(ids) != len(set(ids)):
        raise ValueError("Prepared split IDs overlap or contain duplicates")
    config.pop("dataset")
    config["_prepared_splits"] = splits
    config["_prepared_source"] = {
        "source": REPO,
        "revision": revision,
        "config": source["config"],
        "path": prefix,
        "source_details": manifest["source"],
        "split_policy": manifest["split_policy"],
        "counts": manifest["counts"],
    }
    config["data_path"] = {role: str(get(role + ".parquet")) for role in splits}

    if name in {"nq", "triviaqa"}:
        config["_prepared_mrqa"] = True
        if config.get("scoring", "text_em_f1") != "text_em_f1":
            raise ValueError("Prepared MRQA data requires scoring: text_em_f1")
        config["scoring"] = "text_em_f1"
    elif name in {
        "alfworld",
        "tau2",
        "terminal_bench",
        "tau3_banking",
        "workbench",
        "bfcl",
    }:
        archive = {
            "alfworld": "experiment-native.tar.gz",
            "tau2": "native-resources.tar.gz",
            "terminal_bench": "upstream/tasks.tar.gz",
            "tau3_banking": "upstream/domain.tar.gz",
            "workbench": "native.tar.gz",
            "bfcl": "native.tar.gz",
        }[name]
        path = get(archive)
        root = unpack(path, entry(archive)["sha256"])
        config["data_path"] = str(root)
        if name == "alfworld":
            roots = [
                p.parent
                for p in root.rglob("train")
                if p.is_dir()
                and (p.parent / "valid_seen").is_dir()
                and (p.parent / "valid_unseen").is_dir()
            ]
            if len(roots) != 1:
                raise ValueError(
                    "Prepared ALFWorld archive must contain one native train/valid_seen/valid_unseen root"
                )
            config["data_path"] = str(roots[0])
        elif name == "tau2":
            config["data_path"] = str(
                root / "data/tau2/domains" / config.get("domain", "telecom")
            )
            config["_prepared_user_simulator"] = _user_simulator(root)
        elif name == "terminal_bench":
            task_roots = {
                p.parent.parent for p in root.rglob("task.toml") if p.parent.name in ids
            }
            if len(task_roots) != 1:
                raise ValueError(
                    "Prepared Terminal-Bench tasks must share one directory"
                )
            config["data_path"] = str(task_roots.pop())
        elif name == "workbench":
            config["_prepared_root"] = str(root)
            config["data_path"] = str(root / "data")
        elif name == "bfcl":
            config["_prepared_archive"] = {
                "path": str(path),
                **entry(archive),
            }
        elif name == "tau3_banking":
            domains = [
                p.parent for p in root.rglob("db.json") if (p.parent / "tasks").is_dir()
            ]
            if len(domains) != 1:
                raise ValueError(
                    "Prepared banking archive must contain one native task/database domain"
                )
            config["data_path"] = str(domains[0])
            simulator = unpack(
                get("user_simulator.tar.gz"),
                entry("user_simulator.tar.gz")["sha256"],
            )
            config["_prepared_user_simulator"] = _user_simulator(simulator)
    elif name == "travelplanner":
        root = unpack(get("database.tar.gz"), entry("database.tar.gz")["sha256"])
        config["database_path"] = str(
            root / "database" if (root / "database").is_dir() else root
        )
    elif name == "officeqa_pro":
        root = unpack(get("corpus.tar.gz"), entry("corpus.tar.gz")["sha256"])
        config["corpus_path"] = str(root)
    elif name == "spreadsheetbench2":
        reverse = {
            f"{task_id.split('/')[0].lower().replace('_', '-')}-{task_id.split('/')[1]}": task_id
            for task_id in ids
        }
        config["_prepared_ids"] = reverse
        config["_prepared_splits"] = {
            role: [
                next(k for k, v in reverse.items() if v == task_id)
                for task_id in values
            ]
            for role, values in splits.items()
        }
        code = {}
        for relative in (
            "evaluation/evaluation.py",
            "evaluation/open_spreadsheet.py",
            "SWE-agent/spreadsheet.Dockerfile",
        ):
            code[relative] = str(get("upstream/code/" + relative))
        config.pop("data_path")
        config["_prepared_spreadsheet"] = {
            "archive": str(get("upstream/spreadsheetbench-v2-09-10.zip")),
            "code": code,
        }
    elif name == "appworld":
        bundle = get("data-0.1.0.bundle")
        wheel = get("runtime/appworld-0.1.3.post1-py3-none-any.whl")
        config["data_path"] = str(
            _appworld(bundle, wheel, entry("data-0.1.0.bundle")["sha256"])
        )
    elif name in {"deepswe", "swe_bench_pro", "harvey_lab", "jobbench"}:
        archive = "native/experiment-native.tar.gz"
        path = get(archive)
        root = unpack(path, entry(archive)["sha256"])
        if name == "harvey_lab":
            config["data_path"] = str(root)
        else:
            parents = {p.parent.parent for p in root.rglob("task.toml")}
            if len(parents) != 1:
                raise ValueError(
                    "Prepared Harbor tasks must share one native directory"
                )
            config["data_path"] = str(parents.pop())
    elif name == "widesearch":
        archive = "native/native-source.tar.gz"
        root = unpack(get(archive), entry(archive)["sha256"])
        gold = [p for p in root.rglob("widesearch_gold") if p.is_dir()]
        if len(gold) != 1:
            raise ValueError(
                "Prepared WideSearch requires one native gold CSV directory"
            )
        config["gold_path"] = str(gold[0])
    return config


def _searchqa(config, source, manifest, download):
    """Keep the original SkillOpt subset's published roles and manifest format."""
    import pyarrow.parquet as pq

    if manifest.get("schema") != "flashrsi.searchqa.v1":
        raise ValueError("Prepared SearchQA requires its native subset manifest")
    splits, paths = {}, {}
    for role in ("train", "dev", "test"):
        entry = manifest["splits"][role]
        if entry["file"] != f"searchqa/{role}.parquet":
            raise ValueError("Unexpected SearchQA subset path")
        path = Path(hf_hub_download(filename=entry["file"], **download))
        _verify(path, entry)
        ids = pq.read_table(path, columns=["id"]).column("id").to_pylist()
        if len(ids) != entry["count"] or any(
            not isinstance(i, str) or not i for i in ids
        ):
            raise ValueError("SearchQA subset ID/count mismatch")
        splits[role], paths[role] = ids, str(path)
    ids = [i for values in splits.values() for i in values]
    if len(ids) != len(set(ids)):
        raise ValueError("SearchQA subset IDs overlap or contain duplicates")
    config.pop("dataset")
    config.update(
        data_path=paths,
        _prepared_splits=splits,
        _prepared_source={
            "source": REPO,
            "revision": source["revision"],
            "config": source["config"],
            "path": "searchqa",
            "source_details": manifest["source"],
            "split_policy": manifest["notes"]["subset"],
            "counts": {r: len(v) for r, v in splits.items()},
        },
    )
    return config


def _user_simulator(root):
    guidelines = list(root.rglob("simulation_guidelines.md"))
    if (
        len(guidelines) != 1
        or not guidelines[0].with_name("simulation_guidelines_tools.md").is_file()
    ):
        raise ValueError("Prepared tau user simulator guidelines are incomplete")
    return str(guidelines[0].parent)


def _verify(path, entry):
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if path.stat().st_size != entry["bytes"] or digest != entry["sha256"]:
        raise ValueError(f"Prepared resource checksum/size mismatch: {path.name}")


def unpack(path, digest):
    cache = _cache()
    destination = cache / digest
    with FileLock(str(destination) + ".lock"):
        if not destination.exists():
            with tarfile.open(path, "r:gz") as archive:
                roots = {
                    PurePosixPath(member.name).parts[0]
                    for member in archive
                    if member.name
                }
            with TemporaryDirectory(prefix=".extract-", dir=cache) as temporary:
                extracted = Path(temporary) / "data"
                extracted.mkdir()
                _extract(
                    path, extracted, [{"path": root} for root in roots], "prepared"
                )
                extracted.rename(destination)
    return destination


def _cache():
    cache = (Path(constants.HF_HOME) / "flashrsi/prepared").resolve()
    # Native archives contain long filenames. Windows' extended namespace keeps
    # these readable even when HF_HOME is inside a deeply nested workspace.
    if os.name == "nt" and not str(cache).startswith("\\\\?\\"):
        path = str(cache)
        cache = Path(
            "\\\\?\\UNC\\" + path[2:] if path.startswith("\\\\") else "\\\\?\\" + path
        )
    cache.mkdir(parents=True, exist_ok=True)
    return cache


def verify_native(root, proof):
    """A pinned HF archive replaces BFCL's Git object transport, not its code."""
    path = Path(proof["path"])
    _verify(path, proof)
    expected = set()
    with tarfile.open(path, "r:gz") as archive:
        for member in archive:
            if member.isdir():
                continue
            if not member.isfile() or not _is_safe(member.name):
                raise ValueError("Unsafe prepared native source")
            target = root.joinpath(*PurePosixPath(member.name).parts)
            expected.add(target)
            if (
                target.is_symlink()
                or not target.is_file()
                or target.read_bytes() != archive.extractfile(member).read()
            ):
                raise ValueError("Prepared native source changed after extraction")
    if any(p not in expected for p in root.rglob("*.py")):
        raise ValueError("Prepared native source has unexpected Python files")
    return proof["sha256"]


def _appworld(bundle, wheel, digest):
    """Read the official 0.1.0 AES-CFB bundle format; never redistribute plaintext.

    Format: appworld 0.1.3.post1 common/utils.py (Apache-2.0), matching the
    release's verified wheel. Public format constants come from that same wheel.
    """
    try:
        from cryptography.hazmat.decrepit.ciphers.modes import CFB
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    except ImportError:
        raise ValueError(
            "Prepared AppWorld data requires flashrsi-lite[appworld]"
        ) from None
    cache = _cache()
    destination = cache / digest
    with FileLock(str(destination) + ".lock"):
        if not destination.exists():
            with ZipFile(wheel) as archive:
                tree = ast.parse(archive.read("appworld/common/constants.py"))
            values = {
                node.targets[0].id: ast.literal_eval(node.value)
                for node in tree.body
                if isinstance(node, ast.Assign)
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id in {"PASSWORD", "SALT"}
            }
            key = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=values["SALT"],
                iterations=100000,
            ).derive(values["PASSWORD"].encode())
            data = bundle.read_bytes()
            decryptor = Cipher(algorithms.AES(key), CFB(data[:16])).decryptor()
            decrypted = decryptor.update(data[16:]) + decryptor.finalize()
            with TemporaryDirectory(prefix=".appworld-", dir=cache) as temporary:
                root = Path(temporary)
                with ZipFile(io.BytesIO(decrypted)) as archive:
                    for member in archive.infolist():
                        name = member.filename.rstrip("/")
                        if (
                            not _is_safe(name)
                            or member.external_attr >> 16 & 0o170000 == 0o120000
                        ):
                            raise ValueError("Unsafe AppWorld bundle path")
                    archive.extractall(root)
                if not (root / "data/datasets").is_dir():
                    raise ValueError("AppWorld bundle does not contain native data")
                root.rename(destination)
    return destination / "data"

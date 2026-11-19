#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""The content-addressed store under hw/.cad/cache/, and layout's input_key, code_shas and tool_versions."""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import threading
import types
import unittest
from collections.abc import Iterator
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load(name: str, filename: str):
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
        assert spec and spec.loader
        sys.modules[name] = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sys.modules[name])
    return sys.modules[name]


layout = _load("cad_record_layout", "layout.py")
store = _load("cad_record_store", "store.py")
TICK_NS = 2_000_000_000  # the racy window: FAT stamps mtime in 2 s steps, the coarsest clock the store allows for


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def key(name: str) -> str:
    """A store key for a test: any sha256."""
    return sha(name.encode())


class Fixture(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="cad-record-store-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.hw = self.root / "hw"
        self.hw.mkdir()
        self.store = store.Store(self.hw)

    def file(self, name: str, data: bytes) -> Path:
        path = self.root / "out" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def claimed(self, key: str, members: dict[str, bytes], **fields) -> dict:
        record = {"kind": "test", "members": {name: self.store.intern(self.file(name, data))
                                              for name, data in members.items()}, **fields}
        self.assertEqual(self.store.claim(key, record), "claimed")
        return record


class InputKey(unittest.TestCase):
    def test_the_key_is_the_canonical_recipe_sha_of_the_allowlisted_inputs(self) -> None:
        material = {"format": 2, "kind": "part", "inputs": {"model.py": "ab" * 32}, "kernel": "cadquery"}
        self.assertEqual(layout.input_key(material), layout.recipe_sha256(material))
        self.assertEqual(layout.input_key(material, allow=("format", "kind", "inputs", "kernel")),
                         layout.recipe_sha256(material))

    def test_a_key_needs_its_format_and_kind_and_only_allowlisted_inputs(self) -> None:
        for material in ({"kind": "part"}, {"format": 1}, {"format": 1, "kind": ""}):
            with self.subTest(material=material), self.assertRaises(ValueError):
                layout.input_key(material)
        with self.assertRaisesRegex(ValueError, "build_s"):  # a timing is never a key input
            layout.input_key({"format": 1, "kind": "part", "build_s": 0.2}, allow=("format", "kind"))

    def test_code_shas_and_tool_versions_name_explicit_files_and_distributions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a.py").write_bytes(b"a")
            (root / "sub").mkdir()
            (root / "sub" / "b.py").write_bytes(b"b")
            self.assertEqual(layout.code_shas(root, ["sub/b.py", "a.py"]), {"a.py": sha(b"a"), "sub/b.py": sha(b"b")})
        versions = layout.tool_versions(("pyyaml", "no-such-distribution-x"))
        self.assertRegex(versions["pyyaml"], r"^\d+\.")
        self.assertEqual(versions["no-such-distribution-x"], "missing")


class Objects(Fixture):
    def test_an_object_is_stored_once_read_only_under_its_sha(self) -> None:
        first = self.store.intern(self.file("a.step", b"STEP"))
        second = self.store.intern(self.file("b.step", b"STEP"))
        self.assertEqual(first, second)
        self.assertEqual(first, sha(b"STEP"))
        stored = self.hw / ".cad" / "cache" / "objects" / first
        self.assertEqual(stored.read_bytes(), b"STEP")
        self.assertEqual(stored.stat().st_mode & 0o777, 0o444)
        self.assertEqual(layout.classify(stored, self.hw).entry.id, "cache.part_objects")

    def test_place_object_links_or_copies_read_only_and_misses_a_removed_object(self) -> None:
        digest = self.store.intern(self.file("a.step", b"STEP"))
        target = self.root / "run" / "a.step"
        self.assertTrue(self.store.place_object(digest, target))
        self.assertEqual((target.read_bytes(), target.stat().st_mode & 0o777), (b"STEP", 0o444))
        os.chmod(self.hw / ".cad" / "cache" / "objects" / digest, 0o644)
        (self.hw / ".cad" / "cache" / "objects" / digest).unlink()
        self.assertFalse(self.store.place_object(digest, self.root / "run" / "b.step"))
        self.assertFalse((self.root / "run" / "b.step").exists())

    def test_interning_bytes_already_stored_turns_the_output_into_a_read_only_link(self) -> None:
        digest = self.store.intern(self.file("a.step", b"STEP"))
        rebuilt = self.file("b.step", b"STEP")  # a rebuild writes equal bytes to a new, writable file
        self.assertEqual(self.store.intern(rebuilt), digest)
        self.assertTrue(os.path.samefile(rebuilt, self.hw / ".cad" / "cache" / "objects" / digest))
        self.assertEqual(rebuilt.stat().st_mode & 0o777, 0o444)

    def test_interning_after_gc_removed_an_object_this_store_checked_stores_it_again(self) -> None:
        digest = self.store.intern(self.file("a.step", b"STEP"))
        stored = self.hw / ".cad" / "cache" / "objects" / digest
        stored.unlink()  # another process's gc, after this Store checked the object
        rebuilt = self.file("b.step", b"STEP")
        self.assertEqual(self.store.intern(rebuilt), digest)
        self.assertEqual(stored.read_bytes(), b"STEP")
        self.assertTrue(os.path.samefile(rebuilt, stored))

    def test_without_hard_links_objects_and_records_are_copies_and_the_first_writer_still_wins(self) -> None:
        with mock.patch.object(store.os, "link", side_effect=OSError(1, "Operation not permitted")):
            first = self.claimed(key("n"), {"mesh.unv": b"ONE"})
            other = {"kind": "test", "members": {"mesh.unv": self.store.intern(self.file("x.unv", b"TWO"))}}
            outcome = self.store.claim(key("n"), other)
            destination = self.root / "run" / "mesh"
            placed = self.store.place(first, destination)
        self.assertRegex(outcome, "^conflict: ")
        self.assertEqual(store.Store(self.hw).record(key("n")).record["members"], first["members"])
        self.assertEqual((placed, (destination / "mesh.unv").read_bytes()), ("", b"ONE"))
        stored = self.hw / ".cad" / "cache" / "objects" / first["members"]["mesh.unv"]
        self.assertFalse(os.path.samefile(destination / "mesh.unv", stored))
        self.assertEqual((destination / "mesh.unv").stat().st_mode & 0o777, 0o444)


class Records(Fixture):
    def test_a_claimed_record_is_read_back_with_its_members(self) -> None:
        record = self.claimed(key("k"), {"mesh.unv": b"UNV", "sub/mesh.json": b"{}"}, facts={"nodes": 3})
        found = self.store.record(key("k"))
        self.assertEqual((found.reason, found.record["members"], found.record["facts"]),
                         ("", record["members"], {"nodes": 3}))
        self.assertEqual(layout.classify(self.hw / ".cad" / "cache" / "records" / f"{key('k')}.json", self.hw).entry.id,
                         "cache.part_records")

    def test_a_record_of_the_old_shape_is_a_miss_and_the_next_claim_replaces_it(self) -> None:
        record = self.claimed(key("o"), {"mesh.unv": b"UNV"})
        path = self.hw / ".cad" / "cache" / "records" / f"{key('o')}.json"
        kept = json.loads(path.read_text(encoding="utf-8"))
        old = {"format": kept["format"], "kind": "test", "objects": record["members"]}  # before members replaced objects
        path.write_text(json.dumps(old), encoding="utf-8")
        found = self.store.record(key("o"))
        self.assertIsNone(found.record)
        self.assertRegex(found.reason, r"^miss: a record needs members")
        self.assertRegex(self.store.claim(key("o"), record), r"^replaced: miss: a record needs members")
        self.assertEqual(self.store.record(key("o")).record["members"], record["members"])

    def test_a_missing_record_is_a_miss_and_a_changed_object_is_stale_with_its_reason(self) -> None:
        self.assertTrue(self.store.record(key("m")).reason.startswith("miss"))
        record = self.claimed(key("s"), {"mesh.unv": b"UNV"})
        path = self.hw / ".cad" / "cache" / "objects" / record["members"]["mesh.unv"]
        os.chmod(path, 0o644)
        path.write_bytes(b"CHANGED")  # an accidental in-place write
        found = store.Store(self.hw).record(key("s"))
        self.assertIsNone(found.record)
        self.assertRegex(found.reason, r"^stale: mesh\.unv .* does not hash to its name")

    def test_an_object_edited_in_place_after_this_store_checked_it_is_never_published(self) -> None:
        edits = {"a write of another size": (b"UNV", b"EDITED", False),
                 "a same-size write whose mtime is put back (#245)": (b"VNU", b"XYZ", True)}
        for number, (case, (data, edited, mtime_put_back)) in enumerate(edits.items()):
            with self.subTest(case):
                record = self.claimed(key(f"i{number}"), {"mesh.unv": data})
                self.assertIsNotNone(self.store.record(key(f"i{number}")).record)  # this Store has checked the object
                path = self.hw / ".cad" / "cache" / "objects" / record["members"]["mesh.unv"]
                os.chmod(path, 0o644)
                checked = os.stat(path)
                path.write_bytes(edited)  # an honest mistake: a tool writes through the object
                if mtime_put_back:  # what a rewrite within one tick of a coarse timestamp clock leaves
                    os.utime(path, ns=(checked.st_atime_ns, checked.st_mtime_ns))
                self.assertRegex(self.store.record(key(f"i{number}")).reason, r"^stale: mesh\.unv ")
                destination = self.root / f"run{number}" / "mesh"
                self.assertRegex(self.store.place(record, destination), r"^stale: mesh\.unv ")
                self.assertFalse(destination.exists())
                self.assertFalse(self.store.place_object(record["members"]["mesh.unv"], destination.with_name("one.unv")))
                self.assertFalse(destination.with_name("one.unv").exists())

    def test_the_first_writer_of_a_key_wins_and_a_different_second_record_is_a_finding(self) -> None:
        first = self.claimed(key("w"), {"mesh.unv": b"ONE"})
        same = {"kind": "test", "members": dict(first["members"])}
        self.assertEqual(self.store.claim(key("w"), same), "exists")
        other = {"kind": "test", "members": {"mesh.unv": self.store.intern(self.file("x.unv", b"TWO"))}}
        outcome = self.store.claim(key("w"), other)
        self.assertRegex(outcome, r"^conflict: .*mesh\.unv.*the key is missing an input")
        self.assertEqual(self.store.record(key("w")).record["members"], first["members"])
        findings = (self.hw / ".cad" / "cache" / "findings.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(json.loads(findings[-1])["key"], key("w"))

    def test_concurrent_writers_of_one_key_leave_exactly_one_record(self) -> None:
        records = [{"kind": "test", "members": {"m": self.store.intern(self.file(f"{i}", str(i).encode()))}}
                   for i in range(8)]
        outcomes: list[str] = []
        threads = [threading.Thread(target=lambda r=r: outcomes.append(store.Store(self.hw).claim(key("c"), r)))
                   for r in records]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(outcomes.count("claimed"), 1)
        self.assertEqual(sum(o.startswith("conflict") for o in outcomes), 7)

    def test_a_stale_record_gives_way_to_the_next_claim(self) -> None:
        old = self.claimed(key("r"), {"mesh.unv": b"OLD"})
        stored = self.hw / ".cad" / "cache" / "objects" / old["members"]["mesh.unv"]
        stored.unlink()  # gc, or a hand, removed the record's object
        fresh = {"kind": "test", "members": {"mesh.unv": self.store.intern(self.file("n.unv", b"NEW"))}}
        self.assertRegex(store.Store(self.hw).claim(key("r"), fresh), r"^replaced: stale: mesh\.unv ")
        self.assertEqual(store.Store(self.hw).record(key("r")).record["members"], fresh["members"])

    def test_concurrent_claimers_of_a_stale_key_leave_one_replacement_and_log_the_rest(self) -> None:
        old = self.claimed(key("q"), {"mesh.unv": b"OLD"})
        (self.hw / ".cad" / "cache" / "objects" / old["members"]["mesh.unv"]).unlink()
        records = [{"kind": "test", "members": {"m": self.store.intern(self.file(f"{i}", str(i).encode()))}}
                   for i in range(8)]
        outcomes: dict[int, str] = {}
        threads = [threading.Thread(target=lambda i=i: outcomes.update({i: store.Store(self.hw).claim(key("q"), records[i])}))
                   for i in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        winners = [i for i, outcome in outcomes.items() if outcome.startswith("replaced: stale")]
        self.assertEqual(len(winners), 1, outcomes)
        self.assertEqual(sum(o.startswith("conflict") for o in outcomes.values()), 7)
        self.assertEqual(store.Store(self.hw).record(key("q")).record["members"], records[winners[0]]["members"])

    def test_a_claim_waits_while_another_store_holds_the_key(self) -> None:
        record = {"kind": "test", "members": {"m": self.store.intern(self.file("a", b"A"))}}
        outcomes: list[str] = []
        claimer = threading.Thread(target=lambda: outcomes.append(store.Store(self.hw).claim(key("h"), record)))
        with self.store.lock(key("h")):
            claimer.start()
            claimer.join(0.3)
            self.assertEqual((outcomes, self.store.record(key("h")).reason), ([], "miss: no record"))
        claimer.join(5)
        self.assertEqual(outcomes, ["claimed"])

    def test_a_retired_record_gives_way_to_the_next_claim(self) -> None:
        self.claimed(key("t"), {"mesh.unv": b"OLD"})
        fresh = {"kind": "test", "members": {"mesh.unv": self.store.intern(self.file("n.unv", b"NEW"))}}
        with self.store.lock(key("t")):
            self.store.retire(key("t"))
            self.assertEqual(self.store.claim(key("t"), fresh), "claimed")
        self.assertEqual(self.store.record(key("t")).record["members"], fresh["members"])

    def test_a_record_that_names_a_version_is_refused(self) -> None:
        digest = self.store.intern(self.file("a", b"A"))
        for members in ({"versions/v3/mesh.unv": digest}, {"v3.unv": digest}):
            with self.subTest(members=members), self.assertRaisesRegex(ValueError, "version label v3"):
                self.store.claim(key("v"), {"kind": "test", "members": members}, version_labels=("v3",))
        self.assertEqual(self.store.claim(key("v"), {"kind": "test", "members": {"v30x.unv": digest}},
                                          version_labels=("v3",)), "claimed")

    def test_a_record_member_must_be_a_plain_relative_path(self) -> None:
        digest = self.store.intern(self.file("a", b"A"))
        for name in ("/abs", "../up", "a/../b", ""):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.store.claim(key("p"), {"kind": "test", "members": {name: digest}})


class VerifiedCache(Fixture):
    """`holds` answers from the hashes this Store took before, each kept with the object's stat and the time of
    the hash. It trusts one only while the stat is unchanged and the object's last change (the newer of mtime and
    ctime) is at least one tick of the coarsest timestamp clock older than the hash: git's racy-git rule. `record`,
    `place` and `place_object` hash the bytes again whatever the cache holds (#245)."""

    def object_path(self, digest: str) -> Path:
        return self.hw / ".cad" / "cache" / "objects" / digest

    def hashed_at(self, digest: str, offset: int) -> Path:
        """The object `digest`, made writable, once this Store hashed it `offset` ns after its last change."""
        path = self.object_path(digest)
        os.chmod(path, 0o644)  # first, so that the hash below keeps the stat each test then starts from
        found = os.stat(path)
        with mock.patch.object(store.time, "time_ns", return_value=max(found.st_mtime_ns, found.st_ctime_ns) + offset):
            self.assertTrue(self.store.holds(digest))
        return path

    @contextlib.contextmanager
    def stat_unchanged(self, path: Path, **shown: int) -> Iterator[None]:
        """While the block runs, os.stat of the file at `path` reports the stat it had when the block began, with
        the fields in `shown` replaced. It stands for a write that the timestamps do not show: on a coarse clock
        a rewrite within one tick keeps both mtime and ctime, and ctime cannot be set from user space."""
        before = os.stat(path)
        seen = types.SimpleNamespace(**{name: getattr(before, name) for name in dir(before) if name.startswith("st_")})
        vars(seen).update(shown)
        real = os.stat

        def reported(target, *args, **kwargs):
            found = real(target, *args, **kwargs)
            return seen if (found.st_dev, found.st_ino) == (before.st_dev, before.st_ino) else found

        with mock.patch.object(store.os, "stat", reported):
            yield

    def test_a_write_within_one_tick_of_the_hash_is_seen_although_the_stat_does_not_show_it(self) -> None:
        for offset in (0, TICK_NS - 1):
            with self.subTest(offset=offset):
                digest = self.store.intern(self.file(f"w{offset}", sha(b"w%d" % offset).encode()))
                path = self.hashed_at(digest, offset)
                with self.stat_unchanged(path):
                    path.write_bytes(b"x" * 64)  # other bytes of the same size
                    self.assertFalse(self.store.holds(digest))

    def test_a_hash_at_least_one_tick_after_the_last_change_is_reused_without_reading_the_object(self) -> None:
        for offset in (TICK_NS, 3600 * 10**9):
            with self.subTest(offset=offset):
                digest = self.store.intern(self.file(f"s{offset}", sha(b"s%d" % offset).encode()))
                self.hashed_at(digest, offset)
                with mock.patch.object(store, "file_sha", wraps=store.file_sha) as hashed:
                    self.assertTrue(self.store.holds(digest))
                hashed.assert_not_called()

    def test_a_change_to_any_stat_field_the_cache_keys_on_makes_holds_hash_again(self) -> None:
        for field in ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns"):
            with self.subTest(field=field):
                digest = self.store.intern(self.file(field, sha(field.encode()).encode()))
                path = self.hashed_at(digest, 10 * TICK_NS)  # settled: only a changed key can make it hash again
                with self.stat_unchanged(path, **{field: getattr(os.stat(path), field) + 1}):
                    path.write_bytes(b"x" * 64)
                    self.assertFalse(self.store.holds(digest))

    def test_an_object_gc_removes_between_the_stat_and_the_read_is_absent_not_an_error(self) -> None:
        record = self.claimed(key("gone"), {"mesh.unv": b"GONE"})
        path = self.object_path(record["members"]["mesh.unv"])
        real = store.file_sha

        def removed_first(read):  # another process's gc, after the store's stat of the object
            if Path(read) == path:
                os.chmod(read, 0o644)
                Path(read).unlink()
            return real(read)

        with mock.patch.object(store, "file_sha", side_effect=removed_first):
            self.assertRegex(self.store.record(key("gone")).reason, r"^stale: mesh\.unv ")

    @contextlib.contextmanager
    def vouched_for(self, name: str) -> Iterator[tuple[dict, str]]:
        """A claimed one-member record whose object this Store hashed long after its last change, rewritten with
        other bytes of the same size that the stat does not show: the cache vouches for bytes the object lacks."""
        record = self.claimed(key(name), {"mesh.unv": sha(name.encode()).encode()})
        digest = record["members"]["mesh.unv"]
        path = self.hashed_at(digest, 10 * TICK_NS)
        with self.stat_unchanged(path):
            path.write_bytes(b"x" * 64)
            yield record, digest

    def test_record_hashes_every_member_whatever_the_cache_holds(self) -> None:
        with self.vouched_for("record"):
            self.assertRegex(self.store.record(key("record")).reason, r"^stale: mesh\.unv .* does not hash to its name")

    def test_place_object_hashes_what_it_links_whatever_the_cache_holds(self) -> None:
        target = self.root / "run" / "one.unv"
        with self.vouched_for("place_object") as (_, digest):
            self.assertFalse(self.store.place_object(digest, target))
        self.assertEqual(list(target.parent.iterdir()), [])  # place_object made the folder, and left nothing in it

    def test_place_hashes_what_it_lays_down_whatever_the_cache_holds(self) -> None:
        destination = self.root / "run" / "mesh"
        with self.vouched_for("place") as (record, _):
            self.assertRegex(self.store.place(record, destination), r"^stale: mesh\.unv ")
        self.assertEqual(list(destination.parent.iterdir()), [])


class Place(Fixture):
    def test_a_record_is_laid_down_whole_and_replaces_an_existing_destination_whole(self) -> None:
        record = self.claimed(key("d"), {"mesh.unv": b"UNV", "sub/mesh.json": b"{}"})
        destination = self.root / "run" / "mesh"
        destination.mkdir(parents=True)
        (destination / "old.txt").write_text("old", encoding="utf-8")
        self.assertEqual(self.store.place(record, destination), "")
        self.assertEqual(sorted(p.relative_to(destination).as_posix() for p in destination.rglob("*") if p.is_file()),
                         ["mesh.unv", "sub/mesh.json"])
        self.assertEqual((destination / "mesh.unv").read_bytes(), b"UNV")
        self.assertEqual([p.name for p in destination.parent.iterdir()], ["mesh"])  # no staging left beside it

    def existing(self) -> tuple[dict, Path]:
        record = self.claimed(key("e"), {"mesh.unv": b"NEW"})
        destination = self.root / "run" / "mesh"
        destination.mkdir(parents=True)
        (destination / "old.txt").write_text("old", encoding="utf-8")
        return record, destination

    def test_without_a_swap_call_the_old_folder_is_moved_aside_and_replaced(self) -> None:
        record, destination = self.existing()
        with mock.patch.object(store, "_exchange", return_value=False):
            self.assertEqual(self.store.place(record, destination), "")
        self.assertEqual([p.name for p in destination.iterdir()], ["mesh.unv"])
        self.assertEqual([p.name for p in destination.parent.iterdir()], ["mesh"])

    def test_a_failed_replacement_puts_the_old_folder_back(self) -> None:
        record, destination = self.existing()
        real = os.rename

        def rename(source, target):
            if Path(target) == destination and Path(source).name.endswith(".placing"):
                raise OSError(28, "No space left on device")
            real(source, target)

        with mock.patch.object(store, "_exchange", return_value=False), \
                mock.patch.object(store.os, "rename", side_effect=rename), self.assertRaises(OSError):
            self.store.place(record, destination)
        self.assertEqual([p.name for p in destination.iterdir()], ["old.txt"])
        self.assertEqual([p.name for p in destination.parent.iterdir()], ["mesh"])

    def test_a_record_with_a_missing_object_leaves_the_destination_untouched(self) -> None:
        record = self.claimed(key("u"), {"a": b"A", "b": b"B"})
        missing = self.hw / ".cad" / "cache" / "objects" / record["members"]["b"]
        os.chmod(missing, 0o644)
        missing.unlink()
        destination = self.root / "run" / "mesh"
        reason = self.store.place(record, destination)
        self.assertRegex(reason, r"^stale: b ")
        self.assertFalse(destination.exists())
        self.assertEqual(list((self.root / "run").iterdir()), [])


class Locks(Fixture):
    def test_threads_that_lock_an_empty_store_at_once_all_get_their_locks(self) -> None:
        errors: list[BaseException] = []
        start = threading.Barrier(8)

        def take(i: int) -> None:
            try:
                start.wait()
                with store.Store(self.hw).lock(key(f"cold{i}")):
                    pass
            except BaseException as error:  # noqa: BLE001 - every failure is the finding
                errors.append(error)

        threads = [threading.Thread(target=take, args=(i,)) for i in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
        self.assertEqual(errors, [])
        self.assertEqual((self.hw / ".cad" / "cache" / ".gitignore").read_text(encoding="utf-8"), "*\n")
    def test_the_lock_of_a_key_is_held_by_one_holder_at_a_time(self) -> None:
        held: list[str] = []
        with self.store.lock(key("l")):
            thread = threading.Thread(target=lambda: (self.store.lock(key("l")).__enter__(), held.append("second")))
            thread.start()
            thread.join(0.3)
            self.assertEqual(held, [])
        thread.join(5)
        self.assertEqual(held, ["second"])
        self.assertEqual(layout.classify(self.hw / ".cad" / "cache" / "locks" / f"{key('l')}.lock", self.hw).entry.id,
                         "cache.locks")


class Collection(Fixture):
    def seal(self, rel: str, files: dict[str, str]) -> None:
        path = self.hw / rel / "manifest.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"files": files}), encoding="utf-8")

    def test_gc_keeps_what_any_sealed_manifest_names_and_removes_the_rest(self) -> None:
        kept = self.claimed(key("a"), {"part.step": b"VERSION"})
        bundle = self.claimed(key("b"), {"mesh.unv": b"BUNDLE"})
        released = self.claimed(key("c"), {"part.stl": b"RELEASE"})
        orphan = self.claimed(key("d"), {"x": b"ORPHAN"})
        self.seal("versions/v1", {"parts/P.step": kept["members"]["part.step"]})
        self.seal("analysis/v1/beam", {"evidence/mesh.unv": bundle["members"]["mesh.unv"]})
        self.seal("releases/A", {"P.stl": {"sha256": released["members"]["part.stl"], "original": "x"}})
        result = self.store.gc()
        self.assertEqual(result["objects"]["removed"], 1)
        self.assertEqual(result["records"]["removed"], 1)
        self.assertEqual(result["manifests"], 3)
        self.assertIsNotNone(self.store.record(key("b")).record)
        self.assertIsNone(self.store.record(key("d")).record)
        self.assertFalse((self.hw / ".cad" / "cache" / "objects" / orphan["members"]["x"]).exists())

    def test_gc_removes_the_part_store_of_the_former_layout(self) -> None:
        for folder in ("parts", "builds"):
            (self.hw / ".cad" / folder).mkdir(parents=True)
            (self.hw / ".cad" / folder / "x").write_text("old", encoding="utf-8")
            os.chmod(self.hw / ".cad" / folder / "x", 0o444)
        dry = self.store.gc(dry_run=True)
        self.assertEqual(dry["former_layout_removed"], [".cad/builds", ".cad/parts"])
        self.assertTrue((self.hw / ".cad" / "parts").is_dir())
        self.store.gc()
        self.assertFalse((self.hw / ".cad" / "parts").exists())
        self.assertFalse((self.hw / ".cad" / "builds").exists())

    def test_gc_refuses_an_unreadable_manifest(self) -> None:
        path = self.hw / "versions" / "v1" / "manifest.json"
        path.parent.mkdir(parents=True)
        path.write_text("{", encoding="utf-8")
        with self.assertRaisesRegex(store.StoreError, "manifest"):
            self.store.gc()

    def test_gc_reads_only_the_manifests_that_seal_their_folder(self) -> None:
        bundle = self.claimed(key("b"), {"mesh.unv": b"BUNDLE"})
        released = self.claimed(key("c"), {"part.stl": b"RELEASE"})
        self.seal("analysis/v1/beam", {"evidence/mesh.unv": bundle["members"]["mesh.unv"],
                                       "evidence/manifest.json": "0" * 64})
        self.seal("releases/A", {"P.stl": {"sha256": released["members"]["part.stl"], "original": "x"}})
        for rel in ("analysis/v1/beam/evidence/manifest.json", "releases/A/definition/manifest.json"):
            payload = self.hw / rel  # a file named manifest.json inside a sealed folder, not a seal itself
            payload.parent.mkdir(parents=True, exist_ok=True)
            payload.write_text(json.dumps({"solver": "ccx"}), encoding="utf-8")
        result = self.store.gc()
        self.assertEqual((result["manifests"], result["objects"]["removed"]), (2, 0))
        self.assertIsNotNone(self.store.record(key("b")).record)
        self.assertIsNotNone(self.store.record(key("c")).record)


class Staging(Fixture):
    def test_every_name_the_store_stages_under_hw_is_a_transient_of_the_layout(self) -> None:
        """A run killed mid-write leaves these names. The audit names each one a leftover of its writer."""
        staged: list[Path] = []
        real = os.replace

        def replace(source, target):
            if Path(source).is_relative_to(self.hw):
                staged.append(Path(source))
            real(source, target)

        with mock.patch.object(store.os, "replace", side_effect=replace):
            self.claimed(key("g"), {"mesh.unv": b"UNV"})
        kinds = {path.parent.name if path.parent.name != "cache" else ".gitignore" for path in staged}
        self.assertEqual(kinds, {".gitignore", "objects", "records"})
        for path in staged:
            with self.subTest(name=path.name):
                found = layout.load().exemption(layout.relative(self.hw, path), False)
                self.assertIsNotNone(found, path.name)
                self.assertEqual(found.kind, "transient", path.name)
                self.assertIn("store.py", found.writer)


if __name__ == "__main__":
    unittest.main()

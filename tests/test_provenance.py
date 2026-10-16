"""code/provenance.json: what produced each step's outputs (issue #5)."""

import hashlib
import json
import os
import subprocess

import pytest

from videogames_utils import provenance

GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "init.defaultBranch=main",
       "-c", "protocol.file.allow=always"]


def git(repo, *args):
    return subprocess.run(GIT + ["-C", str(repo), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def make_repo(path, files=None):
    path.mkdir(parents=True)
    git(path, "init", "-q")
    for name, text in (files or {"README": "x"}).items():
        (path / name).parent.mkdir(parents=True, exist_ok=True)
        (path / name).write_text(text)
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "init")
    return path


@pytest.fixture
def package(tmp_path, monkeypatch):
    """A clean stand-in for the videogames_utils checkout."""
    repo = make_repo(tmp_path / "videogames_utils")
    monkeypatch.setattr(provenance, "PACKAGE_DIR", str(repo))
    return repo


@pytest.fixture
def dataset(tmp_path, package):
    """A clean dataset with a stimuli submodule whose commit is on its remote."""
    remote = tmp_path / "stimuli.git"
    stimuli = make_repo(tmp_path / "stimuli-src", {"Game/rom.sha": "abc\n"})
    git(tmp_path, "clone", "-q", "--bare", str(stimuli), str(remote))
    ds = make_repo(tmp_path / "ds", {"sub-01/ses-001/gamelogs/a.bk2": "bk2",
                                      "code/replays/generate_replays.py": "#"})
    git(ds, "submodule", "add", "-q", str(remote), "stimuli")
    git(ds, "commit", "-q", "-m", "stimuli")
    return ds


def run_step(ds, step="replays", **params):
    with provenance.step(str(ds), step, "code/replays/generate_replays.py",
                         parameters=params or {"force": False},
                         input_submodules=["stimuli"]) as prov:
        prov.add_inputs([str(ds / "sub-01/ses-001/gamelogs/a.bk2")])
        out = ds / "sub-01/ses-001/gamelogs" / f"a_{step}.json"
        out.write_text(step)
        prov.add_outputs([str(out)])
    return json.loads((ds / "code" / "provenance.json").read_text())


def test_step_records_code_inputs_environment_parameters_outputs(dataset, package):
    record = run_step(dataset, force=True, frame_rate=60.0988)
    section = record["replays"]

    assert section["code"]["dataset_commit"] == git(dataset, "rev-parse", "HEAD")
    assert section["code"]["videogames_utils_commit"] == git(package, "rev-parse", "HEAD")
    assert section["code"]["videogames_utils_version"]
    assert section["code"]["script"] == "code/replays/generate_replays.py"

    bk2 = "sub-01/ses-001/gamelogs/a.bk2"
    assert section["inputs"]["files"] == {bk2: "sha256:" + hashlib.sha256(b"bk2").hexdigest()}
    assert section["inputs"]["submodules"] == {
        "stimuli": git(dataset / "stimuli", "rev-parse", "HEAD")}

    env = section["environment"]
    assert env["python"] and env["host"]
    assert "stable-retro" in env["packages"]
    assert env["installed_packages_sha256"]
    assert "ffmpeg" in env

    assert section["parameters"] == {"force": True, "frame_rate": 60.0988}

    out = "sub-01/ses-001/gamelogs/a_replays.json"
    assert section["outputs"]["files"] == [out]
    assert section["outputs"]["checksum"].startswith("sha256:")
    assert section["timestamp"].endswith("Z")


def test_each_step_rewrites_only_its_own_section(dataset):
    first = run_step(dataset, "replays")
    git(dataset, "add", "-A")
    git(dataset, "commit", "-q", "-m", "replays")
    second = run_step(dataset, "videos")
    assert second["replays"] == first["replays"]
    assert set(second) == {"replays", "videos"}

    git(dataset, "add", "-A")
    git(dataset, "commit", "-q", "-m", "videos")
    third = run_step(dataset, "replays", force=True)
    assert third["videos"] == second["videos"]
    assert third["replays"]["parameters"] == {"force": True}


def test_annexed_input_is_recorded_by_its_key(dataset):
    key = "MD5E-s3--0123456789abcdef0123456789abcdef.bk2"
    obj = dataset / ".git" / "annex" / "objects" / "Xx" / "Yy" / key / key
    obj.parent.mkdir(parents=True)
    obj.write_text("bk2")
    link = dataset / "sub-01/ses-001/gamelogs/b.bk2"
    link.symlink_to(os.path.relpath(obj, link.parent))
    assert provenance.file_id(str(link)) == key


def test_nothing_is_written_when_the_step_fails(dataset):
    with pytest.raises(RuntimeError):
        with provenance.step(str(dataset), "replays", "code/replays/generate_replays.py"):
            raise RuntimeError("boom")
    assert not (dataset / "code" / "provenance.json").exists()


def test_refuses_when_the_dataset_has_uncommitted_changes(dataset):
    (dataset / "code/replays/generate_replays.py").write_text("# edited")
    with pytest.raises(provenance.ProvenanceError, match="uncommitted.*ds"):
        run_step(dataset)


def test_refuses_when_videogames_utils_has_uncommitted_changes(dataset, package):
    (package / "README").write_text("edited")
    with pytest.raises(provenance.ProvenanceError, match="uncommitted.*videogames_utils"):
        run_step(dataset)


def test_refuses_when_an_input_submodule_commit_is_not_pushed(dataset):
    sub = dataset / "stimuli"
    (sub / "Game" / "rom.sha").write_text("def\n")
    git(sub, "commit", "-q", "-am", "local only")
    git(dataset, "commit", "-q", "-am", "bump stimuli")
    with pytest.raises(provenance.ProvenanceError, match="stimuli.*not on any remote"):
        run_step(dataset)

    git(sub, "push", "-q", "origin", "HEAD:main")
    run_step(dataset)  # now pushed: accepted


def test_refuses_when_an_input_submodule_is_not_installed(dataset):
    git(dataset, "submodule", "deinit", "-q", "-f", "stimuli")
    with pytest.raises(provenance.ProvenanceError, match="stimuli is not installed"):
        run_step(dataset)


def test_there_is_no_override():
    import inspect
    for func in (provenance.step, provenance.require_clean):
        params = inspect.signature(func).parameters
        assert not any(p in params for p in ("force", "allow_dirty", "override"))


def test_generated_by_keeps_other_entries(dataset):
    desc = dataset / "dataset_description.json"
    desc.write_text(json.dumps({"Name": "x", "GeneratedBy": [{"Name": "bidsify"}]}))
    run_step(dataset)
    provenance.update_generated_by(str(dataset))
    provenance.update_generated_by(str(dataset))  # idempotent
    entries = json.loads(desc.read_text())["GeneratedBy"]
    assert [e["Name"] for e in entries] == ["bidsify", "videogames_utils"]
    ours = entries[1]
    assert ours["Version"]
    assert ours["CodeURL"].endswith(
        provenance.load(str(dataset))["replays"]["code"]["videogames_utils_commit"])
    assert "replays" in ours["Description"]

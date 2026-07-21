"""
tests/test_code_snapshot.py — RepositorySnapshot 与 FileRecord 单元测试

验收标准（对应方案第24.1节）：
  - 相同 repo + 相同 commit + 相同配置 → 相同 snapshot_id
  - 不同 commit → 不同 snapshot_id
  - 产物中不含本机绝对路径
  - relative_path 是合法 POSIX 相对路径
  - logical_file_id 在不同 snapshot 间保持稳定（同 repo + 同路径）
  - file_version_id 随内容变化而变化
  - 路径越界文件被拒绝
  - branch 不影响 snapshot_id
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from agent_knowledge_hub.code_snapshot import (
    CODE_SNAPSHOT_SCHEMA_VERSION,
    FileRecord,
    ParserMode,
    RepositorySnapshot,
    SecretStatus,
    SnapshotState,
    compute_file_version_id,
    compute_index_config_hash,
    compute_logical_file_id,
    compute_repo_id,
    compute_snapshot_id,
    create_file_record,
    create_snapshot,
    detect_language,
)
from agent_knowledge_hub.code_manifest import (
    DEFAULT_EXCLUDE_DIRS,
    TARGET_EXTENSIONS,
    scan_repo_with_snapshot,
    write_snapshot_bundle,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _git_init(path: Path) -> None:
    """在 path 初始化一个最小 git 仓库并提交一个文件，确保有有效 HEAD。"""
    subprocess.run(["git", "init", "-b", "main", str(path)],
                   capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"],
                   cwd=path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"],
                   cwd=path, capture_output=True, check=True)
    # 初始提交，确保 HEAD 可解析
    init_file = path / ".gitkeep"
    init_file.write_text("init\n", encoding="utf-8")
    subprocess.run(["git", "add", ".gitkeep"], cwd=path,
                   capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"],
                   cwd=path, capture_output=True, check=True)


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    """返回一个带有初始提交的临时 git 仓库根目录。"""
    _git_init(tmp_path)
    return tmp_path


@pytest.fixture()
def repo_with_files(git_repo: Path) -> Path:
    """在 git_repo 中写入若干测试文件并提交。"""
    (git_repo / "src").mkdir()
    (git_repo / "src" / "main.cpp").write_text(
        "#include <stdio.h>\nint main() { return 0; }\n", encoding="utf-8"
    )
    (git_repo / "src" / "util.h").write_text(
        "#pragma once\nvoid util();\n", encoding="utf-8"
    )
    (git_repo / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.10)\n", encoding="utf-8"
    )
    (git_repo / "README.md").write_text("# Test\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=git_repo,
                   capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "add source files"],
                   cwd=git_repo, capture_output=True, check=True)
    return git_repo


# ---------------------------------------------------------------------------
# ID 计算：确定性与不变量
# ---------------------------------------------------------------------------

class TestIdComputation:
    def test_snapshot_id_is_deterministic(self):
        """相同输入 → 相同 snapshot_id。"""
        sid1 = compute_snapshot_id("repo_abc", "aabbcc", {}, "cfg123")
        sid2 = compute_snapshot_id("repo_abc", "aabbcc", {}, "cfg123")
        assert sid1 == sid2

    def test_snapshot_id_changes_with_commit(self):
        """不同 commit → 不同 snapshot_id。"""
        sid1 = compute_snapshot_id("repo_abc", "commit_aaa", {}, "cfg")
        sid2 = compute_snapshot_id("repo_abc", "commit_bbb", {}, "cfg")
        assert sid1 != sid2

    def test_snapshot_id_changes_with_config(self):
        """不同配置 → 不同 snapshot_id。"""
        sid1 = compute_snapshot_id("repo_abc", "abc123", {}, "cfg_v1")
        sid2 = compute_snapshot_id("repo_abc", "abc123", {}, "cfg_v2")
        assert sid1 != sid2

    def test_snapshot_id_prefix(self):
        sid = compute_snapshot_id("repo_abc", "abc123", {}, "cfg")
        assert sid.startswith("snap_")

    def test_logical_file_id_stable_across_snapshots(self):
        """同 repo + 同路径 → 相同 logical_file_id，与 snapshot 无关。"""
        lid1 = compute_logical_file_id("repo_x", "src/main.cpp")
        lid2 = compute_logical_file_id("repo_x", "src/main.cpp")
        assert lid1 == lid2
        assert lid1.startswith("file_")

    def test_logical_file_id_differs_for_different_paths(self):
        lid1 = compute_logical_file_id("repo_x", "src/main.cpp")
        lid2 = compute_logical_file_id("repo_x", "src/util.h")
        assert lid1 != lid2

    def test_file_version_id_changes_with_content(self):
        """内容哈希变化 → file_version_id 变化。"""
        fv1 = compute_file_version_id("snap_abc", "src/main.cpp", "hash_aaa")
        fv2 = compute_file_version_id("snap_abc", "src/main.cpp", "hash_bbb")
        assert fv1 != fv2

    def test_file_version_id_changes_with_snapshot(self):
        """不同 snapshot（不同 commit）→ 不同 file_version_id。"""
        fv1 = compute_file_version_id("snap_aaa", "src/main.cpp", "same_hash")
        fv2 = compute_file_version_id("snap_bbb", "src/main.cpp", "same_hash")
        assert fv1 != fv2

    def test_file_version_id_prefix(self):
        fv = compute_file_version_id("snap_abc", "src/main.cpp", "hash")
        assert fv.startswith("fver_")

    def test_repo_id_from_remote_is_stable(self):
        """相同 remote URL → 相同 repo_id。"""
        rid1 = compute_repo_id("https://git.company/repo.git", Path("/any/path"))
        rid2 = compute_repo_id("https://git.company/repo.git", Path("/other/path"))
        assert rid1 == rid2
        assert rid1.startswith("repo_")

    def test_repo_id_strips_git_suffix(self):
        """有无 .git 后缀应产生相同 repo_id。"""
        rid1 = compute_repo_id("https://git.company/repo.git", Path("/p"))
        rid2 = compute_repo_id("https://git.company/repo", Path("/p"))
        assert rid1 == rid2

    def test_index_config_hash_deterministic(self):
        cfg1 = compute_index_config_hash(
            frozenset({"build", ".git"}), frozenset({".cpp", ".h"}), {"fallback": "1.0"}
        )
        cfg2 = compute_index_config_hash(
            frozenset({".git", "build"}), frozenset({".h", ".cpp"}), {"fallback": "1.0"}
        )
        assert cfg1 == cfg2  # 集合顺序不影响结果

    def test_index_config_hash_changes_with_exclude(self):
        cfg1 = compute_index_config_hash(
            frozenset({"build"}), frozenset({".cpp"}), {"fallback": "1.0"}
        )
        cfg2 = compute_index_config_hash(
            frozenset({"build", "node_modules"}), frozenset({".cpp"}), {"fallback": "1.0"}
        )
        assert cfg1 != cfg2


# ---------------------------------------------------------------------------
# create_snapshot：git 元数据解析
# ---------------------------------------------------------------------------

class TestCreateSnapshot:
    def test_snapshot_has_full_commit_sha(self, git_repo: Path):
        snap = create_snapshot(
            git_repo,
            exclude_dirs=DEFAULT_EXCLUDE_DIRS,
            extensions=TARGET_EXTENSIONS,
        )
        # 完整 SHA 为 40 位十六进制，或 no-git- 前缀降级
        assert len(snap.commit_sha) == 40 or snap.commit_sha.startswith("no-git-")

    def test_snapshot_id_no_absolute_path(self, git_repo: Path):
        """snapshot_id 不含本机路径。"""
        snap = create_snapshot(
            git_repo,
            exclude_dirs=DEFAULT_EXCLUDE_DIRS,
            extensions=TARGET_EXTENSIONS,
        )
        assert str(git_repo) not in snap.snapshot_id

    def test_snapshot_state_is_planned(self, git_repo: Path):
        snap = create_snapshot(
            git_repo,
            exclude_dirs=DEFAULT_EXCLUDE_DIRS,
            extensions=TARGET_EXTENSIONS,
        )
        assert snap.state == SnapshotState.PLANNED.value

    def test_snapshot_schema_version(self, git_repo: Path):
        snap = create_snapshot(
            git_repo,
            exclude_dirs=DEFAULT_EXCLUDE_DIRS,
            extensions=TARGET_EXTENSIONS,
        )
        assert snap.schema_version == CODE_SNAPSHOT_SCHEMA_VERSION

    def test_same_repo_same_commit_same_snapshot_id(self, git_repo: Path):
        """方案第24.1节：相同 repo+commit+配置 → 相同 snapshot_id。"""
        snap1 = create_snapshot(
            git_repo,
            exclude_dirs=DEFAULT_EXCLUDE_DIRS,
            extensions=TARGET_EXTENSIONS,
        )
        snap2 = create_snapshot(
            git_repo,
            exclude_dirs=DEFAULT_EXCLUDE_DIRS,
            extensions=TARGET_EXTENSIONS,
        )
        assert snap1.snapshot_id == snap2.snapshot_id

    def test_different_config_different_snapshot_id(self, git_repo: Path):
        """不同配置（排除目录不同）→ 不同 snapshot_id。"""
        snap1 = create_snapshot(
            git_repo,
            exclude_dirs=frozenset({"build"}),
            extensions=TARGET_EXTENSIONS,
        )
        snap2 = create_snapshot(
            git_repo,
            exclude_dirs=frozenset({"build", "node_modules"}),
            extensions=TARGET_EXTENSIONS,
        )
        assert snap1.snapshot_id != snap2.snapshot_id

    def test_branch_does_not_affect_snapshot_id(self, git_repo: Path):
        """方案第5.3节：branch 不参与 snapshot_id 计算。"""
        snap1 = create_snapshot(
            git_repo,
            exclude_dirs=DEFAULT_EXCLUDE_DIRS,
            extensions=TARGET_EXTENSIONS,
        )
        # 创建并切换新分支（commit SHA 不变），snapshot_id 应相同
        subprocess.run(["git", "checkout", "-b", "feature/test"],
                       cwd=git_repo, capture_output=True, check=True)
        snap2 = create_snapshot(
            git_repo,
            exclude_dirs=DEFAULT_EXCLUDE_DIRS,
            extensions=TARGET_EXTENSIONS,
        )
        assert snap1.snapshot_id == snap2.snapshot_id
        assert snap1.branch != snap2.branch  # branch 标注不同

    def test_new_commit_changes_snapshot_id(self, git_repo: Path):
        """新 commit → 不同 snapshot_id。"""
        snap1 = create_snapshot(
            git_repo,
            exclude_dirs=DEFAULT_EXCLUDE_DIRS,
            extensions=TARGET_EXTENSIONS,
        )
        # 追加一个提交
        (git_repo / "extra.txt").write_text("change\n", encoding="utf-8")
        subprocess.run(["git", "add", "extra.txt"],
                       cwd=git_repo, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "extra"],
                       cwd=git_repo, capture_output=True, check=True)
        snap2 = create_snapshot(
            git_repo,
            exclude_dirs=DEFAULT_EXCLUDE_DIRS,
            extensions=TARGET_EXTENSIONS,
        )
        assert snap1.snapshot_id != snap2.snapshot_id

    def test_repo_remote_has_no_credentials(self, git_repo: Path):
        """如果有 remote URL，不含用户名密码。"""
        subprocess.run(
            ["git", "remote", "add", "origin",
             "https://user:pass@git.example.com/repo.git"],
            cwd=git_repo, capture_output=True, check=True,
        )
        snap = create_snapshot(
            git_repo,
            exclude_dirs=DEFAULT_EXCLUDE_DIRS,
            extensions=TARGET_EXTENSIONS,
        )
        if snap.repo_remote:
            assert "user" not in snap.repo_remote
            assert "pass"  not in snap.repo_remote
            assert "@"     not in snap.repo_remote

    def test_nonexistent_repo_raises(self, tmp_path: Path):
        with pytest.raises(RuntimeError, match="不存在"):
            create_snapshot(
                tmp_path / "nonexistent",
                exclude_dirs=DEFAULT_EXCLUDE_DIRS,
                extensions=TARGET_EXTENSIONS,
            )

    def test_snapshot_to_dict_no_absolute_path(self, git_repo: Path):
        """to_dict() 序列化结果中不应出现本机绝对路径。"""
        snap = create_snapshot(
            git_repo,
            exclude_dirs=DEFAULT_EXCLUDE_DIRS,
            extensions=TARGET_EXTENSIONS,
        )
        serialized = json.dumps(snap.to_dict())
        assert str(git_repo) not in serialized


# ---------------------------------------------------------------------------
# create_file_record：FileRecord 不变量
# ---------------------------------------------------------------------------

class TestCreateFileRecord:
    def test_relative_path_is_posix(self, repo_with_files: Path):
        snap = create_snapshot(
            repo_with_files,
            exclude_dirs=DEFAULT_EXCLUDE_DIRS,
            extensions=TARGET_EXTENSIONS,
        )
        cpp_file = repo_with_files / "src" / "main.cpp"
        fr = create_file_record(cpp_file, repo_with_files, snap)

        # 必须是相对路径，不以 / 开头
        assert not fr.relative_path.startswith("/")
        assert fr.relative_path == "src/main.cpp"

    def test_no_absolute_path_in_record(self, repo_with_files: Path):
        snap = create_snapshot(
            repo_with_files,
            exclude_dirs=DEFAULT_EXCLUDE_DIRS,
            extensions=TARGET_EXTENSIONS,
        )
        cpp_file = repo_with_files / "src" / "main.cpp"
        fr = create_file_record(cpp_file, repo_with_files, snap)

        serialized = json.dumps(fr.to_dict())
        assert str(repo_with_files) not in serialized

    def test_language_detection_cpp(self, repo_with_files: Path):
        snap = create_snapshot(
            repo_with_files,
            exclude_dirs=DEFAULT_EXCLUDE_DIRS,
            extensions=TARGET_EXTENSIONS,
        )
        fr = create_file_record(
            repo_with_files / "src" / "main.cpp", repo_with_files, snap
        )
        assert fr.language == "cpp"

    def test_language_detection_header(self, repo_with_files: Path):
        snap = create_snapshot(
            repo_with_files,
            exclude_dirs=DEFAULT_EXCLUDE_DIRS,
            extensions=TARGET_EXTENSIONS,
        )
        fr = create_file_record(
            repo_with_files / "src" / "util.h", repo_with_files, snap
        )
        assert fr.language == "c_header"

    def test_language_detection_cmake(self, repo_with_files: Path):
        snap = create_snapshot(
            repo_with_files,
            exclude_dirs=DEFAULT_EXCLUDE_DIRS,
            extensions=TARGET_EXTENSIONS,
        )
        fr = create_file_record(
            repo_with_files / "CMakeLists.txt", repo_with_files, snap
        )
        assert fr.language == "cmake"

    def test_parser_mode_is_fallback_for_code(self, repo_with_files: Path):
        """Phase A 所有代码文件 parser_mode 均为 fallback。"""
        snap = create_snapshot(
            repo_with_files,
            exclude_dirs=DEFAULT_EXCLUDE_DIRS,
            extensions=TARGET_EXTENSIONS,
        )
        fr = create_file_record(
            repo_with_files / "src" / "main.cpp", repo_with_files, snap
        )
        assert fr.parser_mode == ParserMode.FALLBACK.value

    def test_secret_status_default(self, repo_with_files: Path):
        snap = create_snapshot(
            repo_with_files,
            exclude_dirs=DEFAULT_EXCLUDE_DIRS,
            extensions=TARGET_EXTENSIONS,
        )
        fr = create_file_record(
            repo_with_files / "src" / "main.cpp", repo_with_files, snap
        )
        assert fr.secret_status == SecretStatus.NOT_SCANNED.value

    def test_ownership_and_acl_empty_in_phase_a(self, repo_with_files: Path):
        snap = create_snapshot(
            repo_with_files,
            exclude_dirs=DEFAULT_EXCLUDE_DIRS,
            extensions=TARGET_EXTENSIONS,
        )
        fr = create_file_record(
            repo_with_files / "src" / "main.cpp", repo_with_files, snap
        )
        assert fr.ownership_ids == []
        assert fr.acl_tags == []

    def test_logical_file_id_stable_across_snapshots(self, repo_with_files: Path):
        """同一 repo + 同一文件路径，不同 snapshot 下 logical_file_id 相同。"""
        snap1 = create_snapshot(
            repo_with_files,
            exclude_dirs=DEFAULT_EXCLUDE_DIRS,
            extensions=TARGET_EXTENSIONS,
        )
        fr1 = create_file_record(
            repo_with_files / "src" / "main.cpp", repo_with_files, snap1
        )

        # 追加提交产生新 snapshot
        (repo_with_files / "extra.txt").write_text("x\n", encoding="utf-8")
        subprocess.run(["git", "add", "extra.txt"],
                       cwd=repo_with_files, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "extra"],
                       cwd=repo_with_files, capture_output=True, check=True)
        snap2 = create_snapshot(
            repo_with_files,
            exclude_dirs=DEFAULT_EXCLUDE_DIRS,
            extensions=TARGET_EXTENSIONS,
        )
        fr2 = create_file_record(
            repo_with_files / "src" / "main.cpp", repo_with_files, snap2
        )

        assert fr1.logical_file_id == fr2.logical_file_id   # 路径未变，逻辑ID稳定
        assert fr1.file_version_id != fr2.file_version_id   # snapshot 变了，版本ID不同

    def test_file_version_id_changes_when_content_changes(self, repo_with_files: Path):
        snap = create_snapshot(
            repo_with_files,
            exclude_dirs=DEFAULT_EXCLUDE_DIRS,
            extensions=TARGET_EXTENSIONS,
        )
        cpp = repo_with_files / "src" / "main.cpp"
        fr1 = create_file_record(cpp, repo_with_files, snap)

        # 修改文件内容（不提交，仅验证内容哈希驱动 ID 变化）
        cpp.write_text("// modified\nint main(){}\n", encoding="utf-8")
        fr2 = create_file_record(cpp, repo_with_files, snap)

        assert fr1.content_hash  != fr2.content_hash
        assert fr1.file_version_id != fr2.file_version_id

    def test_path_escape_raises(self, repo_with_files: Path, tmp_path_factory: pytest.TempPathFactory):
        """路径越界文件必须被拒绝（对应方案第6.2节）。"""
        # 使用独立临时目录，确保 outside_file 真正在 repo_with_files 之外
        outside_dir  = tmp_path_factory.mktemp("outside")
        outside_file = outside_dir / "outside.cpp"
        outside_file.write_text("int x;\n", encoding="utf-8")
        snap = create_snapshot(
            repo_with_files,
            exclude_dirs=DEFAULT_EXCLUDE_DIRS,
            extensions=TARGET_EXTENSIONS,
        )
        with pytest.raises(ValueError, match="越界"):
            create_file_record(outside_file, repo_with_files, snap)

    def test_vendored_flag(self, repo_with_files: Path):
        vendor_dir = repo_with_files / "vendor"
        vendor_dir.mkdir()
        vfile = vendor_dir / "lib.cpp"
        vfile.write_text("int v;\n", encoding="utf-8")

        snap = create_snapshot(
            repo_with_files,
            exclude_dirs=frozenset(),   # 不排除 vendor 以便测试标记
            extensions=TARGET_EXTENSIONS,
        )
        fr = create_file_record(vfile, repo_with_files, snap)
        assert fr.vendored is True

    def test_generated_flag(self, repo_with_files: Path):
        gen_dir = repo_with_files / "generated"
        gen_dir.mkdir()
        gfile = gen_dir / "auto.cpp"
        gfile.write_text("int g;\n", encoding="utf-8")

        snap = create_snapshot(
            repo_with_files,
            exclude_dirs=frozenset(),
            extensions=TARGET_EXTENSIONS,
        )
        fr = create_file_record(gfile, repo_with_files, snap)
        assert fr.generated is True

    def test_content_hash_is_sha256(self, repo_with_files: Path):
        snap = create_snapshot(
            repo_with_files,
            exclude_dirs=DEFAULT_EXCLUDE_DIRS,
            extensions=TARGET_EXTENSIONS,
        )
        fr = create_file_record(
            repo_with_files / "src" / "main.cpp", repo_with_files, snap
        )
        assert len(fr.content_hash) == 64
        assert all(c in "0123456789abcdef" for c in fr.content_hash)

    def test_snapshot_id_in_file_record(self, repo_with_files: Path):
        snap = create_snapshot(
            repo_with_files,
            exclude_dirs=DEFAULT_EXCLUDE_DIRS,
            extensions=TARGET_EXTENSIONS,
        )
        fr = create_file_record(
            repo_with_files / "src" / "main.cpp", repo_with_files, snap
        )
        assert fr.snapshot_id == snap.snapshot_id
        assert fr.repo_id     == snap.repo_id


# ---------------------------------------------------------------------------
# scan_repo_with_snapshot：端到端扫描
# ---------------------------------------------------------------------------

class TestScanRepoWithSnapshot:
    def test_returns_snapshot_and_file_records(self, repo_with_files: Path):
        snap, records = scan_repo_with_snapshot(
            repo_with_files,
            exclude_dirs=DEFAULT_EXCLUDE_DIRS,
            extensions=TARGET_EXTENSIONS,
        )
        assert isinstance(snap, RepositorySnapshot)
        assert isinstance(records, list)
        assert len(records) > 0
        assert all(isinstance(r, FileRecord) for r in records)

    def test_no_absolute_paths_in_any_record(self, repo_with_files: Path):
        """方案第2.2节：产物不得含本机绝对路径。"""
        snap, records = scan_repo_with_snapshot(
            repo_with_files,
            exclude_dirs=DEFAULT_EXCLUDE_DIRS,
            extensions=TARGET_EXTENSIONS,
        )
        repo_str = str(repo_with_files)
        for fr in records:
            assert repo_str not in fr.relative_path, (
                f"relative_path 含绝对路径：{fr.relative_path}"
            )
            assert not fr.relative_path.startswith("/"), (
                f"relative_path 以 / 开头：{fr.relative_path}"
            )

    def test_all_records_share_snapshot_id(self, repo_with_files: Path):
        snap, records = scan_repo_with_snapshot(
            repo_with_files,
            exclude_dirs=DEFAULT_EXCLUDE_DIRS,
            extensions=TARGET_EXTENSIONS,
        )
        for fr in records:
            assert fr.snapshot_id == snap.snapshot_id

    def test_scan_is_deterministic(self, repo_with_files: Path):
        """相同仓库两次扫描，file_version_id 集合完全一致。"""
        _, records1 = scan_repo_with_snapshot(
            repo_with_files,
            exclude_dirs=DEFAULT_EXCLUDE_DIRS,
            extensions=TARGET_EXTENSIONS,
        )
        _, records2 = scan_repo_with_snapshot(
            repo_with_files,
            exclude_dirs=DEFAULT_EXCLUDE_DIRS,
            extensions=TARGET_EXTENSIONS,
        )
        ids1 = {r.file_version_id for r in records1}
        ids2 = {r.file_version_id for r in records2}
        assert ids1 == ids2

    def test_excluded_dirs_not_in_records(self, repo_with_files: Path):
        build_dir = repo_with_files / "build"
        build_dir.mkdir()
        (build_dir / "artifact.cpp").write_text("int x;\n", encoding="utf-8")

        _, records = scan_repo_with_snapshot(
            repo_with_files,
            exclude_dirs=DEFAULT_EXCLUDE_DIRS,  # build 在默认排除列表中
            extensions=TARGET_EXTENSIONS,
        )
        paths = {r.relative_path for r in records}
        assert not any(p.startswith("build/") for p in paths)

    def test_unique_file_version_ids(self, repo_with_files: Path):
        """所有 FileRecord 的 file_version_id 必须唯一（无 ID 冲突）。"""
        _, records = scan_repo_with_snapshot(
            repo_with_files,
            exclude_dirs=DEFAULT_EXCLUDE_DIRS,
            extensions=TARGET_EXTENSIONS,
        )
        ids = [r.file_version_id for r in records]
        assert len(ids) == len(set(ids)), "存在重复的 file_version_id"


# ---------------------------------------------------------------------------
# write_snapshot_bundle：输出文件结构
# ---------------------------------------------------------------------------

class TestWriteSnapshotBundle:
    def test_output_files_created(self, repo_with_files: Path, tmp_path: Path):
        snap, records = scan_repo_with_snapshot(
            repo_with_files,
            exclude_dirs=DEFAULT_EXCLUDE_DIRS,
            extensions=TARGET_EXTENSIONS,
        )
        paths = write_snapshot_bundle(snap, records, tmp_path)

        assert paths["snapshot"].exists()
        assert paths["files"].exists()

    def test_snapshot_json_is_valid(self, repo_with_files: Path, tmp_path: Path):
        snap, records = scan_repo_with_snapshot(
            repo_with_files,
            exclude_dirs=DEFAULT_EXCLUDE_DIRS,
            extensions=TARGET_EXTENSIONS,
        )
        paths = write_snapshot_bundle(snap, records, tmp_path)

        data = json.loads(paths["snapshot"].read_text(encoding="utf-8"))
        assert data["snapshot_id"] == snap.snapshot_id
        assert data["schema_version"] == CODE_SNAPSHOT_SCHEMA_VERSION
        assert data["state"] == SnapshotState.PLANNED.value

    def test_files_jsonl_no_absolute_paths(self, repo_with_files: Path, tmp_path: Path):
        """写出的 files.jsonl 中不能含本机绝对路径。"""
        snap, records = scan_repo_with_snapshot(
            repo_with_files,
            exclude_dirs=DEFAULT_EXCLUDE_DIRS,
            extensions=TARGET_EXTENSIONS,
        )
        paths = write_snapshot_bundle(snap, records, tmp_path)

        content = paths["files"].read_text(encoding="utf-8")
        assert str(repo_with_files) not in content

    def test_files_jsonl_line_count(self, repo_with_files: Path, tmp_path: Path):
        snap, records = scan_repo_with_snapshot(
            repo_with_files,
            exclude_dirs=DEFAULT_EXCLUDE_DIRS,
            extensions=TARGET_EXTENSIONS,
        )
        paths = write_snapshot_bundle(snap, records, tmp_path)

        lines = [ln for ln in paths["files"].read_text(encoding="utf-8").splitlines() if ln]
        assert len(lines) == len(records)

    def test_output_under_snapshot_id_dir(self, repo_with_files: Path, tmp_path: Path):
        """输出必须在 <output_dir>/<snapshot_id>/ 子目录下。"""
        snap, records = scan_repo_with_snapshot(
            repo_with_files,
            exclude_dirs=DEFAULT_EXCLUDE_DIRS,
            extensions=TARGET_EXTENSIONS,
        )
        paths = write_snapshot_bundle(snap, records, tmp_path)

        expected_dir = tmp_path / snap.snapshot_id
        assert paths["snapshot"].parent == expected_dir
        assert paths["files"].parent    == expected_dir


# ---------------------------------------------------------------------------
# 语言检测
# ---------------------------------------------------------------------------

class TestDetectLanguage:
    @pytest.mark.parametrize("filename,expected", [
        ("foo.cpp",       "cpp"),
        ("foo.cc",        "cpp"),
        ("foo.cxx",       "cpp"),
        ("foo.c",         "c"),
        ("foo.h",         "c_header"),
        ("foo.hpp",       "cpp_header"),
        ("foo.hxx",       "cpp_header"),
        ("foo.inl",       "cpp_header"),
        ("foo.py",        "python"),
        ("foo.sh",        "shell"),
        ("CMakeLists.txt","cmake"),        # 文件名优先于扩展名
        ("foo.cmake",     "cmake"),
        ("foo.mk",        "makefile"),
        ("foo.proto",     "protobuf"),
        ("foo.json",      "json"),
        ("foo.yaml",      "yaml"),
        ("foo.yml",       "yaml"),
        ("foo.xml",       "xml"),
        ("foo.md",        "markdown"),
        ("foo.xyz",       "unknown"),
    ])
    def test_language(self, filename: str, expected: str):
        assert detect_language(Path(filename)) == expected

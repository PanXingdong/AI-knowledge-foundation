"""
code_snapshot.py — RepositorySnapshot 与 FileRecord 数据模型（Phase A）

职责：
  - 将 git repo 解析为具有稳定身份的 RepositorySnapshot
  - 将磁盘文件转换为 repo-relative 的 FileRecord
  - 所有 ID 均为确定性哈希，不含本机绝对路径

对应方案文档：第5章、第6章、第27.1节、第27.2节
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from agent_knowledge_hub.utils import file_sha256, sha256_text, utc_now_iso

# ---------------------------------------------------------------------------
# 版本常量
# ---------------------------------------------------------------------------

CODE_SNAPSHOT_SCHEMA_VERSION = "code-index.v1"
PARSER_VERSION_FALLBACK = "line-preserving-fallback-1.0"

# ---------------------------------------------------------------------------
# 枚举
# ---------------------------------------------------------------------------


class SnapshotState(str, Enum):
    """Snapshot 状态机（对应方案第4.6节）。"""
    PLANNED    = "planned"
    SCANNING   = "scanning"
    PARSING    = "parsing"
    CHUNKING   = "chunking"
    INDEXING   = "indexing"
    VALIDATING = "validating"
    READY      = "ready"
    ACTIVE     = "active"
    SUPERSEDED = "superseded"
    # 失败态
    FAILED_PLAN       = "failed_plan"
    FAILED_SCAN       = "failed_scan"
    FAILED_PARSE      = "failed_parse"
    FAILED_CHUNK      = "failed_chunk"
    FAILED_INDEX      = "failed_index"
    FAILED_VALIDATION = "failed_validation"


class ParserMode(str, Enum):
    """文件解析模式（对应方案第7.1节）。"""
    COMPILER_INDEXER = "compiler_indexer"
    TREE_SITTER      = "tree_sitter"
    DEDICATED        = "dedicated"
    FALLBACK         = "fallback"
    UNSUPPORTED      = "unsupported"


class SecretStatus(str, Enum):
    """Secret 扫描状态（Phase D 填充，Phase A 默认 not_scanned）。"""
    NOT_SCANNED = "not_scanned"
    CLEAN       = "clean"
    REDACTED    = "redacted"
    BLOCKED     = "blocked"


# ---------------------------------------------------------------------------
# Git 工具函数
# ---------------------------------------------------------------------------

def _git(args: list[str], cwd: Path) -> str | None:
    """运行 git 命令，返回 stdout 字符串；失败返回 None。"""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def resolve_commit_sha(repo_dir: Path) -> str | None:
    """返回完整 40 位 commit SHA（不是短哈希）。"""
    return _git(["rev-parse", "HEAD"], repo_dir)


def resolve_tree_hash(repo_dir: Path) -> str | None:
    """返回 HEAD 对应的 git tree hash。"""
    return _git(["rev-parse", "HEAD^{tree}"], repo_dir)


def resolve_branch(repo_dir: Path) -> str | None:
    """返回当前分支名；detached HEAD 时返回 None。"""
    branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], repo_dir)
    return branch if branch and branch != "HEAD" else None


def resolve_remote_url(repo_dir: Path) -> str | None:
    """返回 origin remote URL，自动剥离凭据。"""
    url = _git(["remote", "get-url", "origin"], repo_dir)
    if url:
        # 去除 https://user:pass@host 中的凭据部分
        url = re.sub(r"(https?://)([^@]+@)", r"\1", url)
    return url


def _git_file_bytes(repo_dir: Path, commit_sha: str, rel_posix: str) -> bytes | None:
    """
    从 git 对象库读取指定 commit 中某文件的字节内容。
    不读取磁盘文件，避免脏工作树污染证据内容。
    返回 None 表示文件在该 commit 中不存在或读取失败。
    """
    try:
        result = subprocess.run(
            ["git", "show", f"{commit_sha}:{rel_posix}"],
            cwd=repo_dir,
            capture_output=True,
            timeout=15,
        )
        if result.returncode == 0:
            return result.stdout
    except Exception:
        pass
    return None


def _is_worktree_dirty(repo_dir: Path) -> bool:
    """检查工作树是否有未提交的修改（包括暂存和未暂存的变更）。"""
    output = _git(["status", "--porcelain"], repo_dir)
    if output is None:
        return False   # 无 git，按非脏处理（使用 no-git- 前缀）
    return bool(output.strip())


def resolve_submodule_commits(repo_dir: Path) -> dict[str, str]:
    """返回 {submodule_relative_path: commit_sha}；无 submodule 时返回 {}。"""
    output = _git(["submodule", "status", "--recursive"], repo_dir)
    if not output:
        return {}
    result: dict[str, str] = {}
    for line in output.splitlines():
        # 格式: " <sha> <path> (<describe>)" 或 "-<sha> <path>"
        parts = line.strip().lstrip("+-").split()
        if len(parts) >= 2:
            result[parts[1]] = parts[0]
    return result


# ---------------------------------------------------------------------------
# 确定性 ID 计算
# ---------------------------------------------------------------------------

def _sha256_of(obj: Any) -> str:
    """对任意 JSON 可序列化对象计算确定性 SHA256（key 排序）。"""
    canonical = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_repo_id(repo_remote: str | None, repo_dir: Path) -> str:
    """
    仓库逻辑身份，跨机器稳定。
    - 有 remote URL → 规范化 URL 的哈希（不含 .git 后缀、不含大小写差异）
    - 无 remote URL → 绝对路径哈希（仅本机可用，降级 fallback）
    """
    if repo_remote:
        normalized = repo_remote.lower().rstrip("/")
        if normalized.endswith(".git"):
            normalized = normalized[:-4]
        source = normalized
    else:
        source = str(repo_dir.resolve())
    return "repo_" + _sha256_of(source)[:16]


def compute_index_config_hash(
    exclude_dirs: frozenset[str],
    extensions: frozenset[str],
    parser_versions: dict[str, str],
    chunk_params: dict[str, Any] | None = None,
) -> str:
    """
    相同配置 → 相同哈希，确保不同配置产生不同 snapshot。
    chunk_params 纳入哈希，防止分块策略变更后 snapshot_id 不变。
    """
    obj = {
        "exclude_dirs":    sorted(exclude_dirs),
        "extensions":      sorted(extensions),
        "parser_versions": {k: parser_versions[k] for k in sorted(parser_versions)},
        "chunk_params":    {k: chunk_params[k] for k in sorted(chunk_params)} if chunk_params else {},
    }
    return _sha256_of(obj)[:16]


def compute_snapshot_id(
    repo_id: str,
    commit_sha: str,
    submodule_commits: dict[str, str],
    index_config_hash: str,
) -> str:
    """
    snapshot_id = hash(repo_id + commit_sha + submodule_commits + index_config_hash)
    branch 不参与计算（对应方案第5.3节注意事项）。
    """
    obj = {
        "repo_id":           repo_id,
        "commit_sha":        commit_sha,
        "submodule_commits": {k: submodule_commits[k] for k in sorted(submodule_commits)},
        "index_config_hash": index_config_hash,
    }
    return "snap_" + _sha256_of(obj)[:24]


def compute_logical_file_id(repo_id: str, relative_path: str) -> str:
    """
    文件逻辑身份：同一 repo 内跨 commit 稳定。
    logical_file_id = hash(repo_id + relative_path)
    """
    return "file_" + _sha256_of({"repo_id": repo_id, "relative_path": relative_path})[:16]


def compute_file_version_id(
    snapshot_id: str,
    relative_path: str,
    content_hash: str,
) -> str:
    """
    文件版本身份：内容或所在 snapshot 变化时必须变化。
    file_version_id = hash(snapshot_id + relative_path + content_hash)
    """
    obj = {
        "snapshot_id":   snapshot_id,
        "relative_path": relative_path,
        "content_hash":  content_hash,
    }
    return "fver_" + _sha256_of(obj)[:16]


# ---------------------------------------------------------------------------
# 语言检测
# ---------------------------------------------------------------------------

_EXT_TO_LANGUAGE: dict[str, str] = {
    ".c":     "c",
    ".cc":    "cpp",
    ".cpp":   "cpp",
    ".cxx":   "cpp",
    ".c++":   "cpp",
    ".h":     "c_header",
    ".hh":    "cpp_header",
    ".hpp":   "cpp_header",
    ".hxx":   "cpp_header",
    ".inl":   "cpp_header",
    ".py":    "python",
    ".sh":    "shell",
    ".cmake": "cmake",
    ".mk":    "makefile",
    ".proto": "protobuf",
    ".json":  "json",
    ".yaml":  "yaml",
    ".yml":   "yaml",
    ".xml":   "xml",
    ".md":    "markdown",
    ".txt":   "plaintext",
}

_BINARY_EXTENSIONS: frozenset[str] = frozenset({
    ".o", ".so", ".a", ".lib", ".dll", ".exe",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico",
    ".pdf", ".zip", ".tar", ".gz", ".7z", ".bin",
})


_FILENAME_TO_LANGUAGE: dict[str, str] = {
    "cmakelists.txt": "cmake",
    "makefile":       "makefile",
    "gnumakefile":    "makefile",
}


def detect_language(path: Path) -> str:
    # 优先按完整文件名匹配（不区分大小写）
    by_name = _FILENAME_TO_LANGUAGE.get(path.name.lower())
    if by_name:
        return by_name
    return _EXT_TO_LANGUAGE.get(path.suffix.lower(), "unknown")


def _select_parser_mode(language: str, binary: bool) -> ParserMode:
    """Phase A 全部使用 fallback；binary 和 unknown 为 unsupported。"""
    if binary or language in ("unknown", "binary"):
        return ParserMode.UNSUPPORTED
    return ParserMode.FALLBACK


# ---------------------------------------------------------------------------
# 路径分类标记
# ---------------------------------------------------------------------------

_GENERATED_MARKERS: tuple[str, ...] = (
    "generated", "gen", "autogen", "auto_gen", "moc_", "_moc",
)
_VENDORED_MARKERS: tuple[str, ...] = (
    "vendor", "third_party", "3rdparty", "thirdparty", "external",
    "KanziEngine", "someip", "ClusterHMIPrebuilts",
)


def _is_generated(rel_parts: tuple[str, ...]) -> bool:
    return any(
        any(marker in part.lower() for marker in _GENERATED_MARKERS)
        for part in rel_parts
    )


def _is_vendored(rel_parts: tuple[str, ...]) -> bool:
    return any(
        any(marker in part for marker in _VENDORED_MARKERS)
        for part in rel_parts
    )


# ---------------------------------------------------------------------------
# 数据类
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RepositorySnapshot:
    """
    代码库在某个 commit + 配置下的不可变快照标识。
    对应方案文档第 5 章、第 27.1 节。
    """
    snapshot_id:        str
    schema_version:     str
    repo_id:            str
    repo_remote:        str | None       # 不含凭据的 remote URL
    branch:             str | None       # 可追溯标注，不参与 snapshot_id
    commit_sha:         str              # 完整 40 位 SHA
    tree_hash:          str | None
    submodule_commits:  dict[str, str]   # {submodule_path: commit_sha}
    index_config_hash:  str
    parser_versions:    dict[str, str]   # {parser_name: version}
    parent_snapshot_id: str | None
    state:              str              # SnapshotState 值
    created_at:         str              # UTC ISO-8601

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False, sort_keys=True)


@dataclass(frozen=True)
class FileRecord:
    """
    代码仓中单个文件在某个 snapshot 内的版本记录。
    对应方案文档第 6 章、第 27.2 节。

    不变量：
      - relative_path 永远是 POSIX 相对路径，不含绝对路径
      - logical_file_id 在同一 repo 内跨 commit 稳定
      - file_version_id 在内容或 snapshot 变化时必须变化
    """
    logical_file_id:  str
    file_version_id:  str
    snapshot_id:      str
    repo_id:          str
    relative_path:    str         # POSIX，相对 repo root，禁止绝对路径
    language:         str
    parser_mode:      str         # ParserMode 值
    content_hash:     str         # 原始文件字节的 SHA-256
    size_bytes:       int
    encoding:         str | None  # 成功识别的编码；binary 时为 None
    generated:        bool
    vendored:         bool
    binary:           bool
    ownership_ids:    list[str]   # Phase D 填充，Phase A 为 []
    acl_tags:         list[str]   # Phase D 填充，Phase A 为 []
    secret_status:    str         # SecretStatus 值，Phase A 默认 not_scanned
    diagnostics:      list[str]   # 解析/编码诊断码

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# 工厂：RepositorySnapshot
# ---------------------------------------------------------------------------

def create_snapshot(
    repo_dir: Path,
    *,
    exclude_dirs: frozenset[str],
    extensions: frozenset[str],
    parent_snapshot_id: str | None = None,
    chunk_params: dict[str, Any] | None = None,
) -> RepositorySnapshot:
    """
    解析 git 元数据，生成处于 PLANNED 状态的 RepositorySnapshot。

    相同 repo_dir + 相同 commit + 相同配置 → 相同 snapshot_id。
    产物不含本机绝对路径。
    chunk_params 纳入 index_config_hash，确保分块策略变更时 snapshot_id 也变化。
    """
    repo_dir = repo_dir.resolve()
    if not repo_dir.is_dir():
        raise RuntimeError(f"repo_dir 不存在：{repo_dir}")

    repo_remote       = resolve_remote_url(repo_dir)
    commit_sha        = resolve_commit_sha(repo_dir)
    tree_hash         = resolve_tree_hash(repo_dir)
    branch            = resolve_branch(repo_dir)
    submodule_commits = resolve_submodule_commits(repo_dir)

    # 无 git 时使用路径哈希作为 commit 替代（降级，标注为 no-git-）
    if commit_sha is None:
        commit_sha = "no-git-" + _sha256_of(str(repo_dir))[:16]

    repo_id = compute_repo_id(repo_remote, repo_dir)

    parser_versions: dict[str, str] = {"fallback": PARSER_VERSION_FALLBACK}
    index_config_hash = compute_index_config_hash(
        exclude_dirs, extensions, parser_versions, chunk_params
    )
    snapshot_id = compute_snapshot_id(
        repo_id, commit_sha, submodule_commits, index_config_hash
    )

    return RepositorySnapshot(
        snapshot_id=snapshot_id,
        schema_version=CODE_SNAPSHOT_SCHEMA_VERSION,
        repo_id=repo_id,
        repo_remote=repo_remote,
        branch=branch,
        commit_sha=commit_sha,
        tree_hash=tree_hash,
        submodule_commits=submodule_commits,
        index_config_hash=index_config_hash,
        parser_versions=parser_versions,
        parent_snapshot_id=parent_snapshot_id,
        state=SnapshotState.PLANNED.value,
        created_at=utc_now_iso(),
    )


# ---------------------------------------------------------------------------
# 工厂：FileRecord
# ---------------------------------------------------------------------------

def _detect_encoding(abs_path: Path) -> str | None:
    """尝试常见编码，返回第一个成功的；全部失败返回 None。"""
    for enc in ("utf-8", "utf-8-sig", "gbk", "gb18030", "latin-1"):
        try:
            abs_path.read_text(encoding=enc)
            return enc
        except (UnicodeDecodeError, PermissionError):
            continue
    return None


def _detect_encoding_from_bytes(data: bytes) -> str | None:
    """从字节内容尝试常见编码，返回第一个成功的；全部失败返回 None。"""
    for enc in ("utf-8", "utf-8-sig", "gbk", "gb18030", "latin-1"):
        try:
            data.decode(enc)
            return enc
        except (UnicodeDecodeError, LookupError):
            continue
    return None


def create_file_record(
    abs_path: Path,
    repo_dir: Path,
    snapshot: RepositorySnapshot,
    *,
    source_bytes: bytes | None = None,
) -> FileRecord:
    """
    为单个文件构建 FileRecord。
    abs_path 必须在 repo_dir 内部；relative_path 永远是 POSIX 相对路径。

    source_bytes：若提供则使用该字节内容计算哈希和大小，而非读取磁盘文件。
    用于脏工作树场景：通过 git show 读取 commit 版本内容，保证 Evidence 真实性。
    """
    abs_path = abs_path.resolve()
    repo_dir = repo_dir.resolve()

    # Symlink 越界检测：拒绝指向 repo 外部的 symlink
    if abs_path.is_symlink():
        real = abs_path.resolve()
        try:
            real.relative_to(repo_dir)
        except ValueError:
            raise ValueError(
                f"Symlink 越界：{abs_path} -> {real} 指向 repo 外部，拒绝索引"
            )

    try:
        rel = abs_path.relative_to(repo_dir)
    except ValueError:
        raise ValueError(
            f"文件路径越界：{abs_path} 不在 repo_dir {repo_dir} 内"
        )

    relative_path = rel.as_posix()   # 关键：只用相对路径，不含绝对路径
    rel_parts     = rel.parts

    is_binary_ext = abs_path.suffix.lower() in _BINARY_EXTENSIONS

    if source_bytes is not None:
        # 使用 git 内容：哈希和大小来自 git 对象，不来自磁盘
        content_hash = hashlib.sha256(source_bytes).hexdigest()
        size_bytes   = len(source_bytes)
        if is_binary_ext:
            encoding = None
            binary   = True
        else:
            encoding = _detect_encoding_from_bytes(source_bytes)
            binary   = (encoding is None)
    else:
        # 使用磁盘文件（需确保工作树干净）
        content_hash = file_sha256(abs_path)
        size_bytes   = abs_path.stat().st_size
        if is_binary_ext:
            encoding = None
            binary   = True
        else:
            encoding = _detect_encoding(abs_path)
            binary   = (encoding is None)

    language    = detect_language(abs_path) if not binary else "binary"
    parser_mode = _select_parser_mode(language, binary)

    diagnostics: list[str] = []
    if binary and not is_binary_ext:
        diagnostics.append("encoding_undetectable")
    if language == "unknown":
        diagnostics.append("language_unknown")

    return FileRecord(
        logical_file_id=compute_logical_file_id(snapshot.repo_id, relative_path),
        file_version_id=compute_file_version_id(
            snapshot.snapshot_id, relative_path, content_hash
        ),
        snapshot_id=snapshot.snapshot_id,
        repo_id=snapshot.repo_id,
        relative_path=relative_path,
        language=language,
        parser_mode=parser_mode.value,
        content_hash=content_hash,
        size_bytes=size_bytes,
        encoding=encoding,
        generated=_is_generated(rel_parts),
        vendored=_is_vendored(rel_parts),
        binary=binary,
        ownership_ids=[],
        acl_tags=[],
        secret_status=SecretStatus.NOT_SCANNED.value,
        diagnostics=diagnostics,
    )

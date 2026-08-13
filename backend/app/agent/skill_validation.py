"""用户上传技能的校验（Phase 27）。

复用 deepagents 自带的 SKILL.md frontmatter 解析器（同 Phase 26 内置技能走的是同一套
规范），不重新发明校验规则；这里只加一层「拒绝而不是静默丢弃」——内置技能解析失败只是
少一条技能、日志警告即可，但用户主动上传时必须让用户知道到底哪里错了。
"""

from __future__ import annotations

from app.config import settings


class SkillValidationError(Exception):
    """用户上传的 SKILL.md 内容不合法，携带可展示给用户的原因。"""


def parse_and_validate(content: str) -> tuple[str, str]:
    """解析并校验一段 SKILL.md 正文，返回 (name, description)。

    Raises:
        SkillValidationError: 超出大小限制、缺少必需 frontmatter 字段、或 name 不合法。
    """
    if len(content.encode("utf-8")) > settings.user_skill_max_bytes:
        msg = f"技能正文超出大小限制（上限 {settings.user_skill_max_bytes} 字节）"
        raise SkillValidationError(msg)

    name = _extract_frontmatter_name(content)
    if not name:
        msg = "缺少 YAML frontmatter 或缺少 name 字段，请参考内置技能的格式（---\\nname: ...\\ndescription: ...\\n---）"
        raise SkillValidationError(msg)

    from deepagents.middleware.skills import _parse_skill_metadata, _validate_skill_name

    is_valid, error = _validate_skill_name(name, name)
    if not is_valid:
        msg = f"技能名不合法：{error}"
        raise SkillValidationError(msg)

    skill_path = f"/user/{name}/SKILL.md"
    metadata = _parse_skill_metadata(content=content, skill_path=skill_path, directory_name=name)
    if metadata is None:
        msg = "SKILL.md 解析失败：请检查 frontmatter 里 name/description 是否都填写了"
        raise SkillValidationError(msg)
    return metadata["name"], metadata["description"]


def _assert_real_unpacked_size(zf: "zipfile.ZipFile", entries: list) -> None:
    """按**真实解压字节**累加校验，超限立即中断（Phase 69 防 zip 炸弹）。

    zip 头里的 `file_size` 是攻击者可写的，改成 10 字节就能骗过 sum() 快筛。
    这里分块读、边读边计数，超限当场停——不会把整个成员解压进内存再发现超了。
    """
    import zipfile

    limit = settings.user_skill_max_zip_bytes
    total = 0
    for info in entries:
        try:
            with zf.open(info) as fh:
                while chunk := fh.read(64 * 1024):
                    total += len(chunk)
                    if total > limit:
                        msg = f"zip 解压后总大小超出上限（上限 {limit} 字节）"
                        raise SkillValidationError(msg)
        except (zipfile.BadZipFile, OSError, EOFError) as e:
            # CRC 不符/成员损坏——申报值与真实内容不一致本身就是可疑信号
            msg = "zip 内容损坏或与声明不符"
            raise SkillValidationError(msg) from e


def parse_and_validate_zip(data: bytes) -> tuple[str, str, dict[str, str]]:
    """解析并校验一个 zip 多文件技能包，返回 (name, description, files)。

    `files` 是 {相对路径: 文本内容}（POSIX 相对路径，含 "SKILL.md" 自身）。

    Raises:
        SkillValidationError: 不是合法 zip / 总大小或文件数超限 / 路径逃逸（zip-slip）/
            含非 UTF-8 文本文件 / 缺少 SKILL.md / SKILL.md 本身校验不过。
    """
    import zipfile
    from io import BytesIO
    from pathlib import PurePosixPath

    try:
        zf = zipfile.ZipFile(BytesIO(data))
    except zipfile.BadZipFile as e:
        msg = "不是合法的 zip 文件"
        raise SkillValidationError(msg) from e

    entries = [i for i in zf.infolist() if not i.is_dir()]
    if not entries:
        msg = "zip 里没有文件"
        raise SkillValidationError(msg)
    if len(entries) > settings.user_skill_max_zip_files:
        msg = f"zip 里文件数超出上限（上限 {settings.user_skill_max_zip_files} 个）"
        raise SkillValidationError(msg)
    # Phase 69：不能信 zip 头里申报的 file_size（可篡改成 10 字节骗过总量校验）。
    # 先按申报值快筛（便宜），真实字节数在下面逐个成员**流式解压时**累加校验。
    if sum(i.file_size for i in entries) > settings.user_skill_max_zip_bytes:
        msg = f"zip 解压后总大小超出上限（上限 {settings.user_skill_max_zip_bytes} 字节）"
        raise SkillValidationError(msg)
    _assert_real_unpacked_size(zf, entries)

    # 路径校验：拒绝绝对路径 / ".." 逃逸 —— 这些文件最终会被拼成
    # "/user/{name}/{relpath}" 虚拟路径种进技能状态；不校验的话，恶意路径可能拼出
    # "/main/xxx/SKILL.md" 这类落到内置技能命名空间的虚拟路径，篡改/冒充内置技能
    # （所有用户技能与内置技能最终合并进同一个 files 种子 dict）。
    raw_files: dict[str, str] = {}
    for info in entries:
        posix_name = info.filename.replace("\\", "/")
        parts = PurePosixPath(posix_name).parts
        if not parts or posix_name.startswith("/") or ".." in parts or any(p in ("", ".") for p in parts):
            msg = f"zip 里的文件路径不合法：{info.filename}"
            raise SkillValidationError(msg)
        try:
            text = zf.read(info).decode("utf-8")
        except UnicodeDecodeError as e:
            msg = f"文件 {info.filename} 不是 UTF-8 文本（暂不支持二进制文件）"
            raise SkillValidationError(msg) from e
        raw_files[posix_name] = text

    # 兼容"压缩了外层文件夹"的常见习惯：根目录没有 SKILL.md，但唯一顶层目录里有，
    # 就剥掉这层前缀。
    if "SKILL.md" not in raw_files:
        top_dirs = {name.split("/", 1)[0] for name in raw_files if "/" in name}
        if len(top_dirs) == 1:
            prefix = next(iter(top_dirs)) + "/"
            if f"{prefix}SKILL.md" in raw_files:
                raw_files = {
                    name[len(prefix):]: content
                    for name, content in raw_files.items()
                    if name.startswith(prefix)
                }

    if "SKILL.md" not in raw_files:
        msg = "zip 根目录下没有找到 SKILL.md"
        raise SkillValidationError(msg)

    name, description = parse_and_validate(raw_files["SKILL.md"])

    # 双重保险：拼出虚拟路径后仍必须落在自己的命名空间内
    for relpath in raw_files:
        vpath = f"/user/{name}/{relpath}"
        if not vpath.startswith(f"/user/{name}/"):
            msg = f"文件路径不合法：{relpath}"
            raise SkillValidationError(msg)

    return name, description, raw_files


def _extract_frontmatter_name(content: str) -> str | None:
    """粗略提取 frontmatter 里的 name（先于完整解析用，给校验失败一个更早的出口）。"""
    import re

    import yaml

    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
    if not match:
        return None
    try:
        data = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    name = str(data.get("name", "")).strip()
    return name or None

## [ERR-20260516-001] python_command_unavailable

**Logged**: 2026-05-16T22:28:51+08:00
**Priority**: medium
**Status**: pending
**Area**: tests

### Summary
当前 Windows 环境未提供 python、py、python3、uv 或 ruff 命令，导致本地单元测试和格式化验证无法执行。

### Error
```powershell
python : The term 'python' is not recognized as the name of a cmdlet, function, script file, or operable program.
py : The term 'py' is not recognized as the name of a cmdlet, function, script file, or operable program.
```

### Context
- 尝试执行 `python -m unittest discover -s tests`。
- 尝试执行 `py -m unittest discover -s tests`。
- 使用 `Get-Command python, py, python3, uv, ruff -ErrorAction SilentlyContinue` 未发现可用命令。
- 尝试执行 `git diff -- .trae/specs/echo-cave-integration/tasks.md tests/test_core.py .learnings/ERRORS.md` 时也发现当前环境缺少 git 命令。

### Suggested Fix
在运行环境安装 Python 与 Git 并加入 PATH，或提供项目固定验证命令和解释器路径。

### Metadata
- Reproducible: yes
- Related Files: tests/test_core.py

---

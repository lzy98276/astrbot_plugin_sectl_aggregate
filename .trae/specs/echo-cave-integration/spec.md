# 回声洞功能集成 Spec

## Why
需要为 AstrBot 插件实现回声洞功能,支持用户通过中文指令进行回声洞的投稿、查询、编辑和删除操作,同时集成 QQ 绑定认证功能,并使用 HTML 模板渲染美观的菜单图片。

## What Changes
- 实现回声洞核心功能模块(投稿、查询、编辑、删除)
- 实现 QQ 绑定认证模块
- 实现 HTML 渲染菜单功能
- 实现中文指令系统(回声洞 查看/投稿/编辑/删除)
- 实现文件分类组织结构

## Impact
- Affected specs: 回声洞管理、QQ 绑定认证、HTML 图片渲染、指令系统
- Affected code: main.py(主要插件文件)、新增模块文件

## ADDED Requirements

### Requirement: 回声洞指令系统
系统 SHALL 提供一组中文回声洞指令,通过 `/回声洞` 或 `回声洞` 触发主功能。

#### Scenario: 用户发送帮助指令
- **WHEN** 用户发送 `help` 或 `/help`
- **THEN** 系统通过 HTML 模板渲染菜单图片并发送给用户,显示所有可用指令

#### Scenario: 用户投稿回声洞
- **WHEN** 用户发送 `回声洞 投稿 内容文本`
- **THEN** 系统调用投稿 API,认证成功后创建回声洞并返回成功响应

#### Scenario: 用户查询回声洞
- **WHEN** 用户发送 `回声洞 查看` 或 `回声洞 查看 编号`
- **THEN** 系统调用查询 API,返回随机或指定编号的回声洞内容

#### Scenario: 用户编辑自己的回声洞
- **WHEN** 用户发送 `回声洞 编辑 编号 新内容`
- **THEN** 系统验证用户身份后调用编辑 API 更新回声洞

#### Scenario: 用户删除自己的回声洞
- **WHEN** 用户发送 `回声洞 删除 编号`
- **THEN** 系统验证用户身份后调用删除 API 删除回声洞

### Requirement: QQ 绑定认证
系统 SHALL 实现 QQ 绑定认证流程,确保用户身份验证后才能进行写操作。

#### Scenario: 用户查询绑定状态
- **WHEN** 用户发送 `绑定状态`
- **THEN** 系统查询 QQ 绑定状态并返回给用户

#### Scenario: 用户申请绑定 QQ
- **WHEN** 用户发送 `绑定 QQ号`
- **THEN** 系统申请临时 Key 并指导用户完成绑定流程

### Requirement: HTML 菜单渲染
系统 SHALL 使用 HTML + Jinja2 模板渲染美观的菜单图片。

#### Scenario: 渲染帮助菜单
- **WHEN** 用户请求帮助菜单
- **THEN** 系统使用 HTML 模板渲染指令列表图片并返回

### Requirement: 文件分类组织
代码 SHALL 按功能模块分类组织,保持清晰的目录结构。

#### Scenario: 项目文件结构
- 主插件文件: main.py(入口和指令路由)
- API 模块: api/ 目录(echo_cave.py, qq_binding.py)
- 模板模块: templates/ 目录(menu.html 等)
- 配置模块: config.py(配置管理)

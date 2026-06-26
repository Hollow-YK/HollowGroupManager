# QFun 版开发指南

本文档为 QFun 版专属开发指南的精简入口。完整的开发约定和 AI 开发提示见 [QFun/AGENTS.md](../../../QFun/AGENTS.md)，开发注意事项和检查清单见 [pitfalls.md](pitfalls.md)。

## 运行环境

| 项 | 说明 |
| --- | --- |
| 引擎 | Modern BeanShell（Java 8+ 语法，**不支持注解**） |
| 宿主 | QFun Plugin for Android QQ |
| 类加载器 | 持有宿主 QQ 和模块的 `classLoader` |
| 线程 | 事件回调在 **IO 线程**；UI 操作需切换主线程 |
| API | 全局函数，无需 import，脚本任意位置直接调用 |

详见 [SDK/QFdocs/QFun_Plugin_API.md](../../../SDK/QFdocs/QFun_Plugin_API.md)。

## 关键约定

> 详细说明见 [QFun/AGENTS.md](../../../QFun/AGENTS.md)。此处仅列出要点。

### BeanShell 类型陷阱

**数值从 Map 取出时，始终用 `String.valueOf()` + 包装类型 `parseXxx`，不能直接 cast。**

```java
// ✅ 正确
r.id = Integer.parseInt(String.valueOf(map.get("id")));
r.sender = Long.parseLong(String.valueOf(map.get("sender")));

// ❌ 错误 — bsh.Primitive 转型异常
r.id = (int) map.get("id");
```

### 空值防护

```java
r.reason = map.get("reason") != null ? map.get("reason").toString() : "";
```

### 线程安全

`onMsg` 和 `joinGroup` 可能在不同线程并发：

```java
List<PunishRecord> records = Collections.synchronizedList(new ArrayList<>());

// 双重检查锁定初始化
if (!initialized) {
    synchronized (initLock) {
        if (!initialized) { init(); initialized = true; }
    }
}
```

### API 调用模式

所有 QFun API 为全局函数，支持属性直接访问：

```java
String text = msgData.msg;
int type = msgData.type;      // 2=群聊, 1=私聊
String peerUin = msgData.peerUin;

// API 调用 — 全局函数，无需 context
List members = getGroupMemberList(groupCode);
shutUp(groupCode, qq, duration);
kickGroup(groupCode, qq, false);
sendMsg(peerUin, message, 2);
```

## 常见任务

### 添加新指令

1. 在 `CommandConfig.defaults()` 中添加命令配置（internal name, names, min_level）
2. 在 `onMsg()` 的 switch 中添加 `case "新内部名":` 分支
3. 实现 `cmdXxx()` 方法
4. 在 `initHelpMaps()` 中的 `CMD_DESC` / `CMD_FORMAT` / `CMD_EXAMPLES` / `CMD_DETAIL` 添加帮助条目

### 添加新数据持久化

1. 定义数据模型类（遵循 `toMap()`/`fromMap()` 模式）
2. 添加 `loadConfigXxx(name)` / `saveConfigXxx(name, data)` 方法
3. 在 `saveConfig(name)` 中调用新的保存方法
4. 在 `init()` 的配置加载循环中加载新数据

### 添加新配置项

1. 在 `config.properties` 中添加键值
2. 在 `checkAndRepairConfig()` 中添加默认值处理
3. 更新 README

### 命令配置（command.json）

全局 `data/command.json` 定义默认命令行为。各配置覆盖项写入 `data/<配置名>/command.json`。

```json
{
  "commands": {
    "punish_do": {
      "enabled": true,
      "names": ["p", "punish"],
      "minLevel": 1
    }
  }
}
```

`names` 支持多个命令名指向同一功能；`minLevel` 控制所需最低权限等级；`sub` 支持递归子命令配置。

## 相关文档

| 文档 | 内容 |
| --- | --- |
| [QFun/AGENTS.md](../../../QFun/AGENTS.md) | QFun 版完整开发指南 + AI 开发提示 |
| [pitfalls.md](pitfalls.md) | QFun 开发注意事项与检查清单 |
| [../index.md](../index.md) | 共享架构与配置管理 |
| [../comparison.md](../../comparison.md) | QFun vs OneBot11 详细对比 |

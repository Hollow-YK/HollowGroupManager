# QFun 版开发注意事项

本文档整理了 OneBot11 → QFun 架构同步过程中遇到的所有问题，供后续 QFun 版开发参考。

## 1. BeanShell 类定义必须前向声明

**问题**：Java 允许类在定义之前被引用，但 BeanShell 是解释型执行，类**必须先定义后使用**。

**错误示例**：
```java
CommandConfig globalCommands = CommandConfig.defaults();  // 行 34，此时 CommandConfig 未定义

// ... 很多代码之后 ...
class CommandConfig { ... }  // 行 442
```

**错误信息**：`Class: CommandConfig not found in namespace`

**正确做法**：所有类定义放在文件最前面（import 之后），按依赖顺序排列。

```java
// 正确顺序：
class ConfigInfo { ... }       // 无依赖
class CommandItem { ... }      // 无依赖
class CommandConfig { ... }    // 依赖 CommandItem
class PunishRecord { ... }     // 无依赖
class BlacklistItem { ... }    // 无依赖
class ConfigState { ... }      // 依赖以上所有类
```

---

## 2. Android import 必须写完整包名

**问题**：`import android.graphics.Bitmap;` 如果误写成 `import Bitmap;`，BeanShell 无法在默认包中找到该类。

**错误信息**：`Class: Bitmap not found in namespace`

**正确做法**：
```java
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Typeface;
```

**注意**：批量替换字符串时小心不要把 `android.graphics.` 前缀也替换掉。

---

## 3. BeanShell 数字类型：int/float 混合运算产生 double

**问题**：Android `Canvas.drawText()` 有多个重载，但**没有 `(String, double, int, Paint)` 签名**。BeanShell 的类型系统与标准 Java 不同——`int` 和 `float` 混合运算会被提升为 `double`。

**错误信息**：`Method drawText(String, double, int, Paint) not found in class 'android.graphics.Canvas'`

**错误示例**：
```java
float tw = paint.measureText(text);
canvas.drawText(text, (imgWidth - tw) / 2f, ry, paint);
// imgWidth 是 int, tw 是 float → 结果变成 double
// ry 是 int → 签名变成 (String, double, int, Paint) → 不存在
```

**正确做法**：保持所有坐标参数类型一致。

**方案 A**（推荐）：全部使用 `int`，用 `(int)` 强转浮点结果。
```java
canvas.drawText(text, (int)((imgWidth - tw) / 2), ry, paint);
```

**方案 B**：全部使用 `float`，显式转换所有坐标。
```java
float x = (float)(imgWidth - tw) / 2f;
float y = (float) ry;
canvas.drawText(text, x, y, paint);
```

**适用范围**：不仅 `drawText`，`drawLine`、`drawRoundRect` 等所有 Canvas 方法都有此问题。

---

## 4. 禁止 Double-Brace 初始化 `{{ }}`

**问题**：`new LinkedHashMap<String, String>() {{ put("k", "v"); }}` 在 Java 中创建匿名内部类。BeanShell 的匿名类加载机制与标准 Java 不同，会导致运行时错误。

**错误示例**：
```java
Map<String, String> CMD_DESC = new LinkedHashMap<String, String>() {{
    put("help", "查看帮助");
    put("punish_do", "处罚成员");
}};
```

**正确做法**：在 `init()` 中逐行 `.put()`。
```java
Map<String, String> CMD_DESC;

void initHelpMaps() {
    CMD_DESC = new LinkedHashMap<String, String>();
    CMD_DESC.put("help", "查看帮助");
    CMD_DESC.put("punish_do", "处罚成员");
}
```

---

## 5. `Paint.Style` 用后必须恢复

**问题**：绘完卡片边框后将 `Paint.Style` 设为 `STROKE`，忘记恢复 `FILL`，导致后续文字变成空心（描边不填充）。

**错误示例**：
```java
paint.setStyle(Paint.Style.STROKE);
canvas.drawRoundRect(..., paint);  // 画边框
// 忘记恢复 FILL → 后续所有 drawText 都是空心字
```

**正确做法**：
```java
paint.setStyle(Paint.Style.FILL);
canvas.drawRoundRect(..., paint);  // 填充背景

paint.setStyle(Paint.Style.STROKE);
canvas.drawRoundRect(..., paint);  // 边框

paint.setStyle(Paint.Style.FILL);  // ← 必须恢复
paint.setStrokeWidth(1f);          // ← 也恢复画笔宽度
```

---

## 6. 文字定位算法：沿袭原版 `cy - offset` 模式

**问题**：原版的 `generateHelpImage` 使用"行底部 - 偏移"定位文字基线（`cy - offset`），重构时误改为行顶部定位，导致所有文字偏移。

**原版算法**（正确）：
```java
int cy = divY + 28;
for (...) {
    switch (prefix) {
        case '#': cy += 42; canvas.drawText(text, x, cy - 12, paint); break;
        case '>': cy += 38; canvas.drawText(text, x, cy - 10, paint); break;
        case '-': cy += 34; canvas.drawText(text, x, cy - 9, paint);  break;
        case '~': cy += 30; canvas.drawText(text, x, cy - 8, paint);  break;
        case '!': cy += 34; canvas.drawText(text, x, cy - 9, paint);  break;
    }
}
```

**各前缀的字体大小和偏移量对照**：

| 前缀 | 字体大小 | 行高 | 偏移 | 含义 |
|------|---------|------|------|------|
| `=` `#` | 22sp | 42 | 12 | 标题/分段 |
| `>` | 20sp | 38 | 10 | 命令格式 |
| `-` | 19sp | 34 | 9 | 描述 |
| `~` | 18sp | 30 | 8 | 示例 |
| `!` | 19sp | 34 | 9 | 警告 |

**不要改动这些数值**，它们与字体度量精确匹配。

---

## 7. 顶层执行代码必须放在所有函数定义之后

**问题**：BeanShell 逐行执行，函数调用在运行时解析。如果顶层代码调用的函数内部又引用了尚未定义的函数，会失败。

**错误示例**：
```java
// 顶层执行代码（行 470）
try { checkAndRepairDataFiles(); } catch (Exception e) {}

// checkAndRepairDataFiles 内部调用 saveGlobalCommands()
// 但 saveGlobalCommands 在行 580 才定义 → 运行时找不到
```

**正确做法**：所有 import、类定义、函数定义放前面，顶层执行代码放**文件末尾**（`unLoadPlugin()` 之前）。

```
 1. import
 2. class 定义（按依赖顺序）
 3. 全局变量声明
 4. 所有函数定义
 5. 顶层执行代码（放在这里）
 6. unLoadPlugin()
```

---

## 8. superAdmins 配置注意事项

**问题**：`config.properties` 中的 `superAdmins` 必须填入**发指令者的 QQ 号**，不是 Bot 的 QQ 号。

```properties
# 正确：填你自己发消息的 QQ 号
superAdmins=2590192626

# 如果需要多人管理
superAdmins=2590192626,123456789
```

**代码中读取**：
```java
// config.properties 中属性名是 superAdmins（驼峰）
String superAdminsVal = configProps.getProperty("superAdmins");
```

**调试技巧**：如果不确定 `superAdmins` 是否生效，查看 `info.log` 中的启动日志。若看到 `⚠ 未配置超级管理员QQ`，说明配置未读取成功。

---

## 9. 权限等级默认值陷阱

**问题**：`bestLevel` 初始化为 `0`（超级管理员）而非 `-1`（无权限），导致不在权限表的人意外获得最高权限。

```java
// 错误
int bestLevel = 0;  // 默认给超管权限！
if (!superAdmins.contains(senderId)) {
    for (int lv : cfgLevels.values()) {
        if (lv > bestLevel) bestLevel = lv;
    }
}

// 正确
int bestLevel = superAdmins.contains(senderId) ? 0 : -1;
if (bestLevel != 0) {
    for (int lv : cfgLevels.values()) {
        if (lv > bestLevel) bestLevel = lv;
    }
}
```

**原则**：任何权限相关的变量，默认值必须是 `-1`（无权限），绝不默认给 `0`。

---

## 10. 卡片圆角矩形：Android Canvas 的 `drawRoundRect`

卡片背景和边框用两次 `drawRoundRect` 实现：

```java
// 填充背景
paint.setStyle(Paint.Style.FILL);
paint.setColor(bgColor);
canvas.drawRoundRect(x0, y0, x1, y1, rx, ry, paint);

// 描边
paint.setStyle(Paint.Style.STROKE);
paint.setStrokeWidth(1f);
paint.setColor(borderColor);
canvas.drawRoundRect(x0, y0, x1, y1, rx, ry, paint);

// 必须恢复
paint.setStyle(Paint.Style.FILL);
paint.setStrokeWidth(1f);
```

所有坐标参数传 `float`（避免 int/float 混合）。圆角半径 `rx` `ry` 写 `14f`，不写 `14`。

---

## 检查清单

QFun 版开发/修改代码后，对照检查：

- [ ] 所有类是否在 import 之后、全局变量之前定义？
- [ ] 类定义顺序是否满足依赖关系？
- [ ] import 是否都是完整包名？
- [ ] 有没有 `{{ }}` 双括号初始化？
- [ ] Canvas 绘制代码是否避免了 int/float 混合运算？
- [ ] `Paint.Style.STROKE` 之后是否恢复了 `FILL`？
- [ ] 顶层执行代码是否放在文件末尾？
- [ ] 权限默认值是否为 `-1` 而非 `0`？
- [ ] `generateHelpImage` 是否沿袭 `cy - offset` 定位模式？

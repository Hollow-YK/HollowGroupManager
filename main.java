// HollowGroupManager - 多群联动管理Bot
// Copyright (C) 2026  Hollow-YK
//
// This program is free software: you can redistribute it and/or modify
// it under the terms of the GNU Affero General Public License as published
// by the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.
//
// This program is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
// GNU Affero General Public License for more details.
//
// You should have received a copy of the GNU Affero General Public License
// along with this program.  If not, see <https://www.gnu.org/licenses/>.

import java.io.*;
import java.util.*;
import java.text.SimpleDateFormat;
import java.util.regex.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Typeface;

// ==================== 全局数据与配置 ====================
List<String> wakeWords;
Set<String> superAdmins;
String dataDirPath;

final Object dataLock = new Object();
Map<String, ManagementGroup> groups = Collections.synchronizedMap(new LinkedHashMap<>());
List<PunishRecord> records = Collections.synchronizedList(new ArrayList<>());
Map<Integer, PunishRecord> recordsById = Collections.synchronizedMap(new LinkedHashMap<>());
Map<String, Integer> permissions = new ConcurrentHashMap<>();
List<BlacklistItem> blacklist = Collections.synchronizedList(new ArrayList<>());
AtomicInteger nextPunishRecordId = new AtomicInteger(1);

boolean initialized = false;
final Object initLock = new Object();

SimpleDateFormat sdf = new SimpleDateFormat("yyyy-MM-dd HH:mm:ss");

// ==================== JSON读写（使用org.json） ====================

// ==================== 启动时配置与数据完整性检查 ====================

void checkAndRepairConfig() {
    File configFile = new File(pluginPath + "/config.properties");
    boolean configNeedRepair = false;
    Properties configProps = new Properties();

    if (!configFile.exists()) {
        log("info.log", "配置文件 config.properties 不存在，创建默认配置");
        qqToast(2, "已创建默认配置");
        configNeedRepair = true;
    } else {
        try {
            FileReader reader = new FileReader(configFile);
            configProps.load(reader);
            reader.close();
        } catch (Exception e) {
            log("info.log", "配置文件读取失败(" + e.getMessage() + ")，备份后重建");
            File bak = new File(pluginPath + "/config.properties.bak");
            if (bak.exists()) bak.delete();
            configFile.renameTo(bak);
            qqToast(1, "配置已损坏，已备份重建");
            configNeedRepair = true;
        }
    }

    String wakeWordsVal = configProps.getProperty("wakeWords");
    if (wakeWordsVal == null || wakeWordsVal.trim().isEmpty()) {
        log("info.log", "配置项 wakeWords 无效，使用默认值 /,!,。");
        wakeWordsVal = "/,!,。";
        configNeedRepair = true;
    }

    String superAdminsVal = configProps.getProperty("superAdmins");
    if (superAdminsVal != null && superAdminsVal.contains("你的QQ号")) {
        log("info.log", "检测到旧版占位符 superAdmins=你的QQ号，已清空");
        qqToast(0, "superAdmins占位符已清空");
        superAdminsVal = "";
        configNeedRepair = true;
    }
    if (superAdminsVal == null) {
        superAdminsVal = "";
        configNeedRepair = true;
    }

    String dataDirVal = configProps.getProperty("dataDir");
    if (dataDirVal == null || dataDirVal.trim().isEmpty()) {
        log("info.log", "配置项 dataDir 无效，使用默认值 data");
        dataDirVal = "data";
        configNeedRepair = true;
    }

    if (configNeedRepair) {
        try {
            PrintWriter out = new PrintWriter(new FileWriter(pluginPath + "/config.properties"));
            out.println("# HollowGroupManager Configuration");
            out.println("# Wake-up words, comma-separated");
            out.println("wakeWords=" + wakeWordsVal.trim());
            out.println("# Super admin QQ numbers, comma-separated");
            out.println("superAdmins=" + superAdminsVal.trim());
            out.println("# Data directory (relative to plugin path)");
            out.println("dataDir=" + dataDirVal.trim());
            out.close();
        } catch (Exception e) {
            log("error.log", "写入配置文件失败: " + e.getMessage());
        }
    }

    wakeWords = new ArrayList<>(Arrays.asList(wakeWordsVal.trim().split(",")));

    superAdmins = new HashSet<>();
    if (!superAdminsVal.trim().isEmpty()) {
        String[] parts = superAdminsVal.trim().split(",");
        for (int i = 0; i < parts.length; i++) {
            String trimmed = parts[i].trim();
            if (!trimmed.isEmpty()) superAdmins.add(trimmed);
        }
    }

    dataDirPath = pluginPath + "/" + dataDirVal.trim();

    if (superAdmins.isEmpty()) {
        log("info.log", "⚠ 未配置超级管理员QQ (superAdmins)，请编辑 config.properties 后重启插件");
        qqToast(0, "未配置超级管理员");
    }
}

void checkAndRepairDataFiles() {
    checkGroupsFile();
    checkRecordsFile();
    checkPermissionsFile();
    checkBlacklistFile();
}

// ---- 通用：读文件内容 ----
String readFileContent(File file) {
    try {
        BufferedReader reader = new BufferedReader(new FileReader(file));
        StringBuilder sb = new StringBuilder();
        String line;
        while ((line = reader.readLine()) != null) sb.append(line);
        reader.close();
        return sb.toString();
    } catch (Exception e) {
        return null;
    }
}

// ---- 通用：创建空文件 ----
void createEmptyFile(File file, boolean isList) {
    try {
        PrintWriter out = new PrintWriter(new FileWriter(file));
        out.print(isList ? "[]" : "{}");
        out.close();
    } catch (Exception e) {}
}

// ---- 通用：备份并重建 ----
void backupAndRecreate(File file, String filename, boolean isList, String toastMsg) {
    File bak = new File(dataDirPath + "/" + filename + ".bak");
    if (bak.exists()) bak.delete();
    file.renameTo(bak);
    qqToast(1, toastMsg);
    createEmptyFile(file, isList);
}

// ==================== 各文件独立校验 ====================

void checkGroupsFile() {
    String filename = "groups.json";
    File file = new File(dataDirPath + "/" + filename);

    if (!file.exists()) {
        log("info.log", filename + " 不存在，已创建");
        qqToast(0, filename + "不存在，已创建");
        createEmptyFile(file, true);
        return;
    }

    String content = readFileContent(file);
    if (content == null) {
        log("info.log", filename + " 读取失败，备份后重建");
        backupAndRecreate(file, filename, true, filename + "已损坏，已备份重建");
        return;
    }
    if (content.trim().isEmpty()) {
        log("info.log", filename + " 为空，已重建");
        qqToast(0, filename + "为空，已重建");
        createEmptyFile(file, true);
        return;
    }

    // JSON 解析 + Schema 校验
    try {
        org.json.JSONArray arr = new org.json.JSONArray(content);
        for (int i = 0; i < arr.length(); i++) {
            org.json.JSONObject g = arr.getJSONObject(i);
            g.getString("name");
            g.getString("adminGroup");
            org.json.JSONArray eg = g.getJSONArray("executionGroups");
            for (int j = 0; j < eg.length(); j++) {
                eg.getString(j);
            }
        }
        log("info.log", filename + " 验证通过 (" + arr.length() + "个管理组)");
    } catch (org.json.JSONException e) {
        log("info.log", filename + " 校验失败(" + e.getMessage() + ")，保留原文件");
    }
}

void checkRecordsFile() {
    String filename = "records.json";
    File file = new File(dataDirPath + "/" + filename);

    if (!file.exists()) {
        log("info.log", filename + " 不存在，已创建");
        qqToast(0, filename + "不存在，已创建");
        createEmptyFile(file, true);
        return;
    }

    String content = readFileContent(file);
    if (content == null) {
        log("info.log", filename + " 读取失败，备份后重建");
        backupAndRecreate(file, filename, true, filename + "已损坏，已备份重建");
        return;
    }
    if (content.trim().isEmpty()) {
        log("info.log", filename + " 为空，已重建");
        qqToast(0, filename + "为空，已重建");
        createEmptyFile(file, true);
        return;
    }

    // JSON 解析 + Schema 校验
    try {
        org.json.JSONArray arr = new org.json.JSONArray(content);
        for (int i = 0; i < arr.length(); i++) {
            org.json.JSONObject r = arr.getJSONObject(i);
            r.getInt("id");
            r.getLong("sender");
            r.getLong("time");
            r.getString("fromGroup");
            r.getLong("target");
            r.getString("method");
            r.getString("content");
            r.getString("reason");
            r.getString("status");
            r.getString("failDetail");
            r.getLong("revokeTime");
            r.getString("revokeReason");
        }
        log("info.log", filename + " 验证通过 (" + arr.length() + "条记录)");
    } catch (org.json.JSONException e) {
        log("info.log", filename + " 校验失败(" + e.getMessage() + ")，保留原文件");
    }
}

void checkPermissionsFile() {
    String filename = "permissions.json";
    File file = new File(dataDirPath + "/" + filename);

    if (!file.exists()) {
        log("info.log", filename + " 不存在，已创建");
        qqToast(0, filename + "不存在，已创建");
        createEmptyFile(file, false);
        return;
    }

    String content = readFileContent(file);
    if (content == null) {
        log("info.log", filename + " 读取失败，备份后重建");
        backupAndRecreate(file, filename, false, filename + "已损坏，已备份重建");
        return;
    }
    if (content.trim().isEmpty()) {
        log("info.log", filename + " 为空，已重建");
        qqToast(0, filename + "为空，已重建");
        createEmptyFile(file, false);
        return;
    }

    // JSON 解析 + Schema 校验：key = QQ号, value = 数字(1或-1)
    try {
        org.json.JSONObject obj = new org.json.JSONObject(content);
        java.util.Iterator<String> keys = obj.keys();
        while (keys.hasNext()) {
            String key = keys.next();
            int val = obj.getInt(key);
            if (val != 1 && val != -1) throw new org.json.JSONException(key + " 的值不是 1 或 -1");
        }
        log("info.log", filename + " 验证通过 (" + obj.length() + "条权限)");
    } catch (org.json.JSONException e) {
        log("info.log", filename + " 校验失败(" + e.getMessage() + ")，保留原文件");
    }
}

void checkBlacklistFile() {
    String filename = "blacklist.json";
    File file = new File(dataDirPath + "/" + filename);

    if (!file.exists()) {
        log("info.log", filename + " 不存在，已创建");
        qqToast(0, filename + "不存在，已创建");
        createEmptyFile(file, true);
        return;
    }

    String content = readFileContent(file);
    if (content == null) {
        log("info.log", filename + " 读取失败，备份后重建");
        backupAndRecreate(file, filename, true, filename + "已损坏，已备份重建");
        return;
    }
    if (content.trim().isEmpty()) {
        log("info.log", filename + " 为空，已重建");
        qqToast(0, filename + "为空，已重建");
        createEmptyFile(file, true);
        return;
    }

    // JSON 解析 + Schema 校验
    try {
        org.json.JSONArray arr = new org.json.JSONArray(content);
        for (int i = 0; i < arr.length(); i++) {
            org.json.JSONObject b = arr.getJSONObject(i);
            b.getLong("qq");
            b.getString("reason");
            b.getLong("addTime");
            b.getString("groupName");
        }
        log("info.log", filename + " 验证通过 (" + arr.length() + "条黑名单)");
    } catch (org.json.JSONException e) {
        log("info.log", filename + " 校验失败(" + e.getMessage() + ")，保留原文件");
    }
}

// --- 执行检查 ---
try { checkAndRepairConfig(); } catch (Exception e) {
    log("error.log", "配置检查修复失败: " + e.getMessage());
    wakeWords = new ArrayList<>(Arrays.asList("/", "!", "。"));
    superAdmins = new HashSet<>();
    dataDirPath = pluginPath + "/data";
}

try { new File(dataDirPath).mkdirs(); } catch (Exception e) {}

try { checkAndRepairDataFiles(); } catch (Exception e) {
    log("error.log", "数据文件检查修复失败: " + e.getMessage());
}

// ==================== 数据模型 ====================
class ManagementGroup {
    String name;
    String adminGroup;
    Set<String> executionGroups = Collections.synchronizedSet(new LinkedHashSet<>());

    Map<String, Object> toMap() {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("name", name);
        map.put("adminGroup", adminGroup);
        synchronized (executionGroups) { map.put("executionGroups", new ArrayList<>(executionGroups)); }
        return map;
    }

    static ManagementGroup fromMap(Map<String, Object> map) {
        ManagementGroup g = new ManagementGroup();
        g.name = (String) map.get("name");
        g.adminGroup = (String) map.get("adminGroup");
        List<String> execs = (List<String>) map.get("executionGroups");
        if (execs != null) g.executionGroups = Collections.synchronizedSet(new LinkedHashSet<>(execs));
        return g;
    }
}

class PunishRecord {
    int id;
    long sender;
    long time;
    String fromGroup;
    long target;
    String method;   // kick, mute, warning
    String content;  // f, 1d2h, 空
    String reason;
    String status;   // 不合规, 已执行, 执行失败, 已撤销
    String failDetail;
    long revokeTime;
    String revokeReason;

    Map<String, Object> toMap() {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("id", id);
        map.put("sender", sender);
        map.put("time", time);
        map.put("fromGroup", fromGroup);
        map.put("target", target);
        map.put("method", method);
        map.put("content", content != null ? content : "");
        map.put("reason", reason);
        map.put("status", status);
        map.put("failDetail", failDetail != null ? failDetail : "");
        map.put("revokeTime", revokeTime);
        map.put("revokeReason", revokeReason != null ? revokeReason : "");
        return map;
    }

    static PunishRecord fromMap(Map<String, Object> map) {
        PunishRecord r = new PunishRecord();
        // 使用 String.valueOf + Long.parseLong 避免 BeanShell bsh.Primitive 类型转换问题
        r.id = Integer.parseInt(String.valueOf(map.get("id")));
        r.sender = Long.parseLong(String.valueOf(map.get("sender")));
        r.time = Long.parseLong(String.valueOf(map.get("time")));
        r.fromGroup = map.get("fromGroup") != null ? map.get("fromGroup").toString() : "";
        r.target = Long.parseLong(String.valueOf(map.get("target")));
        r.method = map.get("method") != null ? map.get("method").toString() : "";
        r.content = map.get("content") != null ? map.get("content").toString() : "";
        r.reason = map.get("reason") != null ? map.get("reason").toString() : "";
        r.status = map.get("status") != null ? map.get("status").toString() : "";
        r.failDetail = map.get("failDetail") != null ? map.get("failDetail").toString() : "";
        r.revokeTime = Long.parseLong(String.valueOf(map.get("revokeTime")));
        r.revokeReason = map.get("revokeReason") != null ? map.get("revokeReason").toString() : "";
        return r;
    }

    String describe() {
        String c = content != null ? content : "";
        switch (method) {
            case "kick": return "kick" + (c.equals("f") ? " f" : "");
            case "mute": return "mute " + c;
            case "warning": return "warning";
            default: return method != null ? method : "";
        }
    }
}

class BlacklistItem {
    long qq;
    String reason;
    long addTime;
    String groupName;

    Map<String, Object> toMap() {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("qq", qq);
        map.put("reason", reason);
        map.put("addTime", addTime);
        map.put("groupName", groupName);
        return map;
    }

    static BlacklistItem fromMap(Map<String, Object> map) {
        BlacklistItem b = new BlacklistItem();
        b.qq = Long.parseLong(String.valueOf(map.get("qq")));
        b.reason = map.get("reason") != null ? map.get("reason").toString() : "";
        b.addTime = Long.parseLong(String.valueOf(map.get("addTime")));
        b.groupName = map.get("groupName") != null ? map.get("groupName").toString() : "";
        return b;
    }
}

// ==================== 初始化与数据持久化 ====================
void init() {
    // 配置已在顶层代码中检查修复并设置到全局变量
    // 数据文件也已在顶层代码中验证，确保是合法 JSON

    // 加载数据
    groups = Collections.synchronizedMap(loadMap(dataDirPath + "/groups.json", ManagementGroup::fromMap));
    records = Collections.synchronizedList(loadList(dataDirPath + "/records.json", PunishRecord::fromMap));
    permissions = new ConcurrentHashMap<>(loadSimpleMap(dataDirPath + "/permissions.json"));
    blacklist = Collections.synchronizedList(loadList(dataDirPath + "/blacklist.json", BlacklistItem::fromMap));

    // 构建ID索引并计算下一个记录ID
    int maxId = 0;
    synchronized (records) {
        for (PunishRecord r : records) {
            recordsById.put(r.id, r);
            if (r.id > maxId) maxId = r.id;
        }
    }
    nextPunishRecordId.set(maxId + 1);
}

// 序列化工具
void saveAll() {
    synchronized (records) { saveList(dataDirPath + "/records.json", records, PunishRecord::toMap); }
    synchronized (groups) { saveMap(dataDirPath + "/groups.json", groups, ManagementGroup::toMap); }
    saveSimpleMap(dataDirPath + "/permissions.json", permissions);
    synchronized (blacklist) { saveList(dataDirPath + "/blacklist.json", blacklist, BlacklistItem::toMap); }
}

// 加载/保存集合
<T> List<T> loadList(String path, Function<Map<String, Object>, T> mapper) {
    File file = new File(path);
    if (!file.exists()) return new ArrayList<>();
    try {
        org.json.JSONArray arr = new org.json.JSONArray(readFileContent(file));
        List<T> list = new ArrayList<>();
        for (int i = 0; i < arr.length(); i++) {
            list.add(mapper.apply(toMap(arr.getJSONObject(i))));
        }
        return list;
    } catch (Exception e) {
        log("error.log", "加载数据失败 " + path + ": " + e.getMessage());
        // 尝试从 .tmp 恢复
        File tmpFile = new File(path + ".tmp");
        if (tmpFile.exists()) {
            try {
                org.json.JSONArray arr = new org.json.JSONArray(readFileContent(tmpFile));
                List<T> list = new ArrayList<>();
                for (int i = 0; i < arr.length(); i++) {
                    list.add(mapper.apply(toMap(arr.getJSONObject(i))));
                }
                log("info.log", "从 .tmp 恢复数据成功 " + path);
                tmpFile.renameTo(file);
                return list;
            } catch (Exception e2) {
                log("error.log", "从 .tmp 恢复数据失败 " + path + ": " + e2.getMessage());
            }
        }
    }
    return new ArrayList<>();
}

<T> void saveList(String path, List<T> list, Function<T, Map<String, Object>> mapper) {
    org.json.JSONArray arr = new org.json.JSONArray();
    for (T item : list) arr.put(new org.json.JSONObject(mapper.apply(item)));
    String tmpPath = path + ".tmp";
    try (PrintWriter out = new PrintWriter(new FileWriter(tmpPath))) {
        out.print(arr.toString());
    } catch (Exception e) {
        log("error.log", "保存数据失败 " + path + ": " + e.getMessage());
        new File(tmpPath).delete();
        return;
    }
    File tmpFile = new File(tmpPath);
    File target = new File(path);
    if (target.exists()) target.delete();
    if (!tmpFile.renameTo(target)) {
        log("error.log", "保存数据失败(rename) " + path);
    }
}

Map<String, ManagementGroup> loadMap(String path, Function<Map<String, Object>, ManagementGroup> mapper) {
    File file = new File(path);
    if (!file.exists()) return new LinkedHashMap<>();
    try {
        org.json.JSONArray arr = new org.json.JSONArray(readFileContent(file));
        Map<String, ManagementGroup> map = new LinkedHashMap<>();
        for (int i = 0; i < arr.length(); i++) {
            ManagementGroup g = mapper.apply(toMap(arr.getJSONObject(i)));
            map.put(g.name, g);
        }
        return map;
    } catch (Exception e) {
        log("error.log", "加载管理组失败: " + e.getMessage());
        // 尝试从 .tmp 恢复
        File tmpFile = new File(path + ".tmp");
        if (tmpFile.exists()) {
            try {
                org.json.JSONArray arr = new org.json.JSONArray(readFileContent(tmpFile));
                Map<String, ManagementGroup> map = new LinkedHashMap<>();
                for (int i = 0; i < arr.length(); i++) {
                    ManagementGroup g = mapper.apply(toMap(arr.getJSONObject(i)));
                    map.put(g.name, g);
                }
                log("info.log", "从 .tmp 恢复管理组成功 " + path);
                tmpFile.renameTo(file);
                return map;
            } catch (Exception e2) {
                log("error.log", "从 .tmp 恢复管理组失败 " + path + ": " + e2.getMessage());
            }
        }
    }
    return new LinkedHashMap<>();
}

void saveMap(String path, Map<String, ManagementGroup> map, Function<ManagementGroup, Map<String, Object>> mapper) {
    org.json.JSONArray arr = new org.json.JSONArray();
    for (ManagementGroup g : map.values()) arr.put(new org.json.JSONObject(mapper.apply(g)));
    String tmpPath = path + ".tmp";
    try (PrintWriter out = new PrintWriter(new FileWriter(tmpPath))) {
        out.print(arr.toString());
    } catch (Exception e) {
        log("error.log", "保存管理组失败: " + e.getMessage());
        new File(tmpPath).delete();
        return;
    }
    File tmpFile = new File(tmpPath);
    File target = new File(path);
    if (target.exists()) target.delete();
    if (!tmpFile.renameTo(target)) {
        log("error.log", "保存管理组失败(rename) " + path);
    }
}

Map<String, Integer> loadSimpleMap(String path) {
    File file = new File(path);
    if (!file.exists()) return new HashMap<>();
    try {
        org.json.JSONObject obj = new org.json.JSONObject(readFileContent(file));
        Map<String, Integer> map = new HashMap<>();
        java.util.Iterator<String> keys = obj.keys();
        while (keys.hasNext()) {
            String key = keys.next();
            map.put(key, obj.getInt(key));
        }
        return map;
    } catch (Exception e) {
        log("error.log", "加载权限失败: " + e.getMessage());
        // 尝试从 .tmp 恢复
        File tmpFile = new File(path + ".tmp");
        if (tmpFile.exists()) {
            try {
                org.json.JSONObject obj = new org.json.JSONObject(readFileContent(tmpFile));
                Map<String, Integer> map = new HashMap<>();
                java.util.Iterator<String> keys = obj.keys();
                while (keys.hasNext()) {
                    String key = keys.next();
                    map.put(key, obj.getInt(key));
                }
                log("info.log", "从 .tmp 恢复权限成功 " + path);
                tmpFile.renameTo(file);
                return map;
            } catch (Exception e2) {
                log("error.log", "从 .tmp 恢复权限失败 " + path + ": " + e2.getMessage());
            }
        }
    }
    return new HashMap<>();
}

void saveSimpleMap(String path, Map<String, Integer> map) {
    org.json.JSONObject obj = new org.json.JSONObject(map);
    String tmpPath = path + ".tmp";
    try (PrintWriter out = new PrintWriter(new FileWriter(tmpPath))) {
        out.print(obj.toString());
    } catch (Exception e) {
        log("error.log", "保存权限失败: " + e.getMessage());
        new File(tmpPath).delete();
        return;
    }
    File tmpFile = new File(tmpPath);
    File target = new File(path);
    if (target.exists()) target.delete();
    if (!tmpFile.renameTo(target)) {
        log("error.log", "保存权限失败(rename) " + path);
    }
}

// ==================== org.json → Map/List 转换辅助 ====================
// 将 org.json.JSONObject 递归转换为 Map<String, Object>，保证与 fromMap 兼容
Map<String, Object> toMap(org.json.JSONObject obj) {
    Map<String, Object> map = new LinkedHashMap<>();
    java.util.Iterator<String> keys = obj.keys();
    while (keys.hasNext()) {
        String key = keys.next();
        map.put(key, toValue(obj.get(key)));
    }
    return map;
}

List<Object> toList(org.json.JSONArray arr) {
    List<Object> list = new ArrayList<>();
    for (int i = 0; i < arr.length(); i++) {
        list.add(toValue(arr.get(i)));
    }
    return list;
}

Object toValue(Object value) {
    if (value instanceof org.json.JSONObject) return toMap((org.json.JSONObject) value);
    if (value instanceof org.json.JSONArray) return toList((org.json.JSONArray) value);
    if (value == org.json.JSONObject.NULL) return null;
    return value;
}

// 函数式接口（避免依赖java.util.function）
interface Function<T, R> {
    R apply(T t);
}

// ==================== 辅助方法 ====================
int getPermissionLevel(String qq) {
    if (superAdmins.contains(qq)) return 0;
    return permissions.getOrDefault(qq, -1);
}

ManagementGroup findGroupByGroupId(String groupId) {
    synchronized (groups) {
        for (ManagementGroup g : groups.values()) {
            if (g.adminGroup.equals(groupId) || g.executionGroups.contains(groupId)) return g;
        }
    }
    return null;
}

ManagementGroup findGroupByName(String name) {
    return groups.get(name);
}

void sendGroupMsg(String group, String msg) {
    sendMsg(group, msg, 2); // 2=群聊
}

void notifyAdminGroup(ManagementGroup g, String msg) {
    if (g != null && g.adminGroup != null) {
        sendGroupMsg(g.adminGroup, msg);
    }
}

// 解析时长（秒），返回null表示格式错误
Long parseDurationSeconds(String dur) {
    if (dur == null || dur.isEmpty()) return null;
    // 纯数字（含小数点） -> 天
    try {
        double days = Double.parseDouble(dur);
        return (long) (days * 86400);
    } catch (Exception e) {}
    // 组合格式 XdYhZm
    Pattern p = Pattern.compile("(\\d+d)?(\\d+h)?(\\d+m)?");
    Matcher m = p.matcher(dur.toLowerCase());
    if (m.matches() && !dur.isEmpty()) {
        long total = 0;
        boolean matched = false;
        String dayStr = m.group(1);
        String hourStr = m.group(2);
        String minStr = m.group(3);
        if (dayStr != null) { total += Long.parseLong(dayStr.replace("d","")) * 86400; matched = true; }
        if (hourStr != null) { total += Long.parseLong(hourStr.replace("h","")) * 3600; matched = true; }
        if (minStr != null) { total += Long.parseLong(minStr.replace("m","")) * 60; matched = true; }
        if (matched && total > 0) return total;
    }
    return null;
}

// 从文本中提取纯数字（QQ号）
String extractQQ(String text) {
    if (text == null) return null;
    Matcher m = Pattern.compile("\\d+").matcher(text);
    if (m.find()) return m.group();
    return null;
}

// 从消息中解析目标QQ：优先at列表，其次从文本提取数字
String resolveTargetQQ(Object msgData, String text) {
    List<String> atList = msgData.atList;
    if (atList != null && !atList.isEmpty()) {
        return atList.get(0);
    }
    return extractQQ(text);
}

// ==================== 指令解析与执行 ====================
void onMsg(Object msgData) {
    if (!initialized) {
        synchronized (initLock) {
            if (!initialized) {
                init();
                initialized = true;
            }
        }
    }

    // 直接动态访问属性，无需强制转换为MsgData
    int type = msgData.type;
    if (type != 2) return; // 仅处理群聊
    String text = msgData.msg != null ? msgData.msg.trim() : "";
    String peerUin = msgData.peerUin;       // 群号
    String userUin = msgData.userUin;       // 发送者QQ

    // 检查唤醒词
    boolean startsWithWake = false;
    for (String word : wakeWords) {
        if (text.startsWith(word)) {
            text = text.substring(word.length()).trim();
            startsWithWake = true;
            break;
        }
    }
    if (!startsWithWake) return;

    // 权限等级，-1 直接忽略
    int level = getPermissionLevel(userUin);
    if (level < 0) return;

    String[] parts = text.split("\\s+");
    if (parts.length == 0) return;
    String cmd = parts[0].toLowerCase();

    switch (cmd) {
        case "help":
            cmdHelp(level, peerUin);
            break;
        case "p":
            cmdPunish(level, userUin, peerUin, parts, msgData);
            break;
        case "h":
            cmdQuery(level, peerUin, parts, msgData);
            break;
        case "a":
            cmdPermission(level, userUin, peerUin, parts, msgData);
            break;
        case "group":
            cmdGroup(level, userUin, peerUin, parts);
            break;
        case "rp":
            cmdRevoke(level, userUin, peerUin, parts);
            break;
        default:
            // 未知指令
            break;
    }
}

void cmdHelp(int level, String group) {
    StringBuilder sb = new StringBuilder("可用指令：\n");
    if (level == 0) {
        sb.append("/p <目标> <方式> [内容] <原因>  - 处罚\n");
        sb.append("/h <目标> [-i]               - 查询记录\n");
        sb.append("/a <目标> [等级]             - 设置权限\n");
        sb.append("/group admin/set/remove/info - 管理组\n");
        sb.append("/rp <记录ID> [原因]          - 撤销\n");
    } else if (level == 1) {
        sb.append("/p <目标> <方式> [内容] <原因>  - 处罚\n");
        sb.append("/h <目标> [-i]               - 查询记录\n");
        sb.append("/rp <记录ID> [原因]          - 撤销\n");
    }
    sb.append("/help - 帮助");
    sendGroupMsg(group, sb.toString());
}

void cmdPunish(int level, String sender, String group, String[] parts, Object msgData) {
    if (parts.length < 4) {
        sendGroupMsg(group, "格式：<唤醒词>p <被处罚者> <处罚方式> [处罚内容] <原因>");
        return;
    }
    // 被处罚者解析
    String targetQQ = resolveTargetQQ(msgData, parts[1]);
    if (targetQQ == null || targetQQ.isEmpty()) {
        sendGroupMsg(group, "未找到被处罚者QQ，请艾特或输入QQ号");
        return;
    }

    String method = parts[2].toLowerCase();
    if (!method.equals("kick") && !method.equals("mute") && !method.equals("warning")) {
        sendGroupMsg(group, "无效的处罚方式，可选：kick, mute, warning");
        return;
    }

    String content = "";
    String reason;
    int reasonStart;
    if (method.equals("mute")) {
        if (parts.length < 5) {
            sendGroupMsg(group, "禁言缺少时长，格式：mute <时长> <原因>");
            return;
        }
        content = parts[3];
        reasonStart = 4;
        // 验证时长格式
        if (parseDurationSeconds(content) == null) {
            sendGroupMsg(group, "时长格式错误，支持：数字(天) 或 组合如1d2h30m");
            return;
        }
    } else if (method.equals("kick")) {
        if (parts.length >= 4) {
            if (parts[3].equalsIgnoreCase("f")) {
                content = "f";
                reasonStart = 4;
            } else {
                content = "";
                reasonStart = 3;
            }
        } else {
            reasonStart = 3;
        }
    } else { // warning
        content = "";
        reasonStart = 3;
    }

    if (reasonStart >= parts.length) {
        // 缺少原因
        PunishRecord r = createPunishRecord(sender, group, Long.parseLong(targetQQ), method, content, "", "不合规");
        notifyAdminGroup(findGroupByGroupId(group), "[不合规] 处罚（" + r.id + "）：发起者（" + sender + "）在群（" + group + "）发起的处罚缺少原因，未执行。");
        sendGroupMsg(group, "原因缺失，记录已生成为[不合规]，未执行处罚。");
        saveAll();
        return;
    }

    StringBuilder reasonBuilder = new StringBuilder();
    for (int i = reasonStart; i < parts.length; i++) {
        if (i > reasonStart) reasonBuilder.append(" ");
        reasonBuilder.append(parts[i]);
    }
    reason = reasonBuilder.toString();

    // 查找管理组
    ManagementGroup mg = findGroupByGroupId(group);
    if (mg == null) {
        sendGroupMsg(group, "当前群不属于任何管理组，无法执行。");
        return;
    }

    // 创建记录
    PunishRecord r = createPunishRecord(sender, group, Long.parseLong(targetQQ), method, content, reason, "执行中");

    // 遍历执行群（三步检查：成员在群 → 状态检查 → 执行）
    List<String> execGroups;
    synchronized (mg.executionGroups) { execGroups = new ArrayList<>(mg.executionGroups); }
    boolean anySuccess = false;
    boolean anyFail = false;
    List<String> failGroups = new ArrayList<>();
    for (String gid : execGroups) {
        // 第一步：检查确认成员在群内（不在则跳过，不视为失败）
        // 使用 getGroupMemberList 遍历比对 uin，比 getMemberInfo 更可靠
        boolean memberInGroup = false;
        List groupMembers = getGroupMemberList(gid);
        if (groupMembers != null) {
            for (Object m : groupMembers) {
                if (m.uin != null && m.uin.equals(targetQQ)) {
                    memberInGroup = true;
                    break;
                }
            }
        }
        if (!memberInGroup) continue;

        // 第二步：操作前状态检查
        if (method.equals("mute")) {
            // 检查成员是否已被禁言（仍执行以更新时长，仅记录提示）
            List prohibitList = getProhibitList(gid);
            if (prohibitList != null) {
                for (Object p : prohibitList) {
                    if (p.user.equals(targetQQ)) {
                        notifyAdminGroup(mg, "[提示] 处罚「" + r.id + "」在群" + gid + "成员" + targetQQ + "已被禁言，将更新禁言时长。");
                        break;
                    }
                }
            }
        }

        // 第三步：执行处罚操作并通报
        try {
            switch (method) {
                case "kick":
                    boolean toBlack = "f".equals(content);
                    kickGroup(gid, targetQQ, false);
                    if (toBlack) {
                        addToBlacklist(Long.parseLong(targetQQ), reason, mg.name);
                        sendGroupMsg(gid, "[atUin=" + targetQQ + "] 因「" + reason + "」被踢出并加入黑名单。");
                    } else {
                        sendGroupMsg(gid, "[atUin=" + targetQQ + "] 因「" + reason + "」被踢出。");
                    }
                    break;
                case "mute":
                    long sec = parseDurationSeconds(content);
                    shutUp(gid, targetQQ, sec);
                    sendGroupMsg(gid, "[atUin=" + targetQQ + "] 因「" + reason + "」被禁言 " + content + "。");
                    break;
                case "warning":
                    // 警告无实际操作，仅通报
                    sendGroupMsg(gid, "[atUin=" + targetQQ + "] 因「" + reason + "」被警告。");
                    break;
            }
            anySuccess = true;
        } catch (Exception e) {
            anyFail = true;
            failGroups.add(gid);
            notifyAdminGroup(mg, "[异常] 处罚「" + r.id + "」在群" + gid + "执行失败：" + e.getMessage());
        }
    }

    // 更新状态
    if (anyFail && !anySuccess) {
        r.status = "执行失败";
        r.failDetail = "失败群：" + String.join(",", failGroups);
    } else if (anyFail) {
        r.status = "执行失败";
        r.failDetail = "部分失败，失败群：" + String.join(",", failGroups);
    } else {
        r.status = "已执行";
    }
    updatePunishRecord(r);

    // 发送总结（仅报告失败，跳过不视为失败）
    StringBuilder feedback = new StringBuilder();
    if (anyFail && !anySuccess) {
        feedback.append("处罚执行失败，失败群：" + String.join(",", failGroups));
    } else if (anyFail) {
        feedback.append("处罚部分执行失败，失败群：" + String.join(",", failGroups));
    } else {
        feedback.append("处罚已执行。");
    }
    sendGroupMsg(group, feedback.toString());

    // 通知管理群
    notifyAdminGroup(mg, "处罚「" + r.id + "」：" + sender + "在" + group + "内发起了对" + targetQQ + "的「" + r.describe() + "」处罚，原因：「" + reason + "」");

    saveAll();
}

PunishRecord createPunishRecord(String sender, String fromGroup, long target, String method, String content, String reason, String status) {
    PunishRecord r = new PunishRecord();
    r.id = nextPunishRecordId.getAndIncrement();
    r.sender = Long.parseLong(sender);
    r.time = System.currentTimeMillis() / 1000;
    r.fromGroup = fromGroup;
    r.target = target;
    r.method = method;
    r.content = content;
    r.reason = reason;
    r.status = status;
    r.failDetail = "";
    r.revokeReason = "";
    synchronized (dataLock) {
        records.add(r);
        recordsById.put(r.id, r);
    }
    return r;
}

void updatePunishRecord(PunishRecord r) {
    // 已经在列表中，无需操作，保存时会同步
}

void addToBlacklist(long qq, String reason, String groupName) {
    BlacklistItem item = new BlacklistItem();
    item.qq = qq;
    item.reason = reason;
    item.addTime = System.currentTimeMillis() / 1000;
    item.groupName = groupName;
    synchronized (blacklist) {
        // 检查是否存在
        for (BlacklistItem b : blacklist) {
            if (b.qq == qq && b.groupName.equals(groupName)) return;
        }
        blacklist.add(item);
    }
}

void removeFromBlacklist(long qq, String groupName) {
    blacklist.removeIf(b -> b.qq == qq && b.groupName.equals(groupName));
}

void cmdQuery(int level, String group, String[] parts, Object msgData) {
    if (parts.length < 2) {
        sendGroupMsg(group, "格式：/h <成员> [-i]（可at）");
        return;
    }
    String targetQQ = resolveTargetQQ(msgData, parts[1]);
    if (targetQQ == null || targetQQ.isEmpty()) {
        sendGroupMsg(group, "未找到目标QQ，请at或输入QQ号");
        return;
    }
    long target = Long.parseLong(targetQQ);
    boolean detail = parts.length > 2 && parts[2].equals("-i");

    ManagementGroup mg = findGroupByGroupId(group);
    if (mg == null) {
        sendGroupMsg(group, "当前群不属于管理组");
        return;
    }

    List<PunishRecord> filtered = new ArrayList<>();
    synchronized (records) {
        for (PunishRecord r : records) {
            if (r.target == target && (r.fromGroup.equals(group) || mg.executionGroups.contains(r.fromGroup) || mg.adminGroup.equals(r.fromGroup))) {
                // 组内共享记录
                filtered.add(r);
            }
        }
    }

    if (detail) {
        // 生成表格图片发送
        sendPunishRecordTableImage(group, filtered);
    } else {
        // 汇总统计（仅已执行和执行失败）
        int totalPunish = 0, muteCount = 0, kickCount = 0;
        long muteTotalSec = 0;
        for (PunishRecord r : filtered) {
            if (r.status.equals("已执行") || r.status.equals("执行失败")) {
                totalPunish++;
                if (r.method.equals("mute")) {
                    muteCount++;
                    Long sec = parseDurationSeconds(r.content);
                    if (sec != null) muteTotalSec += sec;
                } else if (r.method.equals("kick")) {
                    kickCount++;
                }
            }
        }
        StringBuilder sb = new StringBuilder("成员 " + targetQQ + " 统计：\n");
        if (totalPunish > 0) sb.append("被处罚总次数：").append(totalPunish).append("\n");
        if (muteCount > 0) {
            sb.append("被禁言次数：").append(muteCount).append("\n");
            long hours = muteTotalSec / 3600;
            long minutes = (muteTotalSec % 3600) / 60;
            long days = hours / 24;
            hours = hours % 24;
            sb.append("被禁言总时长：").append(days).append("d").append(hours).append("h").append(minutes).append("m\n");
        }
        if (kickCount > 0) sb.append("被踢次数：").append(kickCount).append("\n");
        if (totalPunish == 0) sb.append("暂无记录");
        sendGroupMsg(group, sb.toString());
    }
}

// ==================== 记录表格图片生成 ====================
void sendPunishRecordTableImage(String group, List<PunishRecord> list) {
    if (list.isEmpty()) {
        sendGroupMsg(group, "无记录");
        return;
    }
    try {
        String path = pluginPath + "/record_table_" + group + "_" + System.currentTimeMillis() + ".png";
        generatePunishRecordTableImage(list, path);
        sendPic(group, path, 2);
        new File(path).delete();
    } catch (Exception e) {
        // 图片生成失败时回退到文字表格
        sendGroupMsg(group, buildPunishRecordTable(list));
    }
}

void generatePunishRecordTableImage(List<PunishRecord> list, String outputPath) throws IOException {
    SimpleDateFormat fmt = new SimpleDateFormat("MM-dd HH:mm");

    // 列定义：标签与宽度
    String[] headers = {"ID", "时间", "发起群", "发起者", "方式", "内容", "原因", "状态", "撤销时间", "撤销原因"};
    int[] colWidths = {50, 120, 110, 110, 55, 70, 140, 70, 120, 140};
    int[] colX = new int[colWidths.length];
    int x = 16;
    for (int i = 0; i < colWidths.length; i++) {
        colX[i] = x;
        x += colWidths[i] + 12;
    }
    int imgWidth = x + 16;

    int rowHeight = 42;
    int headerY = 68;
    int headerH = 46;
    int imgHeight = headerY + headerH + list.size() * rowHeight + 30;

    Bitmap bitmap = Bitmap.createBitmap(imgWidth, imgHeight, Bitmap.Config.ARGB_8888);
    Canvas canvas = new Canvas(bitmap);
    Paint paint = new Paint();
    paint.setAntiAlias(true);
    canvas.drawColor(Color.WHITE);

    // 标题
    paint.setColor(Color.parseColor("#1A237E"));
    paint.setTypeface(Typeface.DEFAULT_BOLD);
    paint.setTextSize(30);
    canvas.drawText("处罚记录列表  (" + list.size() + "条)", 20, 44, paint);

    // 表头背景
    paint.setColor(Color.parseColor("#3F51B5"));
    canvas.drawRoundRect(12, headerY - 4, imgWidth - 12, headerY + headerH - 10, 10, 10, paint);

    // 表头文字
    paint.setColor(Color.WHITE);
    paint.setTypeface(Typeface.DEFAULT_BOLD);
    paint.setTextSize(20);
    for (int i = 0; i < headers.length; i++) {
        canvas.drawText(headers[i], colX[i], headerY + 28, paint);
    }

    // 数据行
    paint.setTypeface(Typeface.DEFAULT);
    paint.setTextSize(17);
    for (int i = 0; i < list.size(); i++) {
        PunishRecord r = list.get(i);
        int rowY = headerY + headerH + i * rowHeight;

        // 交替行背景
        if (i % 2 == 0) {
            paint.setColor(Color.parseColor("#F5F7FF"));
        } else {
            paint.setColor(Color.WHITE);
        }
        canvas.drawRect(12, rowY, imgWidth - 12, rowY + rowHeight, paint);

        // 行分隔线
        paint.setColor(Color.parseColor("#E0E0E0"));
        canvas.drawLine(12, rowY + rowHeight, imgWidth - 12, rowY + rowHeight, paint);

        // 状态颜色（null 安全）
        String st = r.status != null ? r.status : "";
        int statusColor = Color.BLACK;
        if (st.equals("已执行")) statusColor = Color.parseColor("#2E7D32");
        else if (st.equals("已撤销")) statusColor = Color.parseColor("#F57F17");
        else if (st.equals("执行失败")) statusColor = Color.parseColor("#C62828");
        else if (st.equals("不合规")) statusColor = Color.parseColor("#757575");

        String c = (r.content != null && !r.content.isEmpty()) ? r.content : "-";
        String revReason = (r.revokeReason != null && !r.revokeReason.isEmpty()) ? r.revokeReason : "-";

        String[] values = {
            String.valueOf(r.id),
            fmt.format(new Date(r.time * 1000)),
            truncateText(r.fromGroup, paint, colWidths[2]),
            truncateText(String.valueOf(r.sender), paint, colWidths[3]),
            r.method != null ? r.method : "-",
            truncateText(c, paint, colWidths[5]),
            truncateText(r.reason, paint, colWidths[6]),
            st.isEmpty() ? "-" : st,
            r.revokeTime == 0 ? "-" : fmt.format(new Date(r.revokeTime * 1000)),
            truncateText(revReason, paint, colWidths[9])
        };

        for (int j = 0; j < values.length; j++) {
            int color = (j == 7) ? statusColor : Color.BLACK;
            paint.setColor(color);
            canvas.drawText(values[j], colX[j], rowY + 29, paint);
        }
    }

    FileOutputStream fos = new FileOutputStream(outputPath);
    bitmap.compress(Bitmap.CompressFormat.PNG, 100, fos);
    fos.close();
}

String truncateText(String text, Paint paint, float maxWidth) {
    if (text == null || text.isEmpty()) return "-";
    if (paint.measureText(text) <= maxWidth) return text;
    String result = text;
    while (result.length() > 0 && paint.measureText(result + "…") > maxWidth) {
        result = result.substring(0, result.length() - 1);
    }
    return result.isEmpty() ? "…" : result + "…";
}

// 文字表格（回退用）
String buildPunishRecordTable(List<PunishRecord> list) {
    if (list.isEmpty()) return "无记录";
    StringBuilder sb = new StringBuilder("记录列表：\n");
    sb.append("ID | 时间 | 发起群 | 发起者 | 方式 | 内容 | 原因 | 状态 | 撤销时间 | 撤销原因\n");
    SimpleDateFormat fmt = new SimpleDateFormat("MM-dd HH:mm");
    for (PunishRecord r : list) {
        String c = r.content != null && !r.content.isEmpty() ? r.content : "-";
        String revReason = r.revokeReason != null && !r.revokeReason.isEmpty() ? r.revokeReason : "-";
        String fg = r.fromGroup != null ? r.fromGroup : "-";
        String m = r.method != null ? r.method : "-";
        String rs = r.reason != null ? r.reason : "-";
        String st = r.status != null ? r.status : "-";
        sb.append(r.id).append(" | ");
        sb.append(fmt.format(new Date(r.time * 1000))).append(" | ");
        sb.append(fg).append(" | ");
        sb.append(r.sender).append(" | ");
        sb.append(m).append(" | ");
        sb.append(c).append(" | ");
        sb.append(rs).append(" | ");
        sb.append(st).append(" | ");
        sb.append(r.revokeTime == 0 ? "-" : fmt.format(new Date(r.revokeTime * 1000))).append(" | ");
        sb.append(revReason);
        sb.append("\n");
    }
    return sb.toString();
}

void cmdPermission(int level, String sender, String group, String[] parts, Object msgData) {
    if (level != 0) {
        sendGroupMsg(group, "权限不足，仅超级管理员可用");
        return;
    }
    if (parts.length < 2) {
        sendGroupMsg(group, "格式：/a <成员> [1/-1]（可at）");
        return;
    }
    String targetQQ = resolveTargetQQ(msgData, parts[1]);
    if (targetQQ == null || targetQQ.isEmpty()) {
        sendGroupMsg(group, "未找到目标QQ，请at或输入QQ号");
        return;
    }
    if (targetQQ.equals(sender)) {
        sendGroupMsg(group, "不能修改自己的权限");
        return;
    }
    int newLevel = 1; // 默认
    if (parts.length >= 3) {
        try {
            newLevel = Integer.parseInt(parts[2]);
        } catch (Exception e) {
            sendGroupMsg(group, "权限等级只能是1或-1");
            return;
        }
    }
    if (newLevel != 1 && newLevel != -1) {
        sendGroupMsg(group, "权限等级只能是1或-1");
        return;
    }
    permissions.put(targetQQ, newLevel);
    saveAll();
    sendGroupMsg(group, "已设置 " + targetQQ + " 的权限为 " + (newLevel == 1 ? "管理员" : "普通成员"));
}

void cmdGroup(int level, String sender, String group, String[] parts) {
    if (level != 0) {
        sendGroupMsg(group, "权限不足");
        return;
    }
    if (parts.length < 2) {
        sendGroupMsg(group, "子命令：admin <名称> / set <名称> / remove / info");
        return;
    }
    String sub = parts[1].toLowerCase();
    switch (sub) {
        case "admin":
            if (parts.length < 3) {
                sendGroupMsg(group, "格式：/group admin <组名>");
                return;
            }
            String name = parts[2];
            if (findGroupByName(name) != null) {
                sendGroupMsg(group, "管理组已存在");
                return;
            }
            if (findGroupByGroupId(group) != null) {
                sendGroupMsg(group, "本群已属于其他管理组");
                return;
            }
            ManagementGroup mg = new ManagementGroup();
            mg.name = name;
            mg.adminGroup = group;
            groups.put(name, mg);
            saveAll();
            sendGroupMsg(group, "管理组 “" + name + "” 创建成功，本群为管理群");
            break;
        case "set":
            if (parts.length < 3) {
                sendGroupMsg(group, "格式：/group set <组名>");
                return;
            }
            String targetName = parts[2];
            ManagementGroup exist = findGroupByName(targetName);
            if (exist == null) {
                sendGroupMsg(group, "管理组不存在");
                return;
            }
            if (exist.adminGroup.equals(group)) {
                sendGroupMsg(group, "管理群不能作为执行群");
                return;
            }
            if (findGroupByGroupId(group) != null) {
                sendGroupMsg(group, "本群已属于其他管理组");
                return;
            }
            exist.executionGroups.add(group);
            saveAll();
            sendGroupMsg(group, "已将本群加入管理组 “" + targetName + "” 作为执行群");
            break;
        case "remove":
            ManagementGroup current = findGroupByGroupId(group);
            if (current == null) {
                sendGroupMsg(group, "本群不属于任何管理组");
                return;
            }
            if (current.adminGroup.equals(group)) {
                sendGroupMsg(group, "管理群无法移出，请使用 /group admin 重建");
                return;
            }
            current.executionGroups.remove(group);
            saveAll();
            sendGroupMsg(group, "已从管理组移出");
            break;
        case "info":
            ManagementGroup info = findGroupByGroupId(group);
            if (info == null) {
                sendGroupMsg(group, "本群未加入管理组");
                return;
            }
            String role = info.adminGroup.equals(group) ? "管理群" : "执行群";
            String execList;
            synchronized (info.executionGroups) {
                execList = info.executionGroups.isEmpty() ? "无" : String.join(",", info.executionGroups);
            }
            sendGroupMsg(group, "组名：" + info.name + "\n角色：" + role + "\n管理群：" + info.adminGroup + "\n执行群列表：" + execList);
            break;
        default:
            sendGroupMsg(group, "未知子命令");
    }
}

void cmdRevoke(int level, String sender, String group, String[] parts) {
    if (level != 0 && level != 1) {
        sendGroupMsg(group, "无权限");
        return;
    }
    if (parts.length < 2) {
        sendGroupMsg(group, "格式：/rp <记录ID> [撤销原因]");
        return;
    }
    int recordId;
    try {
        recordId = Integer.parseInt(parts[1]);
    } catch (Exception e) {
        sendGroupMsg(group, "记录ID必须为数字");
        return;
    }
    PunishRecord target = recordsById.get(recordId);
    if (target == null) {
        sendGroupMsg(group, "记录不存在");
        return;
    }
    if (!target.status.equals("已执行") && !target.status.equals("执行失败")) {
        sendGroupMsg(group, "该记录状态为 " + target.status + "，不可撤销");
        return;
    }
    String revokeReason = parts.length >= 3 ? String.join(" ", Arrays.copyOfRange(parts, 2, parts.length)) : "";

    ManagementGroup mg = findGroupByGroupId(target.fromGroup);
    if (mg == null) {
        sendGroupMsg(group, "记录对应管理组异常");
        return;
    }

    // 执行撤销动作（三步检查：成员在群 → 处于禁言状态 → 执行解禁）
    boolean anyRevoked = false;
    List<String> revokeSkipGroups = new ArrayList<>();
    List<String> revokeFailGroups = new ArrayList<>();

    if (target.method.equals("mute")) {
        for (String gid : mg.executionGroups) {
            try {
                // 第一步：检查确认成员在群内
                // 使用 getGroupMemberList 遍历比对 uin，比 getMemberInfo 更可靠
                boolean memberInGroup = false;
                List groupMembers = getGroupMemberList(gid);
                if (groupMembers != null) {
                    for (Object m : groupMembers) {
                        if (m.uin != null && m.uin.equals(String.valueOf(target.target))) {
                            memberInGroup = true;
                            break;
                        }
                    }
                }
                if (!memberInGroup) {
                    revokeSkipGroups.add(gid + "(成员不存在)");
                    continue;
                }

                // 第二步：检查成员处于被禁言状态
                boolean isMuted = false;
                List prohibitList = getProhibitList(gid);
                if (prohibitList != null) {
                    for (Object p : prohibitList) {
                        if (p.user.equals(String.valueOf(target.target))) {
                            isMuted = true;
                            break;
                        }
                    }
                }
                if (!isMuted) {
                    revokeSkipGroups.add(gid + "(未处于禁言状态)");
                    continue;
                }

                // 第三步：执行取消禁言
                shutUp(gid, String.valueOf(target.target), 0);
                anyRevoked = true;
            } catch (Exception e) {
                revokeFailGroups.add(gid);
                notifyAdminGroup(mg, "[异常] 撤销（" + target.id + "）在群（" + gid + "）执行失败：" + e.getMessage());
            }
        }

        // 没有任何群成功解禁
        if (!anyRevoked && !revokeFailGroups.isEmpty()) {
            sendGroupMsg(group, "撤销操作执行失败，失败群：" + String.join(",", revokeFailGroups));
            return;
        }
    } else if (target.method.equals("kick") && "f".equals(target.content)) {
        try {
            removeFromBlacklist(target.target, mg.name);
            anyRevoked = true;
        } catch (Exception e) {
            sendGroupMsg(group, "撤销操作执行失败：" + e.getMessage());
            return;
        }
    }
    // warning 和 kick 非 f 无操作

    target.status = "已撤销";
    target.revokeTime = System.currentTimeMillis() / 1000;
    target.revokeReason = revokeReason;
    updatePunishRecord(target);
    saveAll();

    String revokeMsg = "记录 " + recordId + " 已撤销";
    if (!revokeSkipGroups.isEmpty()) {
        revokeMsg += "（以下群跳过：" + String.join(", ", revokeSkipGroups) + "）";
    }
    sendGroupMsg(group, revokeMsg);
    notifyAdminGroup(mg, "[撤销] 处罚（" + target.id + "）已被（" + sender + "）撤销，原处罚：（" + target.target + "）的（" + target.describe() + "），原因：（" + target.reason + "）。撤销原因：" + (revokeReason.isEmpty() ? "无" : revokeReason));
}

// ==================== 群事件：黑名单自动踢人 ====================
void joinGroup(String group, String qq) {
    if (!initialized) {
        synchronized (initLock) { if (!initialized) init(); }
    }
    ManagementGroup mg = findGroupByGroupId(group);
    if (mg == null) return;
    BlacklistItem matched = null;
    synchronized (blacklist) {
        for (BlacklistItem b : blacklist) {
            if (b.qq == Long.parseLong(qq) && b.groupName.equals(mg.name)) {
                matched = b;
                break;
            }
        }
    }
    if (matched != null) {
        try {
            // 检查成员是否仍在群内
            // 使用 getGroupMemberList 遍历比对 uin，比 getMemberInfo 更可靠
            boolean memberInGroup = false;
            List groupMembers = getGroupMemberList(group);
            if (groupMembers != null) {
                for (Object m : groupMembers) {
                    if (m.uin != null && m.uin.equals(qq)) {
                        memberInGroup = true;
                        break;
                    }
                }
            }
            if (!memberInGroup) {
                log("info.log", "黑名单成员 " + qq + " 在群（" + group + "）中已不存在，跳过踢出。");
                return;
            }
            kickGroup(group, qq, false);
            sendGroupMsg(group, "用户 " + qq + " 在管理组黑名单中，已自动移出。原因：" + matched.reason);
        } catch (Exception e) {
            log("error.log", "黑名单踢人失败：" + e.getMessage());
        }
    }
}

// ==================== 生命周期 ====================
void unLoadPlugin() {
    saveAll();
}
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
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Typeface;

// ==================== 数据模型（必须最先定义，BeanShell 不支持前向引用） ====================

class ConfigInfo {
    String notifyGroup;
    Set<String> executionGroups = Collections.synchronizedSet(new LinkedHashSet<String>());

    Map<String, Object> toMap() {
        Map<String, Object> map = new LinkedHashMap<String, Object>();
        map.put("notifyGroup", notifyGroup);
        synchronized (executionGroups) {
            map.put("executionGroups", new ArrayList<String>(executionGroups));
        }
        return map;
    }

    static ConfigInfo fromMap(Map<String, Object> map) {
        ConfigInfo info = new ConfigInfo();
        Object ng = map.get("notifyGroup");
        info.notifyGroup = (ng != null && !String.valueOf(ng).isEmpty()) ? String.valueOf(ng) : null;
        Object eg = map.get("executionGroups");
        if (eg instanceof List) {
            List<String> execs = (List<String>) eg;
            info.executionGroups = Collections.synchronizedSet(new LinkedHashSet<String>());
            for (int i = 0; i < execs.size(); i++) {
                String e = execs.get(i);
                if (e != null && !e.isEmpty()) info.executionGroups.add(String.valueOf(e));
            }
        }
        return info;
    }
}

class CommandItem {
    boolean enabled = true;
    List<String> names = new ArrayList<String>();
    Integer minLevel = null;  // null=继承上级, -1=所有人, 0=超管, ≥1越小越高
    Map<String, CommandItem> sub;  // 子命令

    Map<String, Object> toMap() {
        Map<String, Object> map = new LinkedHashMap<String, Object>();
        map.put("enabled", enabled);
        if (names != null && !names.isEmpty()) {
            map.put("names", new ArrayList<String>(names));
        }
        if (minLevel != null) {
            map.put("minLevel", minLevel);
        }
        if (sub != null && !sub.isEmpty()) {
            Map<String, Object> subMap = new LinkedHashMap<String, Object>();
            for (Map.Entry<String, CommandItem> e : sub.entrySet()) {
                subMap.put(e.getKey(), e.getValue().toMap());
            }
            map.put("sub", subMap);
        }
        return map;
    }

    static CommandItem fromMap(Map<String, Object> map) {
        CommandItem item = new CommandItem();
        if (map.containsKey("enabled")) {
            item.enabled = Boolean.parseBoolean(String.valueOf(map.get("enabled")));
        }
        Object namesObj = map.get("names");
        if (namesObj instanceof List) {
            List<String> ns = (List<String>) namesObj;
            item.names = new ArrayList<String>();
            for (int i = 0; i < ns.size(); i++) {
                String n = ns.get(i);
                if (n != null && !n.isEmpty()) item.names.add(n);
            }
        }
        if (map.containsKey("minLevel") && map.get("minLevel") != null) {
            try {
                item.minLevel = Integer.parseInt(String.valueOf(map.get("minLevel")));
            } catch (Exception e) {
                item.minLevel = null;
            }
        }
        Object subObj = map.get("sub");
        if (subObj instanceof Map) {
            Map<String, Object> subMap = (Map<String, Object>) subObj;
            item.sub = new LinkedHashMap<String, CommandItem>();
            for (Map.Entry<String, Object> e : subMap.entrySet()) {
                if (e.getValue() instanceof Map) {
                    item.sub.put(e.getKey(), CommandItem.fromMap((Map<String, Object>) e.getValue()));
                }
            }
        }
        return item;
    }
}

class CommandConfig {
    Map<String, CommandItem> commands = new LinkedHashMap<String, CommandItem>();

    Map<String, Object> toMap() {
        Map<String, Object> map = new LinkedHashMap<String, Object>();
        Map<String, Object> cmds = new LinkedHashMap<String, Object>();
        for (Map.Entry<String, CommandItem> e : commands.entrySet()) {
            cmds.put(e.getKey(), e.getValue().toMap());
        }
        map.put("commands", cmds);
        return map;
    }

    static CommandConfig fromMap(Map<String, Object> map) {
        CommandConfig cc = new CommandConfig();
        Object cmdsObj = map.get("commands");
        if (cmdsObj instanceof Map) {
            Map<String, Object> cmds = (Map<String, Object>) cmdsObj;
            for (Map.Entry<String, Object> e : cmds.entrySet()) {
                if (e.getValue() instanceof Map) {
                    cc.commands.put(e.getKey(), CommandItem.fromMap((Map<String, Object>) e.getValue()));
                }
            }
        }
        return cc;
    }

    static CommandConfig defaults() {
        CommandConfig cc = new CommandConfig();
        // help — 所有人可见
        CommandItem helpItem = new CommandItem();
        helpItem.names = Arrays.asList("help");
        helpItem.minLevel = -1;
        cc.commands.put("help", helpItem);
        // punish_do
        CommandItem pItem = new CommandItem();
        pItem.names = Arrays.asList("p", "punish");
        pItem.minLevel = 1;
        cc.commands.put("punish_do", pItem);
        // punish_revoke
        CommandItem rpItem = new CommandItem();
        rpItem.names = Arrays.asList("rp", "revoke");
        rpItem.minLevel = 1;
        cc.commands.put("punish_revoke", rpItem);
        // punish_history
        CommandItem hItem = new CommandItem();
        hItem.names = Arrays.asList("h", "history");
        hItem.minLevel = 1;
        cc.commands.put("punish_history", hItem);
        // admin
        CommandItem aItem = new CommandItem();
        aItem.names = Arrays.asList("a", "admin");
        aItem.minLevel = 0;
        cc.commands.put("admin", aItem);
        // config (with sub-commands)
        CommandItem cfgItem = new CommandItem();
        cfgItem.names = Arrays.asList("config", "group");
        cfgItem.minLevel = 0;
        cfgItem.sub = new LinkedHashMap<String, CommandItem>();
        cfgItem.sub.put("new",    CommandConfig.makeSubCmd(true, null));
        cfgItem.sub.put("rename", CommandConfig.makeSubCmd(true, null));
        cfgItem.sub.put("notify", CommandConfig.makeSubCmd(true, null));
        cfgItem.sub.put("set",    CommandConfig.makeSubCmd(true, null));
        cfgItem.sub.put("remove", CommandConfig.makeSubCmd(true, null));
        cfgItem.sub.put("group",  CommandConfig.makeSubCmd(true, -1));
        cc.commands.put("config", cfgItem);
        return cc;
    }

    static CommandItem makeSubCmd(boolean enabled, Integer minLevel) {
        CommandItem item = new CommandItem();
        item.enabled = enabled;
        item.minLevel = minLevel;
        return item;
    }
}

class PunishRecord {
    int id;
    long sender;
    long time;
    String fromGroup;
    long target;
    String method;   // kick, mute, warn
    String content;  // f, 1d2h, 空
    String reason;
    String status;   // 不合规, 已执行, 执行失败, 部分失败, 已撤销
    String failDetail;
    long revokeTime;
    String revokeReason;

    Map<String, Object> toMap() {
        Map<String, Object> map = new LinkedHashMap<String, Object>();
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
        if (method.equals("kick")) return "kick" + (c.equals("f") ? " f" : "");
        if (method.equals("mute")) return "mute " + c;
        if (method.equals("warn")) return "warn";
        return method != null ? method : "";
    }
}

class BlacklistItem {
    long qq;
    String reason;
    long addTime;
    String groupName;

    Map<String, Object> toMap() {
        Map<String, Object> map = new LinkedHashMap<String, Object>();
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

class ConfigState {
    String name;
    ConfigInfo info = new ConfigInfo();
    CommandConfig commands = new CommandConfig();  // 仅含该配置的覆盖项
    List<PunishRecord> records = Collections.synchronizedList(new ArrayList<PunishRecord>());
    Map<Integer, PunishRecord> recordsById = Collections.synchronizedMap(new LinkedHashMap<Integer, PunishRecord>());
    Map<String, Integer> permissions = new ConcurrentHashMap<String, Integer>();
    List<BlacklistItem> blacklist = Collections.synchronizedList(new ArrayList<BlacklistItem>());
    int nextRid = 1;
}

// ==================== 全局数据与配置 ====================
List<String> wakeWords;
Set<String> superAdmins;
String dataDirPath;

Map<String, ConfigState> configs = Collections.synchronizedMap(new LinkedHashMap<>());
CommandConfig globalCommands = CommandConfig.defaults();
Map<String, String> cmdNameMap = new ConcurrentHashMap<>();

boolean initialized = false;
final Object initLock = new Object();

SimpleDateFormat sdf = new SimpleDateFormat("yyyy-MM-dd HH:mm:ss");

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
    // 确保全局 command.json 存在
    File cmdFile = new File(dataDirPath + "/command.json");
    if (!cmdFile.exists()) {
        saveGlobalCommands(CommandConfig.defaults());
        log("info.log", "已创建全局 command.json");
    } else {
        String content = readFileContent(cmdFile);
        if (content == null || content.trim().isEmpty()) {
            saveGlobalCommands(CommandConfig.defaults());
            log("info.log", "command.json 为空，已重建");
        } else {
            try {
                CommandConfig.fromMap(toMap(new org.json.JSONObject(content)));
                log("info.log", "command.json 验证通过");
            } catch (Exception e) {
                File bak = new File(dataDirPath + "/command.json.bak");
                if (bak.exists()) bak.delete();
                cmdFile.renameTo(bak);
                saveGlobalCommands(CommandConfig.defaults());
                log("info.log", "command.json 校验失败(" + e.getMessage() + ")，已备份重建");
            }
        }
    }
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

// ==================== org.json → Map/List 转换辅助 ====================
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

// 函数式接口
interface Function<T, R> {
    R apply(T t);
}

// ==================== 数据持久化 ====================

// 路径辅助
String configDir(String name) { return dataDirPath + "/" + name; }
String punishDir(String name) { return configDir(name) + "/punish"; }

// ---- 通用 JSON 文件读写 ----
List readJsonArray(File file) {
    String content = readFileContent(file);
    if (content == null || content.trim().isEmpty()) return null;
    try {
        org.json.JSONArray arr = new org.json.JSONArray(content);
        return toList(arr);
    } catch (Exception e) {
        // 尝试 .tmp 恢复
        File tmp = new File(file.getPath() + ".tmp");
        if (tmp.exists()) {
            String tmpContent = readFileContent(tmp);
            if (tmpContent != null && !tmpContent.trim().isEmpty()) {
                try {
                    org.json.JSONArray tmpArr = new org.json.JSONArray(tmpContent);
                    log("info.log", "从 .tmp 恢复 " + file.getName() + " 成功");
                    tmp.renameTo(file);
                    return toList(tmpArr);
                } catch (Exception e2) {}
            }
        }
        log("error.log", "读取 JSON 数组失败 " + file.getPath() + ": " + e.getMessage());
        return null;
    }
}

Map<String, Object> readJsonObject(File file) {
    String content = readFileContent(file);
    if (content == null || content.trim().isEmpty()) return null;
    try {
        org.json.JSONObject obj = new org.json.JSONObject(content);
        return toMap(obj);
    } catch (Exception e) {
        // 尝试 .tmp 恢复
        File tmp = new File(file.getPath() + ".tmp");
        if (tmp.exists()) {
            String tmpContent = readFileContent(tmp);
            if (tmpContent != null && !tmpContent.trim().isEmpty()) {
                try {
                    org.json.JSONObject tmpObj = new org.json.JSONObject(tmpContent);
                    log("info.log", "从 .tmp 恢复 " + file.getName() + " 成功");
                    tmp.renameTo(file);
                    return toMap(tmpObj);
                } catch (Exception e2) {}
            }
        }
        log("error.log", "读取 JSON 对象失败 " + file.getPath() + ": " + e.getMessage());
        return null;
    }
}

void writeJsonFile(File file, Object data) {
    // 确保父目录存在
    File parent = file.getParentFile();
    if (parent != null) parent.mkdirs();

    File tmp = new File(file.getPath() + ".tmp");
    try {
        String json;
        if (data instanceof org.json.JSONArray) {
            json = ((org.json.JSONArray) data).toString();
        } else if (data instanceof org.json.JSONObject) {
            json = ((org.json.JSONObject) data).toString();
        } else if (data instanceof List) {
            json = new org.json.JSONArray((List) data).toString();
        } else if (data instanceof Map) {
            json = new org.json.JSONObject((Map) data).toString();
        } else {
            json = String.valueOf(data);
        }
        PrintWriter out = new PrintWriter(new FileWriter(tmp));
        out.print(json);
        out.close();
        if (file.exists()) file.delete();
        tmp.renameTo(file);
    } catch (Exception e) {
        log("error.log", "写入文件失败 " + file.getPath() + ": " + e.getMessage());
        if (tmp.exists()) tmp.delete();
    }
}

// ---- 全局 command.json ----
CommandConfig loadGlobalCommands() {
    File file = new File(dataDirPath + "/command.json");
    Map<String, Object> data = readJsonObject(file);
    if (data != null) {
        try {
            return CommandConfig.fromMap(data);
        } catch (Exception e) {
            log("error.log", "全局 command.json 解析失败: " + e.getMessage());
        }
    }
    CommandConfig def = CommandConfig.defaults();
    saveGlobalCommands(def);
    return def;
}

void saveGlobalCommands(CommandConfig cc) {
    Map<String, Object> cmdMap = new LinkedHashMap<>();
    Map<String, Object> cmds = new LinkedHashMap<>();
    for (Map.Entry<String, CommandItem> e : cc.commands.entrySet()) {
        cmds.put(e.getKey(), e.getValue().toMap());
    }
    cmdMap.put("commands", cmds);
    writeJsonFile(new File(dataDirPath + "/command.json"), cmdMap);
}

// ---- 各配置加载 ----
ConfigInfo loadConfigInfo(String name) {
    File file = new File(configDir(name) + "/groups.json");
    Map<String, Object> data = readJsonObject(file);
    if (data != null) {
        try { return ConfigInfo.fromMap(data); } catch (Exception e) {}
    }
    return new ConfigInfo();
}

CommandConfig loadConfigCommands(String name) {
    File file = new File(configDir(name) + "/command.json");
    Map<String, Object> data = readJsonObject(file);
    if (data != null) {
        try { return CommandConfig.fromMap(data); } catch (Exception e) {}
    }
    return new CommandConfig();  // 空配置表示全部继承全局
}

List<PunishRecord> loadConfigRecords(String name) {
    File file = new File(punishDir(name) + "/records.json");
    List raw = readJsonArray(file);
    List<PunishRecord> result = Collections.synchronizedList(new ArrayList<>());
    if (raw != null) {
        for (Object item : raw) {
            if (item instanceof Map) {
                try { result.add(PunishRecord.fromMap((Map<String, Object>) item)); }
                catch (Exception e) { log("error.log", "解析记录失败: " + e.getMessage()); }
            }
        }
    }
    return result;
}

Map<String, Integer> loadConfigPermissions(String name) {
    File file = new File(configDir(name) + "/permissions.json");
    Map<String, Object> data = readJsonObject(file);
    Map<String, Integer> result = new ConcurrentHashMap<>();
    if (data != null) {
        for (Map.Entry<String, Object> e : data.entrySet()) {
            try {
                int lv = Integer.parseInt(String.valueOf(e.getValue()));
                if (lv >= 1 || lv == -1) result.put(e.getKey(), lv);
            } catch (Exception ex) {}
        }
    }
    return result;
}

List<BlacklistItem> loadConfigBlacklist(String name) {
    File file = new File(punishDir(name) + "/blacklist.json");
    List raw = readJsonArray(file);
    List<BlacklistItem> result = Collections.synchronizedList(new ArrayList<>());
    if (raw != null) {
        for (Object item : raw) {
            if (item instanceof Map) {
                try { result.add(BlacklistItem.fromMap((Map<String, Object>) item)); }
                catch (Exception e) { log("error.log", "解析黑名单失败: " + e.getMessage()); }
            }
        }
    }
    return result;
}

// ---- 各配置保存 ----
void saveConfigInfo(String name, ConfigInfo info) {
    Map<String, Object> map = new LinkedHashMap<>();
    map.put("notifyGroup", info.notifyGroup);
    synchronized (info.executionGroups) {
        map.put("executionGroups", new ArrayList<>(info.executionGroups));
    }
    writeJsonFile(new File(configDir(name) + "/groups.json"), map);
}

void saveConfigCommands(String name, CommandConfig cc) {
    Map<String, Object> cmdMap = new LinkedHashMap<>();
    Map<String, Object> cmds = new LinkedHashMap<>();
    for (Map.Entry<String, CommandItem> e : cc.commands.entrySet()) {
        cmds.put(e.getKey(), e.getValue().toMap());
    }
    cmdMap.put("commands", cmds);
    writeJsonFile(new File(configDir(name) + "/command.json"), cmdMap);
}

void saveConfigRecords(String name, List<PunishRecord> records) {
    List<Map<String, Object>> list = new ArrayList<>();
    synchronized (records) {
        for (PunishRecord r : records) list.add(r.toMap());
    }
    writeJsonFile(new File(punishDir(name) + "/records.json"), list);
}

void saveConfigPermissions(String name, Map<String, Integer> perms) {
    Map<String, Object> map = new LinkedHashMap<>();
    for (Map.Entry<String, Integer> e : perms.entrySet()) {
        map.put(e.getKey(), e.getValue());
    }
    writeJsonFile(new File(configDir(name) + "/permissions.json"), map);
}

void saveConfigBlacklist(String name, List<BlacklistItem> bl) {
    List<Map<String, Object>> list = new ArrayList<>();
    synchronized (bl) {
        for (BlacklistItem b : bl) list.add(b.toMap());
    }
    writeJsonFile(new File(punishDir(name) + "/blacklist.json"), list);
}

void saveConfig(String name) {
    ConfigState cs = configs.get(name);
    if (cs == null) return;
    saveConfigInfo(name, cs.info);
    saveConfigCommands(name, cs.commands);
    saveConfigRecords(name, cs.records);
    saveConfigPermissions(name, cs.permissions);
    saveConfigBlacklist(name, cs.blacklist);
}

void removeConfig(String name) {
    File dir = new File(configDir(name));
    if (dir.exists() && dir.isDirectory()) {
        deleteDir(dir);
        log("info.log", "已删除配置目录: " + name);
    }
}

void renameConfigDir(String oldName, String newName) {
    File oldDir = new File(configDir(oldName));
    File newDir = new File(configDir(newName));
    if (oldDir.exists()) {
        oldDir.renameTo(newDir);
        log("info.log", "配置重命名: " + oldName + " → " + newName);
    }
}

void deleteDir(File dir) {
    File[] files = dir.listFiles();
    if (files != null) {
        for (File f : files) {
            if (f.isDirectory()) deleteDir(f);
            else f.delete();
        }
    }
    dir.delete();
}

void saveAll() {
    for (String name : configs.keySet()) saveConfig(name);
    saveGlobalCommands(globalCommands);
}

// ==================== 初始化 ====================
void init() {
    new File(dataDirPath).mkdirs();

    // 加载全局 command.json
    globalCommands = loadGlobalCommands();

    // 扫描配置子目录
    configs.clear();
    File dataDir = new File(dataDirPath);
    File[] subdirs = dataDir.listFiles(File::isDirectory);
    if (subdirs != null) {
        for (File d : subdirs) {
            String name = d.getName();
            if (name.startsWith(".")) continue;
            if (!new File(d, "groups.json").exists()) continue;

            ConfigState cs = new ConfigState();
            cs.name = name;
            cs.info = loadConfigInfo(name);
            cs.commands = loadConfigCommands(name);
            cs.records = loadConfigRecords(name);
            cs.permissions = new ConcurrentHashMap<>(loadConfigPermissions(name));
            cs.blacklist = loadConfigBlacklist(name);

            int maxId = 0;
            for (PunishRecord r : cs.records) {
                cs.recordsById.put(r.id, r);
                if (r.id > maxId) maxId = r.id;
            }
            cs.nextRid = maxId + 1;
            configs.put(name, cs);
        }
    }

    // 无配置时创建默认
    if (configs.isEmpty()) {
        ConfigState def = new ConfigState();
        def.name = "default";
        configs.put("default", def);
        saveConfig("default");
        log("info.log", "已创建默认配置 'default'");
    }

    buildCmdNameMap();
    initHelpMaps();

    int totalRecords = 0;
    for (ConfigState cs : configs.values()) totalRecords += cs.records.size();
    log("info.log", "已加载: " + configs.size() + " 配置 " + totalRecords + " 记录");
}

void buildCmdNameMap() {
    cmdNameMap.clear();
    // 全局命令
    for (Map.Entry<String, CommandItem> e : globalCommands.commands.entrySet()) {
        for (String n : e.getValue().names) {
            if (n != null && !n.isEmpty()) cmdNameMap.put(n, e.getKey());
        }
    }
    // 各配置覆盖
    for (ConfigState cs : configs.values()) {
        for (Map.Entry<String, CommandItem> e : cs.commands.commands.entrySet()) {
            for (String n : e.getValue().names) {
                if (n != null && !n.isEmpty()) cmdNameMap.put(n, e.getKey());
            }
        }
    }
}

// ==================== 辅助方法 ====================

int getPermissionLevel(String qq) {
    if (superAdmins.contains(qq)) return 0;
    int best = -1;
    for (ConfigState cs : configs.values()) {
        Integer lv = cs.permissions.get(qq);
        if (lv != null && lv > best) best = lv;
    }
    return best;
}

List<ConfigState> findConfigsByGroup(String groupId) {
    List<ConfigState> result = new ArrayList<>();
    for (ConfigState cs : configs.values()) {
        if (groupId.equals(cs.info.notifyGroup) || cs.info.executionGroups.contains(groupId)) {
            result.add(cs);
        }
    }
    return result;
}

ConfigState getConfig(String name) {
    return configs.get(name);
}

CommandConfig resolvedCommands(ConfigState cs) {
    Map<String, CommandItem> merged = new LinkedHashMap<>(globalCommands.commands);
    merged.putAll(cs.commands.commands);
    CommandConfig cc = new CommandConfig();
    cc.commands = merged;
    return cc;
}

String primaryCmdName(CommandItem item) {
    return (item.names != null && !item.names.isEmpty()) ? item.names.get(0) : "";
}

int resolveMinLevel(CommandItem item, CommandItem parent) {
    if (item.minLevel != null) return item.minLevel;
    if (parent != null && parent.minLevel != null) return parent.minLevel;
    return 1;
}

void sendGroupMsg(String group, String msg) {
    sendMsg(group, msg, 2);
}

void notifyNotifyGroup(ConfigState cs, String msg) {
    if (cs != null && cs.info.notifyGroup != null) {
        sendGroupMsg(cs.info.notifyGroup, msg);
    }
}

// 解析时长（秒），返回null表示格式错误
Long parseDurationSeconds(String dur) {
    if (dur == null || dur.isEmpty()) return null;
    try {
        double days = Double.parseDouble(dur);
        return (long) (days * 86400);
    } catch (Exception e) {}
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

String extractQQ(String text) {
    if (text == null) return null;
    Matcher m = Pattern.compile("\\d+").matcher(text);
    if (m.find()) return m.group();
    return null;
}

String resolveTargetQQ(Object msgData, String text) {
    List<String> atList = msgData.atList;
    if (atList != null && !atList.isEmpty()) {
        return atList.get(0);
    }
    return extractQQ(text);
}

// ==================== 消息入口 ====================
void onMsg(Object msgData) {
    if (!initialized) {
        synchronized (initLock) {
            if (!initialized) {
                init();
                initialized = true;
            }
        }
    }

    int type = msgData.type;
    if (type != 2) return;
    String text = msgData.msg != null ? msgData.msg.trim() : "";
    String peerUin = msgData.peerUin;
    String userUin = msgData.userUin;

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

    // 权限等级
    int level = getPermissionLevel(userUin);
    if (level < 0) return;

    String[] parts = text.split("\\s+");
    if (parts.length == 0) return;
    String cmd = parts[0].toLowerCase();

    // 命令名 → 内部名
    String internal = cmdNameMap.get(cmd);
    if (internal == null) return;

    switch (internal) {
        case "help":
            cmdHelp(level, peerUin, userUin, parts, msgData);
            break;
        case "punish_do":
            cmdPunish(level, userUin, peerUin, parts, msgData);
            break;
        case "punish_revoke":
            cmdRevoke(level, userUin, peerUin, parts);
            break;
        case "punish_history":
            cmdQuery(level, userUin, peerUin, parts, msgData);
            break;
        case "admin":
            cmdPermission(level, userUin, peerUin, parts, msgData);
            break;
        case "config":
            cmdConfig(level, userUin, peerUin, parts);
            break;
    }
}

// ==================== /help ====================

// 命令描述映射（在 init() 中初始化）
Map<String, String> CMD_DESC;
Map<String, String> CMD_FORMAT;
Map<String, List<String>> CMD_EXAMPLES;
Map<String, List<String>> CMD_DETAIL;

void initHelpMaps() {
    CMD_DESC = new LinkedHashMap<String, String>();
    CMD_DESC.put("help", "查看帮助");
    CMD_DESC.put("punish_do", "处罚成员");
    CMD_DESC.put("punish_revoke", "撤销处罚");
    CMD_DESC.put("punish_history", "查询处罚记录");
    CMD_DESC.put("admin", "权限管理");
    CMD_DESC.put("config", "配置管理");

    CMD_FORMAT = new LinkedHashMap<String, String>();
    CMD_FORMAT.put("help",           "{w}{cmd} [命令]");
    CMD_FORMAT.put("punish_do",      "{w}{cmd} [配置] <目标> <方式> [内容] <原因>");
    CMD_FORMAT.put("punish_revoke",  "{w}{cmd} [配置] <记录ID> [撤销原因]");
    CMD_FORMAT.put("punish_history", "{w}{cmd} [配置] [目标] [-i]");
    CMD_FORMAT.put("admin",          "{w}{cmd} [配置] <目标> [等级]");
    CMD_FORMAT.put("config",         "{w}{cmd} <子命令>");

    CMD_EXAMPLES = new LinkedHashMap<String, List<String>>();
    CMD_EXAMPLES.put("help",           Arrays.asList("{w}{cmd} <命令>"));
    CMD_EXAMPLES.put("punish_do",      Arrays.asList("{w}{cmd} @某人 mute 1d2h 广告刷屏"));
    CMD_EXAMPLES.put("punish_revoke",  Arrays.asList("{w}{cmd} 5 误判"));
    CMD_EXAMPLES.put("punish_history", Arrays.asList("{w}{cmd} @某人 -i"));
    CMD_EXAMPLES.put("admin",          Arrays.asList("{w}{cmd} @某人 1"));
    CMD_EXAMPLES.put("config",         Arrays.asList("{w}{cmd} new 反馈组", "{w}{cmd} 反馈组 set"));

    CMD_DETAIL = new LinkedHashMap<String, List<String>>();
    CMD_DETAIL.put("help", Arrays.asList(
        "# {w}{cmd} — 查看帮助",
        "> {w}{cmd} [命令]",
        "- 无参数时显示按配置分组的可用指令",
        "- 指定命令时显示该命令的详细用法",
        "~ {w}{cmd}  → 概览",
        "~ {w}{cmd} <命令>  → 详情"
    ));
    CMD_DETAIL.put("punish_do", Arrays.asList(
        "# {w}{cmd} — 处罚成员",
        "> {w}{cmd} [配置] <目标> <方式> [内容] <原因>",
        "- <目标>  @某人 或 QQ号",
        "- [配置]  指定配置名（可选）",
        "- <方式>  kick / mute / warn",
        "- [内容]  kick可选f(黑名单)；mute必填时长；warn不需要",
        "- <原因>  缺失时记为不合规，不执行",
        "! 时长格式：纯数字=天  组合 1d2h30m",
        "~ {w}{cmd} @某人 mute 1d2h 广告刷屏"
    ));
    CMD_DETAIL.put("punish_revoke", Arrays.asList(
        "# {w}{cmd} — 撤销处罚",
        "> {w}{cmd} [配置] <记录ID> [撤销原因]",
        "- [配置]  多配置群必填，单配置群可选",
        "! 仅可撤销已执行/执行失败/部分失败的记录",
        "~ {w}{cmd} 5  /  {w}{cmd} 反馈组 5 误判"
    ));
    CMD_DETAIL.put("punish_history", Arrays.asList(
        "# {w}{cmd} — 查询记录",
        "> {w}{cmd} [配置] [目标] [-i]",
        "- [配置]  指定配置名（多配置群必填）",
        "- 无参数 全部记录表格  /  -i  图片详情",
        "! 状态颜色：绿已执行 橙已撤销 红失败 灰不合规"
    ));
    CMD_DETAIL.put("admin", Arrays.asList(
        "# {w}{cmd} — 权限管理",
        "> {w}{cmd} [配置] <目标> [等级]",
        "- -1=普通成员  ≥1 数字越大权限越低（默认1）",
        "! 不可设0，不可改自己",
        "~ {w}{cmd} @某人 1  /  {w}{cmd} 反馈组 @某人 2"
    ));
    CMD_DETAIL.put("config", Arrays.asList(
        "# {w}{cmd} — 配置管理",
        "> {w}{cmd} new <名称>         创建新配置",
        "> {w}{cmd} rename <旧> <新>    重命名配置",
        "> {w}{cmd} <名称> notify      设本群为通知群",
        "> {w}{cmd} <名称> set         本群加入执行群",
        "> {w}{cmd} <名称> remove      本群移出配置",
        "> {w}{cmd} <名称> group       查看配置信息",
        "! 一个群可属于多个配置，通知群也可设为执行群"
    ));
}

void cmdHelp(int level, String group, String senderId, String[] parts, Object msgData) {
    String w = wakeWords.get(0);

    // 获取发送者的群名片
    String senderCard = "";
    try {
        Object sender = msgData.sender;
        if (sender != null) {
            String card = sender.card;
            String nick = sender.nickname;
            if (card != null && !card.isEmpty()) senderCard = card;
            else if (nick != null && !nick.isEmpty()) senderCard = nick;
        }
    } catch (Exception e) {}

    String subtitle;
    if (!senderCard.isEmpty()) {
        subtitle = senderCard + " (" + senderId + ")";
    } else {
        subtitle = "QQ: " + senderId;
    }

    List<ConfigState> cfgs = findConfigsByGroup(group);

    // 解析要查看的命令
    String detailInternal = null;
    String extCmd = null;
    if (parts.length >= 2) {
        extCmd = parts[1].toLowerCase();
        detailInternal = cmdNameMap.get(extCmd);
        if (detailInternal == null) {
            List<String> known = new ArrayList<>(new LinkedHashSet<>(cmdNameMap.values()));
            Collections.sort(known);
            sendGroupMsg(group, "未知命令：" + extCmd + "，可用：" + String.join(", ", known));
            return;
        }
    }

    List<String> lines;
    String title;
    if (detailInternal != null) {
        lines = buildDetailLines(w, detailInternal, extCmd, cfgs);
        title = "帮助 — " + extCmd;
    } else {
        lines = buildOverviewLines(w, cfgs, senderId);
        title = "HollowGroupManager 帮助";
    }

    sendHelpImage(group, title, subtitle, lines);
}

// 构建概览行：@ 标记卡片起始，@@ 标记结束，= 居中标题
List<String> buildOverviewLines(String w, List<ConfigState> configs, String senderId) {
    List<String> lines = new ArrayList<>();
    lines.add("# 可用指令");
    lines.add("- 唤醒词: " + String.join(", ", wakeWords));
    lines.add("");

    String[] ORDER = {"help", "punish_do", "punish_revoke", "punish_history", "admin", "config"};

    if (configs.isEmpty()) {
        int userLevel = superAdmins.contains(senderId) ? 0 : -1;
        lines.add("@");
        lines.add("= ── 全局（当前群未关联配置）──");
        lines.addAll(renderFilteredCmds(globalCommands, new LinkedHashSet<String>(Arrays.asList(ORDER)), userLevel, w));
        lines.add("@@");
        return lines;
    }

    lines.add("- 本群关联 " + configs.size() + " 个配置");
    lines.add("");

    // 分析各命令在各配置中的自定义情况
    Map<String, Set<String>> customizedBy = new LinkedHashMap<>();
    for (String cmd : ORDER) customizedBy.put(cmd, new LinkedHashSet<>());
    for (ConfigState cfg : configs) {
        for (String cmd : ORDER) {
            if (cfg.commands.commands.containsKey(cmd)) {
                customizedBy.get(cmd).add(cfg.name);
            }
        }
    }

    // 全局卡片：包含至少一个配置未自定义的命令
    Set<String> globalCardCmds = new LinkedHashSet<>();
    Map<String, Set<String>> perCfgCmds = new LinkedHashMap<>();
    for (ConfigState cfg : configs) perCfgCmds.put(cfg.name, new LinkedHashSet<>());

    Set<String> allNames = new LinkedHashSet<>();
    for (ConfigState cfg : configs) allNames.add(cfg.name);

    for (String cmd : ORDER) {
        Set<String> customCfgs = customizedBy.get(cmd);
        if (!customCfgs.equals(allNames)) {
            globalCardCmds.add(cmd);
        }
        for (String cfgName : customCfgs) {
            perCfgCmds.get(cfgName).add(cmd);
        }
    }

    // 发送者在各配置中的等级
    Map<String, Integer> cfgLevels = new LinkedHashMap<>();
    for (ConfigState cfg : configs) {
        cfgLevels.put(cfg.name, superAdmins.contains(senderId) ? 0 :
            cfg.permissions.getOrDefault(senderId, -1));
    }

    // 全局卡片
    if (!globalCardCmds.isEmpty()) {
        int bestLevel = superAdmins.contains(senderId) ? 0 : -1;
        if (bestLevel != 0) {
            for (int lv : cfgLevels.values()) {
                if (lv > bestLevel) bestLevel = lv;
            }
            if (bestLevel == -1) bestLevel = -1;  // 保持在 -1
        }
        lines.add("@");
        lines.add("= ── 全局 ──");
        lines.addAll(renderFilteredCmds(globalCommands, globalCardCmds, bestLevel, w));
        lines.add("@@");
        lines.add("");
    }

    // 各配置卡片
    for (ConfigState cfg : configs) {
        Set<String> myCmds = perCfgCmds.get(cfg.name);
        int lv = cfgLevels.get(cfg.name);
        String lvLabel = lv == 0 ? "超级管理员（0）" : (lv == -1 ? "普通成员（-1）" : "管理员（" + lv + "）");
        String ng = cfg.info.notifyGroup != null ? cfg.info.notifyGroup : "未设";
        int egCount = 0;
        synchronized (cfg.info.executionGroups) { egCount = cfg.info.executionGroups.size(); }

        lines.add("@");
        lines.add("= ── 配置 \"" + cfg.name + "\" ──");
        lines.add("- 通知群: " + ng + "  |  执行群: " + egCount + "个  |  记录: " + cfg.records.size() + "条"
                 + "  |  我的权限: " + lvLabel);
        lines.add("");
        lines.addAll(renderFilteredCmds(resolvedCommands(cfg), myCmds, lv, w));
        lines.add("@@");
        lines.add("");
    }
    return lines;
}

List<String> renderFilteredCmds(CommandConfig cc, Set<String> include, int userLevel, String w) {
    List<String> lines = new ArrayList<>();
    String[] order = {"help", "punish_do", "punish_revoke", "punish_history", "admin", "config"};
    for (String internal : order) {
        if (!include.contains(internal)) continue;
        CommandItem item = cc.commands.get(internal);
        if (item == null || !item.enabled) continue;

        int minLv = resolveMinLevel(item, null);
        boolean visible = (userLevel == 0) || (userLevel == -1 && minLv == -1) || (userLevel > 0 && userLevel <= minLv);
        if (!visible) continue;

        String primary = primaryCmdName(item);
        List<String> aliases = new ArrayList<>();
        if (item.names != null && item.names.size() > 1) {
            for (int i = 1; i < item.names.size(); i++) aliases.add(item.names.get(i));
        }

        String desc = CMD_DESC.getOrDefault(internal, "");
        String minStr = "";
        if (item.minLevel != null && item.minLevel != -1) {
            minStr = "  ·需等级 " + item.minLevel;
        }

        String fmt = CMD_FORMAT.getOrDefault(internal, "");
        if (!fmt.isEmpty()) {
            fmt = fmt.replace("{w}", w).replace("{cmd}", primary);
            lines.add("> " + fmt + minStr);
        }
        if (!aliases.isEmpty()) {
            StringBuilder sb = new StringBuilder();
            for (String a : aliases) sb.append(" ").append(w).append(a);
            lines.add("- 别名:" + sb.toString());
        }
        lines.add("- " + desc);

        List<String> examples = CMD_EXAMPLES.getOrDefault(internal, new ArrayList<>());
        for (String ex : examples) {
            lines.add("~ " + ex.replace("{w}", w).replace("{cmd}", primary));
        }
        lines.add("");
    }
    return lines;
}

List<String> buildDetailLines(String w, String internal, String extCmd, List<ConfigState> configs) {
    List<String> lines = new ArrayList<>();
    lines.add("# " + CMD_DESC.getOrDefault(internal, internal));

    // 收集完整的 names 列表
    List<String> allNames = new ArrayList<>();
    for (ConfigState cfg : configs) {
        CommandConfig resolved = resolvedCommands(cfg);
        CommandItem item = resolved.commands.get(internal);
        if (item != null && item.enabled && item.names != null && item.names.contains(extCmd)) {
            allNames = new ArrayList<>(item.names);
            break;
        }
    }
    if (allNames.isEmpty()) {
        CommandItem item = globalCommands.commands.get(internal);
        if (item != null && item.names != null) allNames = new ArrayList<>(item.names);
    }

    // 别名（除用户输入的名字外）
    List<String> aliases = new ArrayList<>();
    for (String n : allNames) {
        if (!n.equals(extCmd)) aliases.add(n);
    }
    if (!aliases.isEmpty()) {
        StringBuilder sb = new StringBuilder();
        for (String a : aliases) sb.append(" ").append(w).append(a);
        lines.add("- 别名:" + sb.toString());
    }

    // 各配置中的自定义
    Set<String> shown = new LinkedHashSet<>();
    for (ConfigState cfg : configs) {
        CommandItem own = cfg.commands.commands.get(internal);
        if (own == null) continue;
        CommandConfig resolved = resolvedCommands(cfg);
        CommandItem item = resolved.commands.get(internal);
        if (item != null && item.enabled && item.names != null && item.names.contains(extCmd)) {
            String primary = primaryCmdName(item);
            String nameStr = w + primary;
            if (!shown.contains(nameStr)) {
                shown.add(nameStr);
                int lv = resolveMinLevel(item, null);
                lines.add("- 配置 [" + cfg.name + "]: " + nameStr + "  需等级: " + lv);
            }
        }
    }

    if (shown.isEmpty()) {
        CommandItem item = globalCommands.commands.get(internal);
        if (item != null && item.names != null && item.names.contains(extCmd)) {
            String nameStr = w + primaryCmdName(item);
            int lv = resolveMinLevel(item, null);
            lines.add("- 全局: " + nameStr + "  需等级: " + lv);
        }
    }

    // 详细用法
    List<String> detail = CMD_DETAIL.getOrDefault(internal, new ArrayList<>());
    if (!detail.isEmpty()) {
        lines.add("");
        for (String d : detail) {
            lines.add(d.replace("{w}", w).replace("{cmd}", extCmd));
        }
    }
    return lines;
}

// ==================== 帮助图片生成 ====================

void sendHelpImage(String group, String title, String subtitle, List<String> lines) {
    try {
        String path = pluginPath + "/help_" + group + "_" + System.currentTimeMillis() + ".png";
        generateHelpImage(title, subtitle, lines, path);
        sendPic(group, path, 2);
        new File(path).delete();
    } catch (Exception e) {
        // 图片生成失败时回退到文字
        StringBuilder sb = new StringBuilder(title).append("\n");
        for (String line : lines) {
            if (line.isEmpty()) { sb.append("\n"); continue; }
            sb.append(line.length() > 2 ? line.substring(2) : line).append("\n");
        }
        sendGroupMsg(group, sb.toString());
    }
}

void generateHelpImage(String title, String subtitle, List<String> lines, String outputPath) throws IOException {
    int imgWidth = 820;
    int leftPad = 28;
    int rightPad = 20;

    // ---- 第一遍：计算位置 ----
    // cy 追踪每行底部位置，textY = cy - offset（与原始代码一致）
    // 存储：每行的 [cy(底部), prefixAscii, 是否在卡片内]
    List<int[]> rowInfo = new ArrayList<int[]>();
    List<String> rowTexts = new ArrayList<String>();
    List<Boolean> rowInCard = new ArrayList<Boolean>();

    int y = 48;
    if (subtitle != null && !subtitle.isEmpty()) y += 36;
    int divY = y + 12;
    int cy = divY + 28;

    // 卡片跟踪
    int PAD = 16;
    int cardMargin = 16;
    Integer cardStartCy = null;  // 卡片起始行的 cy_before（即上一行的底部）
    List<int[]> cards = new ArrayList<int[]>();  // [topY, bottomY]

    for (int i = 0; i < lines.size(); i++) {
        String line = lines.get(i);
        if (line.isEmpty()) { cy += 18; continue; }

        char prefix = line.charAt(0);
        String text = line.length() > 2 ? line.substring(2) : "";

        // 卡片标记：@ 开始，@@ 结束（不占高度）
        if (prefix == '@') {
            if (line.equals("@@")) {
                if (cardStartCy != null) {
                    cards.add(new int[]{cardStartCy, cy});
                    cardStartCy = null;
                }
            } else {
                cardStartCy = cy;  // 卡片从当前 cy 开始（上一行底部）
            }
            continue;
        }

        // 按原始代码：先加行高，文字画在 cy - offset
        int offset;
        switch (prefix) {
            case '=': case '#': cy += 42; offset = 12; break;
            case '>':           cy += 38; offset = 10; break;
            case '-':           cy += 34; offset = 9;  break;
            case '~':           cy += 30; offset = 8;  break;
            case '!':           cy += 34; offset = 9;  break;
            default:            cy += 34; offset = 9;  break;
        }

        rowInfo.add(new int[]{cy, (int) prefix, offset});
        rowTexts.add(text);
        rowInCard.add(cardStartCy != null);
    }

    // 未闭合的卡片
    if (cardStartCy != null) {
        cards.add(new int[]{cardStartCy, cy});
    }

    // 尾部 AGPL
    int footerTop = cy + 20;  // 内容底部 + 20px 间距
    int footerLine1Y = footerTop + 28;
    int footerLine2Y = footerTop + 50;
    int imgHeight = footerTop + 60;

    // ---- 第二遍：绘制 ----
    Bitmap bitmap = Bitmap.createBitmap(imgWidth, imgHeight, Bitmap.Config.ARGB_8888);
    Canvas canvas = new Canvas(bitmap);
    Paint paint = new Paint();
    paint.setAntiAlias(true);
    canvas.drawColor(Color.WHITE);

    // 卡片背景
    float cardX0 = (float) cardMargin;
    float cardX1 = (float) (imgWidth - cardMargin);
    for (int[] card : cards) {
        float cy0 = (float) (card[0] + 4);   // 卡片上边：起始行顶部 + 少许间距
        float cy1 = (float) (card[1] + PAD); // 卡片下边：结束行底部 + padding

        paint.setStyle(Paint.Style.FILL);
        paint.setColor(Color.parseColor("#F5F7FF"));
        canvas.drawRoundRect(cardX0, cy0, cardX1, cy1, 14f, 14f, paint);

        paint.setStyle(Paint.Style.STROKE);
        paint.setStrokeWidth(1f);
        paint.setColor(Color.parseColor("#D6DBF0"));
        canvas.drawRoundRect(cardX0, cy0, cardX1, cy1, 14f, 14f, paint);
    }
    // 恢复 FILL 样式
    paint.setStyle(Paint.Style.FILL);
    paint.setStrokeWidth(1f);

    // 标题
    paint.setColor(Color.parseColor("#1A237E"));
    paint.setTypeface(Typeface.DEFAULT_BOLD);
    paint.setTextSize(32);
    canvas.drawText(title, leftPad, 44, paint);

    // 副标题
    if (subtitle != null && !subtitle.isEmpty()) {
        paint.setColor(Color.parseColor("#757575"));
        paint.setTypeface(Typeface.DEFAULT);
        paint.setTextSize(22);
        canvas.drawText(subtitle, leftPad, 78, paint);
    }

    // 分隔线
    paint.setColor(Color.parseColor("#E0E0E0"));
    paint.setStrokeWidth(2);
    canvas.drawLine(leftPad, divY, imgWidth - rightPad, divY, paint);
    paint.setStrokeWidth(1);

    // 文字内容（使用原始代码的 cy - offset 定位）
    for (int i = 0; i < rowInfo.size(); i++) {
        int[] ri = rowInfo.get(i);
        int lineCy = ri[0];      // 行底部 cy
        char prefix = (char) ri[1];
        int offset = ri[2];      // cy - offset = 文字基线
        String text = rowTexts.get(i);
        boolean inCard = rowInCard.get(i);

        int indent = (prefix == '=' || prefix == '#' || prefix == '>') ? 0 : 20;
        if (inCard) indent += PAD;
        int textY = lineCy - offset;

        switch (prefix) {
            case '=':
                paint.setColor(Color.parseColor("#1565C0"));
                paint.setTypeface(Typeface.DEFAULT_BOLD);
                paint.setTextSize(22);
                float tw = paint.measureText(text);
                canvas.drawText(text, (int)((imgWidth - tw) / 2), textY, paint);
                break;
            case '#':
                paint.setColor(Color.parseColor("#1565C0"));
                paint.setTypeface(Typeface.DEFAULT_BOLD);
                paint.setTextSize(22);
                canvas.drawText(text, leftPad + indent, textY, paint);
                break;
            case '>':
                paint.setColor(Color.parseColor("#1A237E"));
                paint.setTypeface(Typeface.DEFAULT_BOLD);
                paint.setTextSize(20);
                canvas.drawText(text, leftPad + indent, textY, paint);
                break;
            case '-':
                paint.setColor(Color.BLACK);
                paint.setTypeface(Typeface.DEFAULT);
                paint.setTextSize(19);
                canvas.drawText(text, leftPad + indent, textY, paint);
                break;
            case '~':
                paint.setColor(Color.parseColor("#757575"));
                paint.setTypeface(Typeface.DEFAULT);
                paint.setTextSize(18);
                canvas.drawText(text, leftPad + indent, textY, paint);
                break;
            case '!':
                paint.setColor(Color.parseColor("#E65100"));
                paint.setTypeface(Typeface.DEFAULT);
                paint.setTextSize(19);
                canvas.drawText(text, leftPad + indent, textY, paint);
                break;
            default:
                paint.setColor(Color.BLACK);
                paint.setTypeface(Typeface.DEFAULT);
                paint.setTextSize(19);
                canvas.drawText(text, leftPad + indent, textY, paint);
                break;
        }
    }

    // ---- 尾部 AGPL 声明 ----
    paint.setColor(Color.parseColor("#E0E0FF"));
    paint.setStrokeWidth(2);
    canvas.drawLine(leftPad, footerTop, imgWidth - rightPad, footerTop, paint);
    paint.setStrokeWidth(1);

    paint.setTypeface(Typeface.DEFAULT);
    paint.setTextSize(16);
    paint.setColor(Color.parseColor("#9E9EBB"));

    String footer1 = "License: GNU AGPL v3.0";
    String footer2 = "https://github.com/Hollow-YK/HollowGroupManager";
    float fw1 = paint.measureText(footer1);
    float fw2 = paint.measureText(footer2);
    canvas.drawText(footer1, (int)((imgWidth - fw1) / 2), footerLine1Y, paint);
    canvas.drawText(footer2, (int)((imgWidth - fw2) / 2), footerLine2Y, paint);

    FileOutputStream fos = new FileOutputStream(outputPath);
    bitmap.compress(Bitmap.CompressFormat.PNG, 100, fos);
    fos.close();
}

// ==================== /p 处罚 ====================

final List<String> VALID_METHODS = Arrays.asList("kick", "mute", "warn");

void cmdPunish(int level, String sender, String group, String[] parts, Object msgData) {
    if (parts.length < 2) {
        sendGroupMsg(group, "格式：<唤醒词>p [配置] <目标> <方式> [内容] <原因>");
        return;
    }

    // 解析目标
    String targetQQ = resolveTargetQQ(msgData, parts[1]);
    if (targetQQ == null || targetQQ.isEmpty()) {
        sendGroupMsg(group, "未找到被处罚者QQ，请艾特或输入QQ号");
        return;
    }

    // 尝试解析配置名
    String cfgName = null;
    int methodIdx = 2;
    if (parts.length > 2 && !VALID_METHODS.contains(parts[2].toLowerCase())) {
        cfgName = parts[2];
        methodIdx = 3;
    }

    // 确定配置范围
    List<ConfigState> matchCfgs = findConfigsByGroup(group);
    if (matchCfgs.isEmpty()) return;  // 不响应

    List<ConfigState> targetCfgs;
    if (cfgName != null) {
        targetCfgs = new ArrayList<>();
        for (ConfigState c : matchCfgs) {
            if (c.name.equals(cfgName)) targetCfgs.add(c);
        }
        if (targetCfgs.isEmpty()) {
            sendGroupMsg(group, "配置 \"" + cfgName + "\" 不存在或不包含本群");
            return;
        }
    } else {
        targetCfgs = matchCfgs;
    }

    // 解析方式
    if (methodIdx >= parts.length) {
        sendGroupMsg(group, "缺少处罚方式（kick / mute / warn）");
        return;
    }
    String method = parts[methodIdx].toLowerCase();
    if (!VALID_METHODS.contains(method)) {
        sendGroupMsg(group, "无效处罚方式，可选：kick, mute, warn");
        return;
    }

    String content = "";
    int reasonStart;
    if (method.equals("mute")) {
        if (parts.length < methodIdx + 2) {
            sendGroupMsg(group, "禁言缺少时长");
            return;
        }
        content = parts[methodIdx + 1];
        reasonStart = methodIdx + 2;
        if (parseDurationSeconds(content) == null) {
            sendGroupMsg(group, "时长格式错误，支持数字(天)或组合如1d2h30m");
            return;
        }
    } else if (method.equals("kick")) {
        if (parts.length > methodIdx + 1 && parts[methodIdx + 1].equalsIgnoreCase("f")) {
            content = "f";
            reasonStart = methodIdx + 2;
        } else {
            reasonStart = methodIdx + 1;
        }
    } else { // warn
        reasonStart = methodIdx + 1;
    }

    // 原因检查
    if (reasonStart >= parts.length) {
        // 不合规
        for (ConfigState cfg : targetCfgs) {
            PunishRecord r = createPunishRecord(cfg, sender, group, Long.parseLong(targetQQ), method, content, "", "不合规");
            notifyNotifyGroup(cfg, "[不合规] 处罚（" + r.id + "）：发起者（" + sender + "）在群（" + group + "）发起的处罚缺少原因，未执行。");
        }
        saveAll();
        sendGroupMsg(group, "原因缺失，已记录为[不合规]，未执行处罚。");
        return;
    }

    StringBuilder reasonBuilder = new StringBuilder();
    for (int i = reasonStart; i < parts.length; i++) {
        if (i > reasonStart) reasonBuilder.append(" ");
        reasonBuilder.append(parts[i]);
    }
    String reason = reasonBuilder.toString();

    // 收集所有执行群（去重）
    Set<String> allExecGroups = new LinkedHashSet<>();
    for (ConfigState cfg : targetCfgs) {
        synchronized (cfg.info.executionGroups) {
            allExecGroups.addAll(cfg.info.executionGroups);
        }
    }

    long tidLong = Long.parseLong(targetQQ);

    // 创建记录
    List<Object[]> recordsInfo = new ArrayList<>();  // [ConfigState, PunishRecord]
    for (ConfigState cfg : targetCfgs) {
        PunishRecord r = createPunishRecord(cfg, sender, group, tidLong, method, content, reason, "执行中");
        recordsInfo.add(new Object[]{cfg, r});
    }

    // 执行处罚
    boolean anyOk = false;
    boolean anyFail = false;
    List<String> failGroups = new ArrayList<>();

    for (String eg : allExecGroups) {
        // 检查成员在群
        boolean memberInGroup = false;
        List groupMembers = getGroupMemberList(eg);
        if (groupMembers != null) {
            for (Object m : groupMembers) {
                if (m.uin != null && m.uin.equals(targetQQ)) {
                    memberInGroup = true;
                    break;
                }
            }
        }
        if (!memberInGroup) continue;

        // mute 状态检查
        if (method.equals("mute")) {
            List prohibitList = getProhibitList(eg);
            if (prohibitList != null) {
                for (Object p : prohibitList) {
                    if (p.user.equals(targetQQ)) {
                        for (Object[] ri : recordsInfo) {
                            ConfigState cfg = (ConfigState) ri[0];
                            PunishRecord r = (PunishRecord) ri[1];
                            notifyNotifyGroup(cfg, "[提示] 处罚「" + r.id + "」在群" + eg + "成员" + targetQQ + "已被禁言，将更新时长。");
                        }
                        break;
                    }
                }
            }
        }

        try {
            if (method.equals("kick")) {
                boolean toBlack = "f".equals(content);
                kickGroup(eg, targetQQ, false);
                // 验证
                boolean stillInGroup = false;
                List memberListAfter = getGroupMemberList(eg);
                if (memberListAfter != null) {
                    for (Object m : memberListAfter) {
                        if (m.uin != null && m.uin.equals(targetQQ)) {
                            stillInGroup = true;
                            break;
                        }
                    }
                }
                if (stillInGroup) throw new RuntimeException("踢出失败：bot权限不足，成员仍在群内");
                if (toBlack) {
                    for (ConfigState cfg : targetCfgs) {
                        addToBlacklist(cfg, tidLong, reason, cfg.name);
                    }
                    sendGroupMsg(eg, "[atUin=" + targetQQ + "] 因「" + reason + "」被踢出并加入黑名单。");
                } else {
                    sendGroupMsg(eg, "[atUin=" + targetQQ + "] 因「" + reason + "」被踢出。");
                }
            } else if (method.equals("mute")) {
                long sec = parseDurationSeconds(content);
                shutUp(eg, targetQQ, sec);
                // 验证
                boolean muteSuccess = false;
                List prohibitCheck = getProhibitList(eg);
                if (prohibitCheck != null) {
                    for (Object p : prohibitCheck) {
                        if (p.user != null && p.user.equals(targetQQ)) {
                            muteSuccess = true;
                            break;
                        }
                    }
                }
                if (!muteSuccess) throw new RuntimeException("禁言失败：bot权限不足，成员未被禁言");
                sendGroupMsg(eg, "[atUin=" + targetQQ + "] 因「" + reason + "」被禁言 " + content + "。");
            } else {
                sendGroupMsg(eg, "[atUin=" + targetQQ + "] 因「" + reason + "」被警告。");
            }
            anyOk = true;
        } catch (Exception e) {
            anyFail = true;
            failGroups.add(eg);
            for (Object[] ri : recordsInfo) {
                notifyNotifyGroup((ConfigState) ri[0],
                    "[异常] 处罚「" + ((PunishRecord) ri[1]).id + "」在群" + eg + "执行失败：" + e.getMessage());
            }
        }
    }

    // 更新状态
    String failStr = anyFail ? "失败群：" + String.join(",", failGroups) : "";
    for (Object[] ri : recordsInfo) {
        PunishRecord r = (PunishRecord) ri[1];
        if (anyFail && !anyOk) {
            r.status = "执行失败";
            r.failDetail = failStr;
        } else if (anyFail) {
            r.status = "部分失败";
            r.failDetail = failStr;
        } else {
            r.status = "已执行";
        }
    }

    // 通知各配置的通知群
    Set<String> notified = new LinkedHashSet<>();
    for (Object[] ri : recordsInfo) {
        ConfigState cfg = (ConfigState) ri[0];
        PunishRecord r = (PunishRecord) ri[1];
        String ng = cfg.info.notifyGroup;
        if (ng != null && !notified.contains(ng)) {
            notified.add(ng);
            String fb = "处罚已执行。";
            if (anyFail && !anyOk) fb = "处罚执行失败（" + failStr + "）";
            else if (anyFail) fb = "处罚部分失败（" + failStr + "）";
            try {
                sendGroupMsg(ng,
                    "处罚「" + r.id + "」：" + sender + "在" + group + "发起对"
                    + targetQQ + "的「" + r.describe() + "」处罚，原因：「" + reason + "」，"
                    + "状态：" + r.status
                    + (!r.failDetail.isEmpty() ? "（" + r.failDetail + "）" : ""));
            } catch (Exception ex) {}
        }
    }

    saveAll();

    if (anyFail && !anyOk) {
        sendGroupMsg(group, "处罚执行失败，" + failStr);
    } else if (anyFail) {
        sendGroupMsg(group, "处罚部分失败，" + failStr);
    } else {
        sendGroupMsg(group, "处罚已执行。（" + targetCfgs.size() + " 配置）");
    }
}

PunishRecord createPunishRecord(ConfigState cfg, String sender, String fromGroup, long target, String method, String content, String reason, String status) {
    PunishRecord r = new PunishRecord();
    r.id = cfg.nextRid++;
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
    cfg.records.add(r);
    cfg.recordsById.put(r.id, r);
    return r;
}

void addToBlacklist(ConfigState cfg, long qq, String reason, String groupName) {
    synchronized (cfg.blacklist) {
        for (BlacklistItem b : cfg.blacklist) {
            if (b.qq == qq && b.groupName.equals(groupName)) return;
        }
    }
    BlacklistItem item = new BlacklistItem();
    item.qq = qq;
    item.reason = reason;
    item.addTime = System.currentTimeMillis() / 1000;
    item.groupName = groupName;
    cfg.blacklist.add(item);
}

void removeFromBlacklist(ConfigState cfg, long qq, String groupName) {
    synchronized (cfg.blacklist) {
        for (Iterator<BlacklistItem> it = cfg.blacklist.iterator(); it.hasNext(); ) {
            BlacklistItem b = it.next();
            if (b.qq == qq && b.groupName.equals(groupName)) {
                it.remove();
            }
        }
    }
}

// ==================== /rp 撤销 ====================

void cmdRevoke(int level, String sender, String group, String[] parts) {
    if (parts.length < 2) {
        sendGroupMsg(group, "格式：/rp [配置] <记录ID> [撤销原因]");
        return;
    }

    List<ConfigState> matchCfgs = findConfigsByGroup(group);
    if (matchCfgs.isEmpty()) return;

    // 解析配置名
    String cfgName = null;
    int idIdx = 1;
    ConfigState namedCfg = getConfig(parts[1]);
    if (namedCfg != null) {
        cfgName = parts[1];
        idIdx = 2;
    } else if (matchCfgs.size() >= 2) {
        sendGroupMsg(group, "本群属于多个配置，请指定配置名称：/rp <配置名称> <记录ID> [撤销原因]");
        return;
    }

    if (idIdx >= parts.length) {
        sendGroupMsg(group, "缺少记录ID");
        return;
    }

    int rid;
    try {
        rid = Integer.parseInt(parts[idIdx]);
    } catch (Exception e) {
        sendGroupMsg(group, "记录ID必须为数字");
        return;
    }

    String rr = "";
    if (parts.length > idIdx + 1) {
        StringBuilder sb = new StringBuilder();
        for (int i = idIdx + 1; i < parts.length; i++) {
            if (i > idIdx + 1) sb.append(" ");
            sb.append(parts[i]);
        }
        rr = sb.toString();
    }

    // 查找记录
    PunishRecord target = null;
    ConfigState ownerCfg = null;

    if (cfgName != null) {
        ConfigState tCfg = getConfig(cfgName);
        if (tCfg == null) {
            sendGroupMsg(group, "配置 \"" + cfgName + "\" 不存在");
            return;
        }
        target = tCfg.recordsById.get(rid);
        if (target == null) {
            sendGroupMsg(group, "配置 \"" + cfgName + "\" 中不存在记录 " + rid);
            return;
        }
        ownerCfg = tCfg;
    } else {
        for (ConfigState cs : matchCfgs) {
            target = cs.recordsById.get(rid);
            if (target != null) { ownerCfg = cs; break; }
        }
        if (target == null) {
            sendGroupMsg(group, "记录不存在");
            return;
        }
    }

    if (ownerCfg == null) {
        sendGroupMsg(group, "记录对应配置异常");
        return;
    }

    if (!target.status.equals("已执行") && !target.status.equals("执行失败") && !target.status.equals("部分失败")) {
        sendGroupMsg(group, "该记录状态为 " + target.status + "，不可撤销");
        return;
    }

    // 执行撤销
    boolean anyOk = false;
    List<String> skipGroups = new ArrayList<>();
    List<String> failGroups = new ArrayList<>();

    if (target.method.equals("mute")) {
        List<String> execGroups;
        synchronized (ownerCfg.info.executionGroups) {
            execGroups = new ArrayList<>(ownerCfg.info.executionGroups);
        }
        for (String gid : execGroups) {
            try {
                // 检查成员在群
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
                    skipGroups.add(gid + "(成员不存在)");
                    continue;
                }

                // 检查是否处于禁言状态
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
                    skipGroups.add(gid + "(未处于禁言状态)");
                    continue;
                }

                shutUp(gid, String.valueOf(target.target), 0);
                anyOk = true;
            } catch (Exception e) {
                failGroups.add(gid);
                notifyNotifyGroup(ownerCfg, "[异常] 撤销（" + target.id + "）在群（" + gid + "）执行失败：" + e.getMessage());
            }
        }
        if (!anyOk && !failGroups.isEmpty()) {
            sendGroupMsg(group, "撤销操作执行失败，失败群：" + String.join(",", failGroups));
            return;
        }
    } else if (target.method.equals("kick") && "f".equals(target.content)) {
        removeFromBlacklist(ownerCfg, target.target, ownerCfg.name);
        anyOk = true;
    }

    target.status = "已撤销";
    target.revokeTime = System.currentTimeMillis() / 1000;
    target.revokeReason = rr;
    saveAll();

    String msg = "记录 " + rid + " 已撤销";
    if (!skipGroups.isEmpty()) {
        msg += "（以下群跳过：" + String.join(", ", skipGroups) + "）";
    }
    sendGroupMsg(group, msg);

    notifyNotifyGroup(ownerCfg,
        "[撤销] 处罚（" + target.id + "）已被（" + sender + "）撤销，"
        + "原处罚：（" + target.target + "）的（" + target.describe() + "），"
        + "原因：（" + target.reason + "）。撤销原因：" + (rr.isEmpty() ? "无" : rr));
}

// ==================== /h 查询 ====================

void cmdQuery(int level, String sender, String group, String[] parts, Object msgData) {
    List<ConfigState> matchCfgs = findConfigsByGroup(group);
    if (matchCfgs.isEmpty()) return;

    // 解析配置名
    String cfgName = null;
    int restStart = 1;
    if (parts.length > 1) {
        ConfigState namedCfg = getConfig(parts[1]);
        if (namedCfg != null) {
            cfgName = parts[1];
            restStart = 2;
        } else if (matchCfgs.size() >= 2) {
            sendGroupMsg(group, "本群属于多个配置，请指定配置名称：/h <配置名称> [QQ用户] [-i]");
            return;
        }
    }

    // 确定目标配置
    List<ConfigState> targetCfgs;
    if (cfgName != null) {
        targetCfgs = new ArrayList<>();
        for (ConfigState c : matchCfgs) {
            if (c.name.equals(cfgName)) targetCfgs.add(c);
        }
        if (targetCfgs.isEmpty()) {
            sendGroupMsg(group, "配置 \"" + cfgName + "\" 不存在或不包含本群");
            return;
        }
    } else {
        targetCfgs = matchCfgs;
    }

    // 收集所有记录
    List<PunishRecord> allRecords = new ArrayList<>();
    for (ConfigState cs : targetCfgs) {
        synchronized (cs.records) {
            allRecords.addAll(cs.records);
        }
    }

    // 无参数 → 全表
    if (parts.length < restStart + 1) {
        sendPunishRecordTableImage(group, allRecords);
        return;
    }

    // 解析目标
    String targetQQ = resolveTargetQQ(msgData, parts[restStart]);
    if (targetQQ == null || targetQQ.isEmpty()) {
        if (parts[restStart].equals("-i")) {
            sendPunishRecordTableImage(group, allRecords);
            return;
        }
        sendGroupMsg(group, "未找到目标QQ，请at或输入QQ号");
        return;
    }

    long target = Long.parseLong(targetQQ);
    boolean detail = parts.length > restStart + 1 && parts[restStart + 1].equals("-i");

    // 过滤
    List<PunishRecord> filtered = new ArrayList<>();
    for (PunishRecord r : allRecords) {
        if (r.target == target) filtered.add(r);
    }

    if (detail) {
        sendPunishRecordTableImage(group, filtered);
    } else {
        // 汇总统计
        int totalPunish = 0, muteCount = 0, kickCount = 0;
        long muteTotalSec = 0;
        for (PunishRecord r : filtered) {
            if (r.status.equals("已执行") || r.status.equals("执行失败") || r.status.equals("部分失败")) {
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
        sendGroupMsg(group, buildPunishRecordTable(list));
    }
}

void generatePunishRecordTableImage(List<PunishRecord> list, String outputPath) throws IOException {
    SimpleDateFormat fmt = new SimpleDateFormat("MM-dd HH:mm");

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

        if (i % 2 == 0) {
            paint.setColor(Color.parseColor("#F5F7FF"));
        } else {
            paint.setColor(Color.WHITE);
        }
        canvas.drawRect(12, rowY, imgWidth - 12, rowY + rowHeight, paint);

        paint.setColor(Color.parseColor("#E0E0E0"));
        canvas.drawLine(12, rowY + rowHeight, imgWidth - 12, rowY + rowHeight, paint);

        String st = r.status != null ? r.status : "";
        int statusColor = Color.BLACK;
        if (st.equals("已执行")) statusColor = Color.parseColor("#2E7D32");
        else if (st.equals("已撤销")) statusColor = Color.parseColor("#F57F17");
        else if (st.equals("执行失败")) statusColor = Color.parseColor("#C62828");
        else if (st.equals("部分失败")) statusColor = Color.parseColor("#B71C1C");
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

// ==================== /a 权限 ====================

void cmdPermission(int level, String sender, String group, String[] parts, Object msgData) {
    if (level != 0) {
        sendGroupMsg(group, "权限不足，仅超级管理员可用");
        return;
    }

    List<ConfigState> matchCfgs = findConfigsByGroup(group);
    if (matchCfgs.isEmpty()) return;

    // 解析配置名
    String cfgName = null;
    int targetIdx = 1;
    if (parts.length > 1) {
        ConfigState namedCfg = getConfig(parts[1]);
        if (namedCfg != null) {
            cfgName = parts[1];
            targetIdx = 2;
        } else if (matchCfgs.size() >= 2) {
            sendGroupMsg(group, "本群属于多个配置，请指定配置名称：/a <配置名称> <QQ用户> [等级]");
            return;
        }
    }

    if (targetIdx >= parts.length) {
        sendGroupMsg(group, "格式：/a [配置] <成员> [等级]");
        return;
    }

    String targetQQ = resolveTargetQQ(msgData, parts[targetIdx]);
    if (targetQQ == null || targetQQ.isEmpty()) {
        sendGroupMsg(group, "未找到目标QQ，请at或输入QQ号");
        return;
    }
    if (targetQQ.equals(sender)) {
        sendGroupMsg(group, "不能修改自己的权限");
        return;
    }

    int newLevel = 1;
    if (parts.length >= targetIdx + 2) {
        try {
            newLevel = Integer.parseInt(parts[targetIdx + 2]);
        } catch (Exception e) {
            sendGroupMsg(group, "权限必须为数字（-1=普通成员，≥1 数字越大权限越低，0 不可设）");
            return;
        }
    }
    if (newLevel < -1 || newLevel == 0) {
        sendGroupMsg(group, "权限值无效（-1=普通成员，≥1 数字越大权限越低，0 不可设）");
        return;
    }

    // 确定目标配置
    List<ConfigState> targetCfgs;
    if (cfgName != null) {
        targetCfgs = new ArrayList<>();
        for (ConfigState c : matchCfgs) {
            if (c.name.equals(cfgName)) targetCfgs.add(c);
        }
        if (targetCfgs.isEmpty()) {
            sendGroupMsg(group, "配置 \"" + cfgName + "\" 不存在或不包含本群");
            return;
        }
    } else {
        targetCfgs = matchCfgs;
    }

    List<String> cfgNames = new ArrayList<>();
    for (ConfigState cs : targetCfgs) {
        cs.permissions.put(targetQQ, newLevel);
        cfgNames.add(cs.name);
    }

    saveAll();
    String role = newLevel == -1 ? "普通成员" : "权限等级 " + newLevel;
    sendGroupMsg(group, "已设置 " + targetQQ + " 为" + role + " (配置: " + String.join(", ", cfgNames) + ")");
}

// ==================== /config 配置管理 ====================

void cmdConfig(int level, String sender, String group, String[] parts) {
    if (level != 0) return;  // 仅超管可用

    List<ConfigState> allCfgs = new ArrayList<>(configs.values());

    if (parts.length < 2) {
        sendGroupMsg(group,
            "子命令：\n"
            + "  config new <名称>              — 创建新配置\n"
            + "  config rename <旧名> <新名>     — 重命名配置\n"
            + "  config <名称> notify           — 设本群为通知群\n"
            + "  config <名称> set              — 本群加入执行群\n"
            + "  config <名称> remove           — 本群移出配置\n"
            + "  config <名称> group            — 查看配置信息");
        return;
    }

    String first = parts[1].toLowerCase();

    // config new <名称>
    if (first.equals("new")) {
        if (parts.length < 3) {
            sendGroupMsg(group, "格式：config new <名称>");
            return;
        }
        String name = parts[2];
        if (name.trim().isEmpty()) {
            sendGroupMsg(group, "配置名不能为空");
            return;
        }
        if (configs.containsKey(name)) {
            sendGroupMsg(group, "配置 \"" + name + "\" 已存在");
            return;
        }
        ConfigState cs = new ConfigState();
        cs.name = name;
        configs.put(name, cs);
        saveConfig(name);
        buildCmdNameMap();
        sendGroupMsg(group, "配置 \"" + name + "\" 创建成功");
        return;
    }

    // config rename <旧名> <新名>
    if (first.equals("rename")) {
        if (parts.length < 4) {
            sendGroupMsg(group, "格式：config rename <旧名> <新名>");
            return;
        }
        String oldName = parts[2];
        String newName = parts[3];
        if (!configs.containsKey(oldName)) {
            sendGroupMsg(group, "配置 \"" + oldName + "\" 不存在");
            return;
        }
        if (configs.containsKey(newName)) {
            sendGroupMsg(group, "配置 \"" + newName + "\" 已存在");
            return;
        }
        ConfigState cs = configs.remove(oldName);
        cs.name = newName;
        configs.put(newName, cs);
        saveConfig(newName);
        removeConfig(oldName);
        buildCmdNameMap();
        sendGroupMsg(group, "配置 \"" + oldName + "\" 已重命名为 \"" + newName + "\"");
        return;
    }

    // config <名称> <子命令>
    String name = first;
    if (!configs.containsKey(name)) {
        sendGroupMsg(group, "配置 \"" + name + "\" 不存在，可用：config new <名称> 创建");
        return;
    }

    if (parts.length < 3) {
        sendGroupMsg(group, "格式：config " + name + " notify / set / remove / group");
        return;
    }

    String sub = parts[2].toLowerCase();
    ConfigState cs = configs.get(name);

    if (sub.equals("notify")) {
        cs.info.notifyGroup = group;
        saveConfig(name);
        sendGroupMsg(group, "已将本群设为配置 \"" + name + "\" 的通知群");
    } else if (sub.equals("set")) {
        cs.info.executionGroups.add(group);
        saveConfig(name);
        sendGroupMsg(group, "已将本群加入配置 \"" + name + "\" 的执行群");
    } else if (sub.equals("remove")) {
        boolean removed = false;
        if (group.equals(cs.info.notifyGroup)) {
            cs.info.notifyGroup = null;
            removed = true;
        }
        if (cs.info.executionGroups.contains(group)) {
            cs.info.executionGroups.remove(group);
            removed = true;
        }
        if (!removed) {
            sendGroupMsg(group, "本群不属于配置 \"" + name + "\"");
            return;
        }
        saveConfig(name);
        sendGroupMsg(group, "已将本群从配置 \"" + name + "\" 移出");
    } else if (sub.equals("group")) {
        String ng = cs.info.notifyGroup != null ? cs.info.notifyGroup : "未设置";
        String el;
        synchronized (cs.info.executionGroups) {
            List<String> sorted = new ArrayList<>(cs.info.executionGroups);
            Collections.sort(sorted);
            el = sorted.isEmpty() ? "无" : String.join(", ", sorted);
        }
        sendGroupMsg(group,
            "配置名：" + name + "\n"
            + "通知群：" + ng + "\n"
            + "执行群：" + el + "\n"
            + "记录数：" + cs.records.size());
    } else {
        sendGroupMsg(group, "未知子命令：" + sub);
    }
}

// ==================== 群事件：黑名单自动踢人 ====================

void joinGroup(String group, String qq) {
    if (!initialized) {
        synchronized (initLock) { if (!initialized) init(); }
    }
    List<ConfigState> cfgs = findConfigsByGroup(group);
    if (cfgs.isEmpty()) return;

    long qqLong = Long.parseLong(qq);
    for (ConfigState cs : cfgs) {
        BlacklistItem matched = null;
        synchronized (cs.blacklist) {
            for (BlacklistItem b : cs.blacklist) {
                if (b.qq == qqLong && b.groupName.equals(cs.name)) {
                    matched = b;
                    break;
                }
            }
        }
        if (matched != null) {
            try {
                // 检查成员是否在群
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
                // 验证
                List memberListAfterKick = getGroupMemberList(group);
                if (memberListAfterKick != null) {
                    for (Object m : memberListAfterKick) {
                        if (m.uin != null && m.uin.equals(qq)) {
                            log("error.log", "黑名单踢人失败：bot权限不足，成员 " + qq + " 仍在群内");
                            return;
                        }
                    }
                }
                sendGroupMsg(group, "用户 " + qq + " 在配置 " + cs.name + " 黑名单中，已自动移出。原因：" + matched.reason);
                return;  // 踢一次即可
            } catch (Exception e) {
                log("error.log", "黑名单踢人失败：" + e.getMessage());
            }
        }
    }
}

// ==================== 启动时配置与数据检查 ====================

try { checkAndRepairConfig(); } catch (Exception e) {
    log("error.log", "配置检查修复失败: " + e.getMessage());
    wakeWords = new ArrayList<String>(Arrays.asList("/", "!", "。"));
    superAdmins = new HashSet<String>();
    dataDirPath = pluginPath + "/data";
}

try { new File(dataDirPath).mkdirs(); } catch (Exception e) {}

try { checkAndRepairDataFiles(); } catch (Exception e) {
    log("error.log", "数据文件检查修复失败: " + e.getMessage());
}

// ==================== 生命周期 ====================

void unLoadPlugin() {
    saveAll();
}

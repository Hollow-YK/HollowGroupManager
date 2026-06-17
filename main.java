import java.io.*;
import java.util.*;
import java.text.SimpleDateFormat;
import java.util.regex.*;
import java.util.concurrent.atomic.AtomicInteger;

// ==================== 全局数据与配置 ====================
List<String> wakeWords;
Set<String> superAdmins;
String dataDirPath;

Map<String, ManagementGroup> groups = new LinkedHashMap<>();
List<Record> records = Collections.synchronizedList(new ArrayList<>());
Map<String, Integer> permissions = new HashMap<>();          // qq -> level (1 或 -1)
List<BlacklistItem> blacklist = Collections.synchronizedList(new ArrayList<>());
AtomicInteger nextRecordId = new AtomicInteger(1);

boolean initialized = false;
final Object initLock = new Object();

SimpleDateFormat sdf = new SimpleDateFormat("yyyy-MM-dd HH:mm:ss");

// ==================== 数据模型 ====================
class ManagementGroup {
    String name;
    String adminGroup;
    Set<String> executionGroups = new LinkedHashSet<>();

    Map<String, Object> toMap() {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("name", name);
        map.put("adminGroup", adminGroup);
        map.put("executionGroups", new ArrayList<>(executionGroups));
        return map;
    }

    static ManagementGroup fromMap(Map<String, Object> map) {
        ManagementGroup g = new ManagementGroup();
        g.name = (String) map.get("name");
        g.adminGroup = (String) map.get("adminGroup");
        List<String> execs = (List<String>) map.get("executionGroups");
        if (execs != null) g.executionGroups = new LinkedHashSet<>(execs);
        return g;
    }
}

class Record {
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

    static Record fromMap(Map<String, Object> map) {
        Record r = new Record();
        r.id = ((Number) map.get("id")).intValue();
        r.sender = ((Number) map.get("sender")).longValue();
        r.time = ((Number) map.get("time")).longValue();
        r.fromGroup = (String) map.get("fromGroup");
        r.target = ((Number) map.get("target")).longValue();
        r.method = (String) map.get("method");
        r.content = (String) map.get("content");
        r.reason = (String) map.get("reason");
        r.status = (String) map.get("status");
        r.failDetail = (String) map.get("failDetail");
        r.revokeTime = ((Number) map.get("revokeTime")).longValue();
        r.revokeReason = (String) map.get("revokeReason");
        return r;
    }

    String describe() {
        switch (method) {
            case "kick": return "kick" + (content.equals("f") ? " f" : "");
            case "mute": return "mute " + content;
            case "warning": return "warning";
            default: return method;
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
        b.qq = ((Number) map.get("qq")).longValue();
        b.reason = (String) map.get("reason");
        b.addTime = ((Number) map.get("addTime")).longValue();
        b.groupName = (String) map.get("groupName");
        return b;
    }
}

// ==================== 初始化与数据持久化 ====================
void init() {
    // 读取配置
    Properties props = new Properties();
    try (FileReader reader = new FileReader(pluginPath + "/config.properties")) {
        props.load(reader);
    } catch (Exception e) {
        log("error.log", "配置文件读取失败: " + e.getMessage());
        wakeWords = new ArrayList<>(Arrays.asList("/", "!", "。"));
        superAdmins = new HashSet<>(Arrays.asList("你的QQ号")); // 替换为实际
        dataDirPath = pluginPath + "/data";
        return;
    }
    String words = props.getProperty("wakeWords", "/,!,。");
    wakeWords = new ArrayList<>(Arrays.asList(words.split(",")));
    String admins = props.getProperty("superAdmins", "");
    superAdmins = new HashSet<>(Arrays.asList(admins.split(",")));
    dataDirPath = pluginPath + "/" + props.getProperty("dataDir", "data");

    // 确保数据目录存在
    new File(dataDirPath).mkdirs();

    // 加载数据
    groups = loadMap(dataDirPath + "/groups.json", ManagementGroup::fromMap);
    records = Collections.synchronizedList(loadList(dataDirPath + "/records.json", Record::fromMap));
    permissions = loadSimpleMap(dataDirPath + "/permissions.json");
    blacklist = Collections.synchronizedList(loadList(dataDirPath + "/blacklist.json", BlacklistItem::fromMap));

    // 计算下一个记录ID
    int maxId = 0;
    for (Record r : records) {
        if (r.id > maxId) maxId = r.id;
    }
    nextRecordId.set(maxId + 1);
}

// 序列化工具
void saveAll() {
    saveList(dataDirPath + "/records.json", records, Record::toMap);
    saveMap(dataDirPath + "/groups.json", groups, ManagementGroup::toMap);
    saveSimpleMap(dataDirPath + "/permissions.json", permissions);
    saveList(dataDirPath + "/blacklist.json", blacklist, BlacklistItem::toMap);
}

// ==================== 简易JSON读写（仅支持基本类型、Map、List） ====================
String escapeJson(String s) {
    return s.replace("\\", "\\\\").replace("\"", "\\\"");
}

String unescapeJson(String s) {
    return s.replace("\\\"", "\"").replace("\\\\", "\\");
}

String toJson(Object obj) {
    if (obj == null) return "null";
    if (obj instanceof String) return "\"" + escapeJson((String) obj) + "\"";
    if (obj instanceof Number) return obj.toString();
    if (obj instanceof Boolean) return obj.toString();
    if (obj instanceof Map) {
        Map<?, ?> map = (Map<?, ?>) obj;
        StringBuilder sb = new StringBuilder("{");
        boolean first = true;
        for (Map.Entry<?, ?> entry : map.entrySet()) {
            if (!first) sb.append(",");
            sb.append(toJson(entry.getKey().toString())).append(":").append(toJson(entry.getValue()));
            first = false;
        }
        sb.append("}");
        return sb.toString();
    }
    if (obj instanceof List) {
        List<?> list = (List<?>) obj;
        StringBuilder sb = new StringBuilder("[");
        boolean first = true;
        for (Object item : list) {
            if (!first) sb.append(",");
            sb.append(toJson(item));
            first = false;
        }
        sb.append("]");
        return sb.toString();
    }
    return "\"" + escapeJson(obj.toString()) + "\"";
}

// 简单解析器（递归下降）
Object parseJson(String json) {
    json = json.trim();
    if (json.isEmpty()) return null;
    char first = json.charAt(0);
    if (first == '{') {
        Map<String, Object> map = new LinkedHashMap<>();
        json = json.substring(1, json.length() - 1).trim();
        while (!json.isEmpty()) {
            int colon = findSplit(json, ':');
            String key = (String) parseJson(json.substring(0, colon).trim());
            json = json.substring(colon + 1).trim();
            int comma = findSplit(json, ',');
            String valStr = json.substring(0, comma).trim();
            map.put(key, parseJson(valStr));
            json = json.substring(comma).trim();
            if (json.startsWith(",")) json = json.substring(1).trim();
        }
        return map;
    } else if (first == '[') {
        List<Object> list = new ArrayList<>();
        json = json.substring(1, json.length() - 1).trim();
        while (!json.isEmpty()) {
            int comma = findSplit(json, ',');
            String valStr = json.substring(0, comma).trim();
            if (!valStr.isEmpty()) list.add(parseJson(valStr));
            json = json.substring(comma).trim();
            if (json.startsWith(",")) json = json.substring(1).trim();
        }
        return list;
    } else if (first == '"') {
        int end = json.indexOf('"', 1);
        while (end != -1 && json.charAt(end - 1) == '\\') end = json.indexOf('"', end + 1);
        if (end == -1) end = json.length() - 1;
        return unescapeJson(json.substring(1, end));
    } else {
        try {
            if (json.equals("true")) return true;
            if (json.equals("false")) return false;
            if (json.equals("null")) return null;
            if (json.contains(".")) return Double.parseDouble(json);
            return Long.parseLong(json);
        } catch (Exception e) {
            return json;
        }
    }
}

int findSplit(String json, char delimiter) {
    int depth = 0;
    boolean inString = false;
    for (int i = 0; i < json.length(); i++) {
        char c = json.charAt(i);
        if (inString) {
            if (c == '"' && json.charAt(i - 1) != '\\') inString = false;
            continue;
        }
        if (c == '"') { inString = true; continue; }
        if (c == '{' || c == '[') depth++;
        else if (c == '}' || c == ']') depth--;
        else if (c == delimiter && depth == 0) return i;
    }
    return json.length();
}

// 加载/保存集合
<T> List<T> loadList(String path, Function<Map<String, Object>, T> mapper) {
    File file = new File(path);
    if (!file.exists()) return new ArrayList<>();
    try (BufferedReader reader = new BufferedReader(new FileReader(file))) {
        String content = readAll(reader);
        Object parsed = parseJson(content);
        if (parsed instanceof List) {
            List<T> list = new ArrayList<>();
            for (Object obj : (List) parsed) {
                if (obj instanceof Map) list.add(mapper.apply((Map) obj));
            }
            return list;
        }
    } catch (Exception e) {
        log("error.log", "加载数据失败 " + path + ": " + e.getMessage());
    }
    return new ArrayList<>();
}

<T> void saveList(String path, List<T> list, Function<T, Map<String, Object>> mapper) {
    List<Object> jsonList = new ArrayList<>();
    for (T item : list) jsonList.add(mapper.apply(item));
    try (PrintWriter out = new PrintWriter(new FileWriter(path))) {
        out.print(toJson(jsonList));
    } catch (Exception e) {
        log("error.log", "保存数据失败 " + path + ": " + e.getMessage());
    }
}

Map<String, ManagementGroup> loadMap(String path, Function<Map<String, Object>, ManagementGroup> mapper) {
    File file = new File(path);
    if (!file.exists()) return new LinkedHashMap<>();
    try (BufferedReader reader = new BufferedReader(new FileReader(file))) {
        Object parsed = parseJson(readAll(reader));
        if (parsed instanceof List) {
            Map<String, ManagementGroup> map = new LinkedHashMap<>();
            for (Object obj : (List) parsed) {
                if (obj instanceof Map) {
                    ManagementGroup g = mapper.apply((Map) obj);
                    map.put(g.name, g);
                }
            }
            return map;
        }
    } catch (Exception e) {
        log("error.log", "加载管理组失败: " + e.getMessage());
    }
    return new LinkedHashMap<>();
}

void saveMap(String path, Map<String, ManagementGroup> map, Function<ManagementGroup, Map<String, Object>> mapper) {
    List<Object> list = new ArrayList<>();
    for (ManagementGroup g : map.values()) list.add(mapper.apply(g));
    try (PrintWriter out = new PrintWriter(new FileWriter(path))) {
        out.print(toJson(list));
    } catch (Exception e) {
        log("error.log", "保存管理组失败: " + e.getMessage());
    }
}

Map<String, Integer> loadSimpleMap(String path) {
    File file = new File(path);
    if (!file.exists()) return new HashMap<>();
    try (BufferedReader reader = new BufferedReader(new FileReader(file))) {
        Object parsed = parseJson(readAll(reader));
        if (parsed instanceof Map) {
            Map<String, Integer> map = new HashMap<>();
            for (Map.Entry<?, ?> e : ((Map<?, ?>) parsed).entrySet()) {
                map.put(e.getKey().toString(), ((Number) e.getValue()).intValue());
            }
            return map;
        }
    } catch (Exception e) {
        log("error.log", "加载权限失败: " + e.getMessage());
    }
    return new HashMap<>();
}

void saveSimpleMap(String path, Map<String, Integer> map) {
    try (PrintWriter out = new PrintWriter(new FileWriter(path))) {
        out.print(toJson(map));
    } catch (Exception e) {
        log("error.log", "保存权限失败: " + e.getMessage());
    }
}

String readAll(BufferedReader reader) throws IOException {
    StringBuilder sb = new StringBuilder();
    String line;
    while ((line = reader.readLine()) != null) sb.append(line);
    return sb.toString();
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
    for (ManagementGroup g : groups.values()) {
        if (g.adminGroup.equals(groupId) || g.executionGroups.contains(groupId)) return g;
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
            cmdQuery(level, peerUin, parts);
            break;
        case "a":
            cmdPermission(level, userUin, peerUin, parts);
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
    String targetStr = parts[1];
    String targetQQ = null;
    // 优先使用艾特列表
    List<String> atList = msgData.atList;
    if (atList != null && !atList.isEmpty()) {
        targetQQ = atList.get(0);
    }
    if (targetQQ == null) {
        targetQQ = extractQQ(targetStr);
    }
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
        Record r = createRecord(sender, group, Long.parseLong(targetQQ), method, content, "", "不合规");
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
    Record r = createRecord(sender, group, Long.parseLong(targetQQ), method, content, reason, "执行中");

    // 遍历执行群
    List<String> execGroups = new ArrayList<>(mg.executionGroups);
    boolean allSuccess = true;
    boolean anyFail = false;
    List<String> failGroups = new ArrayList<>();
    for (String gid : execGroups) {
        // 检查成员是否在群
        Object member = getMemberInfo(gid, targetQQ);
        if (member == null) continue; // 跳过
        try {
            switch (method) {
                case "kick":
                    boolean toBlack = "f".equals(content);
                    kickGroup(gid, targetQQ, false);
                    if (toBlack) {
                        addToBlacklist(Long.parseLong(targetQQ), reason, mg.name);
                    }
                    break;
                case "mute":
                    long sec = parseDurationSeconds(content);
                    shutUp(gid, targetQQ, sec);
                    break;
                case "warning":
                    // 无实际操作
                    break;
            }
        } catch (Exception e) {
            allSuccess = false;
            anyFail = true;
            failGroups.add(gid);
            notifyAdminGroup(mg, "[异常] 处罚（" + r.id + "）在群（" + gid + "）执行失败：权限不足。");
        }
    }

    // 更新状态
    if (anyFail) {
        r.status = "执行失败";
        r.failDetail = "失败群：" + String.join(",", failGroups);
    } else {
        r.status = "已执行";
    }
    updateRecord(r);

    // 发送总结
    StringBuilder feedback = new StringBuilder();
    if (allSuccess) {
        feedback.append("处罚已对所有执行群生效。");
    } else {
        feedback.append("处罚部分执行：成功群 " + (execGroups.size() - failGroups.size()) + " 个，失败群：" + String.join(",", failGroups));
    }
    sendGroupMsg(group, feedback.toString());

    // 通知管理群
    notifyAdminGroup(mg, "处罚（" + r.id + "）：（" + sender + "）在（" + group + "）内发起了对（" + targetQQ + "）的（" + r.describe() + "）处罚，原因：（" + reason + "）");

    saveAll();
}

Record createRecord(String sender, String fromGroup, long target, String method, String content, String reason, String status) {
    Record r = new Record();
    r.id = nextRecordId.getAndIncrement();
    r.sender = Long.parseLong(sender);
    r.time = System.currentTimeMillis() / 1000;
    r.fromGroup = fromGroup;
    r.target = target;
    r.method = method;
    r.content = content;
    r.reason = reason;
    r.status = status;
    records.add(r);
    return r;
}

void updateRecord(Record r) {
    // 已经在列表中，无需操作，保存时会同步
}

void addToBlacklist(long qq, String reason, String groupName) {
    // 检查是否存在
    for (BlacklistItem b : blacklist) {
        if (b.qq == qq && b.groupName.equals(groupName)) return;
    }
    BlacklistItem item = new BlacklistItem();
    item.qq = qq;
    item.reason = reason;
    item.addTime = System.currentTimeMillis() / 1000;
    item.groupName = groupName;
    blacklist.add(item);
}

void removeFromBlacklist(long qq, String groupName) {
    blacklist.removeIf(b -> b.qq == qq && b.groupName.equals(groupName));
}

void cmdQuery(int level, String group, String[] parts) {
    if (parts.length < 2) {
        sendGroupMsg(group, "格式：/h <成员QQ> [-i]");
        return;
    }
    String targetStr = parts[1];
    String targetQQ = extractQQ(targetStr);
    if (targetQQ == null) {
        sendGroupMsg(group, "请提供有效的QQ号");
        return;
    }
    long target = Long.parseLong(targetQQ);
    boolean detail = parts.length > 2 && parts[2].equals("-i");

    ManagementGroup mg = findGroupByGroupId(group);
    if (mg == null) {
        sendGroupMsg(group, "当前群不属于管理组");
        return;
    }

    List<Record> filtered = new ArrayList<>();
    for (Record r : records) {
        if (r.target == target && (r.fromGroup.equals(group) || mg.executionGroups.contains(r.fromGroup) || mg.adminGroup.equals(r.fromGroup))) {
            // 组内共享记录
            filtered.add(r);
        }
    }

    if (detail) {
        // 生成表格
        String table = buildRecordTable(filtered);
        sendGroupMsg(group, table);
    } else {
        // 汇总统计（仅已执行和执行失败）
        int totalPunish = 0, muteCount = 0, kickCount = 0;
        long muteTotalSec = 0;
        for (Record r : filtered) {
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

String buildRecordTable(List<Record> list) {
    if (list.isEmpty()) return "无记录";
    StringBuilder sb = new StringBuilder("记录列表：\n");
    sb.append("ID | 时间 | 发起群 | 发起者 | 方式 | 内容 | 原因 | 状态 | 撤销时间 | 撤销原因\n");
    SimpleDateFormat fmt = new SimpleDateFormat("MM-dd HH:mm");
    for (Record r : list) {
        sb.append(r.id).append(" | ");
        sb.append(fmt.format(new Date(r.time * 1000))).append(" | ");
        sb.append(r.fromGroup).append(" | ");
        sb.append(r.sender).append(" | ");
        sb.append(r.method).append(" | ");
        sb.append(r.content.isEmpty() ? "-" : r.content).append(" | ");
        sb.append(r.reason).append(" | ");
        sb.append(r.status).append(" | ");
        sb.append(r.revokeTime == 0 ? "-" : fmt.format(new Date(r.revokeTime * 1000))).append(" | ");
        sb.append(r.revokeReason.isEmpty() ? "-" : r.revokeReason);
        sb.append("\n");
    }
    return sb.toString();
}

void cmdPermission(int level, String sender, String group, String[] parts) {
    if (level != 0) {
        sendGroupMsg(group, "权限不足，仅超级管理员可用");
        return;
    }
    if (parts.length < 2) {
        sendGroupMsg(group, "格式：/a <成员QQ> [1/-1]");
        return;
    }
    String targetQQ = extractQQ(parts[1]);
    if (targetQQ == null) {
        sendGroupMsg(group, "未识别到QQ号");
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
            String execList = info.executionGroups.isEmpty() ? "无" : String.join(",", info.executionGroups);
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
    Record target = null;
    for (Record r : records) {
        if (r.id == recordId) {
            target = r;
            break;
        }
    }
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

    // 执行撤销动作
    try {
        if (target.method.equals("mute")) {
            for (String gid : mg.executionGroups) {
                shutUp(gid, String.valueOf(target.target), 0); // 解禁
            }
        } else if (target.method.equals("kick") && "f".equals(target.content)) {
            removeFromBlacklist(target.target, mg.name);
        }
        // warning 和 kick 非 f 无操作
    } catch (Exception e) {
        sendGroupMsg(group, "撤销操作执行失败：" + e.getMessage());
        return;
    }

    target.status = "已撤销";
    target.revokeTime = System.currentTimeMillis() / 1000;
    target.revokeReason = revokeReason;
    updateRecord(target);
    saveAll();

    sendGroupMsg(group, "记录 " + recordId + " 已撤销");
    notifyAdminGroup(mg, "[撤销] 处罚（" + target.id + "）已被（" + sender + "）撤销，原处罚：（" + target.target + "）的（" + target.describe() + "），原因：（" + target.reason + "）。撤销原因：" + (revokeReason.isEmpty() ? "无" : revokeReason));
}

// ==================== 群事件：黑名单自动踢人 ====================
void joinGroup(String group, String qq) {
    if (!initialized) {
        synchronized (initLock) { if (!initialized) init(); }
    }
    ManagementGroup mg = findGroupByGroupId(group);
    if (mg == null) return;
    for (BlacklistItem b : blacklist) {
        if (b.qq == Long.parseLong(qq) && b.groupName.equals(mg.name)) {
            try {
                kickGroup(group, qq, false);
                sendGroupMsg(group, "用户 " + qq + " 在管理组黑名单中，已自动移出。原因：" + b.reason);
            } catch (Exception e) {
                log("error.log", "黑名单踢人失败：" + e.getMessage());
            }
            break;
        }
    }
}

// ==================== 生命周期 ====================
void unLoadPlugin() {
    saveAll();
}
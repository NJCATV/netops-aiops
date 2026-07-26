<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import HomeDashboard from "./components/HomeDashboard.vue";

const apiBase = "/api";
const navGroups = [
  { title: "系统首页", items: [{ key: "home", label: "智能态势首页" }] },
  { title: "城域网智能运维", items: [{ key: "ai", label: "运维看板" }, { key: "events", label: "实时 Events" }, { key: "syslog", label: "实时 Syslog" }, { key: "trap", label: "SNMP Trap" }, { key: "history", label: "AI 分析历史" }, { key: "aiRules", label: "AI 分析规则" }, { key: "tasks", label: "定时分析任务" }] },
  { title: "运维知识助手", items: [{ key: "aiChat", label: "AI 问答" }, { key: "kbManage", label: "知识库管理" }] },
  { title: "系统管理", items: [{ key: "models", label: "模型管理" }, { key: "users", label: "用户管理" }, { key: "roles", label: "角色管理" }, { key: "settings", label: "系统设置" }, { key: "chatLogs", label: "AI问答日志" }, { key: "qqAuditLogs", label: "QQ问答审计" }, { key: "operationLogs", label: "操作日志" }, { key: "loginLogs", label: "登录日志" }] },
];
const analysisStages = [
  "正在收集 Syslog / Trap / alarm_events",
  "正在清洗与聚合事件",
  "正在识别同设备、同对象、同时间窗口关联",
  "正在判断噪声、恢复事件与证据不足项",
  "正在生成 AI 研判报告",
  "正在整理建议动作",
];
const windowOptions = [
  { label: "最近4小时", value: 4 },
  { label: "最近12小时", value: 12 },
  { label: "最近24小时", value: 24 },
  { label: "自定义窗口", value: "custom" },
];
const aiTabs = [
  { key: "must_handle", label: "必须处理", count: () => aiSections.value.must_handle.length },
  { key: "watch", label: "重点关注", count: () => aiSections.value.watch.length },
  { key: "correlation", label: "关联分析", count: () => correlations.value.length },
  { key: "recovered", label: "已恢复", count: () => aiSections.value.recovered.length },
  { key: "actions", label: "建议动作", count: () => nextActions.value.length },
  { key: "rules_noise", label: "规则与降噪", count: () => aiSections.value.noise.length + analysisDisplay.value.ruleStats.hitCount },
  { key: "insufficient", label: "证据不足", count: () => aiSections.value.insufficient.length },
];

const authChecked = ref(false);
const user = ref(null);
const authForm = ref({ username: "", password: "" });
const view = ref("home");
const loading = ref(false);
const error = ref("");
const lastLoadedAt = ref(null);
const refreshTimer = ref(null);
const elapsedTimer = ref(null);
const clockTimer = ref(null);
const currentTime = ref(new Date());

const overview = ref(null);
const freshness = ref(null);
const syslogs = ref([]);
const syslogTotal = ref(0);
const traps = ref([]);
const trapTotal = ref(0);
const events = ref([]);
const eventTotal = ref(0);
const selectedEvent = ref(null);
const selectedTrap = ref(null);
const selectedSyslog = ref(null);
const selectedKbRecord = ref(null);
const selectedChatLog = ref(null);
const selectedQqAuditLog = ref(null);
const runs = ref([]);
const selectedRun = ref(null);
const findings = ref([]);
const tasks = ref([]);
const selectedFinding = ref(null);
const drawerTab = ref("summary");
const selectedQuality = ref(null);
const activeAiTab = ref("must_handle");
const taskDrawerOpen = ref(false);
const taskLogDrawer = ref(null);
const editingTask = ref(null);
const users = ref([]);
const userDrawerOpen = ref(false);
const editingUser = ref(null);
const userForm = ref({ username: "", display_name: "", password: "", role: "viewer", is_active: true, remark: "" });
const aiRules = ref([]);
const ruleDrawerOpen = ref(false);
const editingRule = ref(null);
const ruleForm = ref({ rule_name: "", raw_text: "", enabled: true, priority: 50 });
const parsedRulePreview = ref(null);
const systemSettings = ref({});
const operationLogs = ref([]);
const loginLogs = ref([]);
const chatLogs = ref([]);
const qqAuditLogs = ref([]);
const qqAuditSummary = ref({});
const qqAuditFilters = ref({ q: "", event: "", group_id: "", user_id: "", limit: 100 });
const qqBotStatus = ref({ known: false, online: false, status: "unknown" });
const llmProviders = ref([]);
const llmModels = ref([]);
const llmUsageKeys = ref([]);
const llmBindings = ref([]);
const providerDrawerOpen = ref(false);
const modelDrawerOpen = ref(false);
const editingProvider = ref(null);
const editingModel = ref(null);
const activeUsageKey = ref("aiops_scheduled_analysis");
const providerForm = ref({ name: "", base_url: "", api_key: "", api_key_env: "", enabled: true, timeout_seconds: 60, remark: "" });
const modelForm = ref({ provider_id: "", model_id: "", display_name: "", endpoint_type: "chat", input_types_text: "text", output_types_text: "text", max_context_tokens: "", max_input_size: "", max_output_tokens: "", supports_streaming: false, supports_tools: false, enabled: true, remark: "" });
const bindingDraft = ref([]);
const kbSummary = ref(null);
const kbReports = ref([]);
const kbRepairs = ref([]);
const kbDocuments = ref([]);
const kbTopics = ref([]);
const kbActiveTab = ref("chat");
const kbReportFilters = ref({ q: "", service: "", canonical_symptom: "", source_type: "formal_fault_report", page: 1, pageSize: 10 });
const kbRepairFilters = ref({ q: "", service: "", canonical_symptom: "", knowledge_value: "", include_noise: false, page: 1, pageSize: 10 });
const kbDocumentFilters = ref({ q: "", service: "", canonical_symptom: "", source_type: "document_kb", page: 1, pageSize: 10 });
const kbTopicFilters = ref({ q: "", service: "", page: 1, pageSize: 10 });
const kbTotals = ref({ reports: 0, repairs: 0, documents: 0, topics: 0 });
const kbImportForms = ref({
  report: { kind: "formal", path: "/opt/jscn-aiops/文档/2026故障报告", rebuild: false, rebuild_aggregates: true, drop_noise: false },
  repair: { kind: "repair", path: "/opt/jscn-aiops/文档/20260705故障汇总.xlsx", rebuild: false, rebuild_aggregates: true, drop_noise: false },
  document: { kind: "formal", path: "/opt/jscn-aiops/文档/运维文档", rebuild: false, rebuild_aggregates: true, drop_noise: false },
});
const kbImportFiles = ref({
  report: [],
  repair: [],
  document: [],
});
const kbImportCards = [
  {
    key: "report",
    title: "故障报告知识库",
    tag: "正式报告",
    accept: ".zip,.doc,.docx,.xlsx",
    multiple: true,
    pathLabel: "报告目录路径",
    uploadHint: "上传按日期命名的故障排查报告 Word，或包含报告和故障台账的 zip/目录；适合作为 AI 问答的高可信引用。",
    placeholder: "支持 .docx、可转换 .doc、zip，配套故障台账可带 .xlsx",
  },
  {
    key: "repair",
    title: "报修知识库",
    tag: "周期导入 Excel",
    accept: ".xlsx,.xls",
    multiple: false,
    pathLabel: "报修 Excel 路径",
    uploadHint: "导入大表类值班/报修流水，例如 20260705故障汇总.xlsx；建议按周或按月增量导入，稳定 ID 会避免重复。",
    placeholder: "选择一个报修 Excel 文件",
  },
  {
    key: "document",
    title: "文件知识库",
    tag: "手册 / FAQ / 错误码",
    accept: ".zip,.doc,.docx,.xlsx",
    multiple: true,
    pathLabel: "文件目录路径",
    uploadHint: "导入明厨亮灶、城域网 ADWAN、承载业务手册、错误代码表等资料；Word 按标题段落切块，普通 Excel 按行入库。",
    placeholder: "支持 .docx、可转换 .doc、普通知识表 .xlsx 或 zip",
  },
];
const kbImportResult = ref(null);
const kbChatInput = ref("");
const kbChatMessages = ref([]);
const kbChatRunning = ref(false);
const kbChatSessions = ref([]);
const kbCurrentSessionId = ref(null);
const kbShowHistory = ref(false);
const aiHistoricalMode = ref(false);

const aiForm = ref({ selectedWindow: 4, customHours: 24 });
const analysisState = ref({ running: false, runUid: "", hours: 4, startedAt: null, elapsed: 0, stageIndex: 0 });
const taskForm = ref({ task_name: "", task_type: "ai_analysis", enabled: true, hours_mode: 24, custom_hours: 24, hours: 24, max_tool_rounds: 2, schedule_type: "interval", interval_minutes: 60, daily_time: "08:00", cron_expr: "", llm_usage_key: "aiops_scheduled_analysis", llm_model_ids: [], remark: "" });
const taskModelDraft = ref([]);
const eventFilters = ref({
  q: "",
  status: "",
  severity: "",
  device: "",
  eventType: "",
  object: "",
  hours: 24,
  start: "",
  end: "",
  page: 1,
  pageSize: 20,
  sort: "last_seen",
  order: "desc",
});
const trapFilters = ref({
  q: "",
  alarmName: "",
  vendor: "",
  lifecycle: "",
  sender: "",
  device: "",
  oid: "",
  matched: "",
  mib: "",
  hours: 24,
  start: "",
  end: "",
  page: 1,
  pageSize: 20,
  order: "desc",
});
const syslogFilters = ref({
  q: "",
  severity: "",
  device: "",
  module: "",
  event: "",
  hours: 24,
  start: "",
  end: "",
  page: 1,
  pageSize: 50,
  order: "desc",
});

const isAdmin = computed(() => user.value?.role === "admin");
const currentTitle = computed(() => {
  if (view.value === "ai" && aiHistoricalMode.value) return "历史 AI 分析报告";
  return navGroups.flatMap((group) => group.items).find((item) => item.key === view.value)?.label || "AI分析结果";
});
const latestRun = computed(() => selectedRun.value || runs.value.find((item) => item.status === "success") || runs.value[0] || null);
const totalEventPages = computed(() => Math.max(1, Math.ceil(eventTotal.value / eventFilters.value.pageSize)));
const totalTrapPages = computed(() => Math.max(1, Math.ceil(trapTotal.value / trapFilters.value.pageSize)));
const totalSyslogPages = computed(() => Math.max(1, Math.ceil(syslogTotal.value / syslogFilters.value.pageSize)));
const totalKbReportPages = computed(() => Math.max(1, Math.ceil(kbTotals.value.reports / kbReportFilters.value.pageSize)));
const totalKbRepairPages = computed(() => Math.max(1, Math.ceil(kbTotals.value.repairs / kbRepairFilters.value.pageSize)));
const totalKbDocumentPages = computed(() => Math.max(1, Math.ceil(kbTotals.value.documents / kbDocumentFilters.value.pageSize)));
const totalKbTopicPages = computed(() => Math.max(1, Math.ceil(kbTotals.value.topics / kbTopicFilters.value.pageSize)));
const uniqueDevices = computed(() => unique(events.value.map((item) => item.device_name || item.device_ip)));
const uniqueEventTypes = computed(() => unique(events.value.map((item) => item.event_type)));
const aiSections = computed(() => ({
  must_handle: collectFindings("must_handle", latestRun.value?.must_handle),
  watch: collectFindings("watch", latestRun.value?.watch),
  recovered: collectFindings("recovered", latestRun.value?.recovered),
  noise: collectFindings("noise", latestRun.value?.noise),
  insufficient: collectFindings("insufficient", latestRun.value?.insufficient),
}));
const dataQualityItems = computed(() => buildDataQuality());
const userRuleHits = computed(() => selectedRun.value?.user_rule_hits || selectedRun.value?.metadata?.user_rule_hits || []);
const nextActions = computed(() => buildActions());
const correlations = computed(() => buildCorrelations());
const lastDataTime = computed(() => newestTime([
  freshness.value?.latest_syslog_at,
  freshness.value?.latest_alarm_event_at,
  latestRun.value?.window_end,
  latestRun.value?.created_at,
  events.value[0]?.last_seen,
]));
const freshnessState = computed(() => {
  const latest = parseDate(lastDataTime.value);
  if (!latest) return { label: "等待数据", tone: "muted", detail: "尚未获取到有效时间戳" };
  const minutes = Math.max(0, Math.round((Date.now() - latest.getTime()) / 60000));
  if (minutes <= 15) return { label: "实时", tone: "ok", detail: `${minutes} 分钟前更新` };
  if (minutes <= 120) return { label: "延迟", tone: "warn", detail: `${minutes} 分钟前更新` };
  return { label: "数据滞后", tone: "danger", detail: `${minutes} 分钟前更新，请检查采集或接口刷新` };
});
const reportSummary = computed(() => ({
  title: latestRun.value?.overall_title || (analysisState.value.running ? "AI 正在研判当前窗口" : "暂无 AI 分析结论"),
  text: latestRun.value?.summary_text || (analysisState.value.running ? "后台正在收集事件、识别关联并生成研判报告。完成后页面会自动刷新为最新成功报告。" : "尚未获取到成功的 AI 研判结果。请确认定时任务是否运行，或由管理员手动触发一次分析。"),
  level: levelLabel(latestRun.value?.overall_level),
}));
const sourceSummary = computed(() => {
  const windows = overview.value?.windows || [];
  const item = windows.find((row) => Number(row.hours) === Number(latestRun.value?.hours || aiForm.value.customHours)) || windows.find((row) => Number(row.hours) === 24) || {};
  return [
    { label: "Syslog", value: item.syslog_parsed ?? "-" },
    { label: "Trap", value: item.trap_raw ?? traps.value.length ?? "-" },
    { label: "Events", value: item.alarm_events ?? events.value.length ?? "-" },
  ];
});
const dashboardMetricCards = computed(() => {
  const windows = overview.value?.windows || [];
  const day = windows.find((row) => Number(row.hours) === 24) || {};
  const runSuccess = runs.value.filter((item) => item.status === "success").length;
  return [
    { label: "24h Syslog", value: day.syslog_parsed ?? "-", hint: "城域网日志接入量" },
    { label: "24h Trap", value: day.trap_raw ?? traps.value.length ?? "-", hint: "SNMP Trap 原始告警" },
    { label: "24h Events", value: day.alarm_events ?? events.value.length ?? "-", hint: "聚合后事件" },
    { label: "AI 分析", value: runs.value.length || "-", hint: runSuccess ? `${runSuccess} 次成功分析` : "等待分析记录" },
    { label: "故障报告", value: kbSummary.value?.formal_report_count ?? kbSummary.value?.formal_count ?? "-", hint: "重点故障知识库" },
    { label: "报修流水", value: kbSummary.value?.repair_count ?? "-", hint: "历史值班经验" },
    { label: "文件知识", value: kbSummary.value?.document_count ?? "-", hint: "手册与错误码" },
    { label: "AI 问答", value: Math.floor((kbSummary.value?.chat_message_count || 0) / 2) || "-", hint: `${kbSummary.value?.chat_session_count || 0} 个会话` },
  ];
});
const dashboardTrendRows = computed(() => {
  const windows = overview.value?.windows || [];
  const maxValue = Math.max(1, ...windows.flatMap((row) => [Number(row.syslog_parsed || 0), Number(row.trap_raw || 0), Number(row.alarm_events || 0)]));
  return windows.slice(0, 4).map((row) => ({
    label: `最近 ${row.hours}h`,
    syslog: Number(row.syslog_parsed || 0),
    trap: Number(row.trap_raw || 0),
    events: Number(row.alarm_events || 0),
    syslogWidth: `${Math.max(4, (Number(row.syslog_parsed || 0) / maxValue) * 100)}%`,
    trapWidth: `${Math.max(4, (Number(row.trap_raw || 0) / maxValue) * 100)}%`,
    eventWidth: `${Math.max(4, (Number(row.alarm_events || 0) / maxValue) * 100)}%`,
  }));
});
const runningPercent = computed(() => `${Math.min(88, 12 + analysisState.value.stageIndex * 13 + Math.floor(analysisState.value.elapsed / 12))}%`);
const findingCounts = computed(() => ({
  must: aiSections.value.must_handle.length,
  watch: aiSections.value.watch.length,
  recovered: aiSections.value.recovered.length,
  insufficient: aiSections.value.insufficient.length,
}));
const runSource = computed(() => {
  const meta = latestRun.value?.metadata || latestRun.value?.agent_runtime || {};
  if (meta?.scheduled_task_id || latestRun.value?.scheduled_task_id) return "定时任务";
  if (analysisState.value.runUid && latestRun.value?.run_uid === analysisState.value.runUid) return "手动触发";
  return latestRun.value ? "历史结果" : "-";
});
const currentClock = computed(() => formatFullTime(currentTime.value.toISOString()));
const analysisDisplay = computed(() => adaptAnalysisDisplay());
const riskTagText = computed(() => {
  const codeMap = { stable: "STABLE", minor: "MINOR", attention: "ATTENTION", critical: "CRITICAL" };
  return `${codeMap[analysisDisplay.value.overallStatus] || "AI"} / ${analysisDisplay.value.overallTitle}`;
});
const chatModels = computed(() => llmModels.value.filter((item) => item.endpoint_type === "chat" && item.enabled));
const selectedUsageBindings = computed(() => llmBindings.value.filter((item) => item.usage_key === activeUsageKey.value).sort((a, b) => a.priority - b.priority));

function unique(values) {
  return [...new Set(values.filter(Boolean).map(String))].slice(0, 80);
}

function parseDate(value) {
  if (!value) return null;
  const textValue = String(value);
  const normalized = /Z$|[+-]\d\d:\d\d$/.test(textValue) ? textValue : `${textValue.replace(" ", "T")}Z`;
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? null : date;
}

function parseFilterTime(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";
  const normalized = raw
    .replace(/\//g, "-")
    .replace(" ", "T")
    .replace(/^(\d{4}-\d{1,2}-\d{1,2})$/, "$1T00:00:00")
    .replace(/^(\d{4}-\d{1,2}-\d{1,2})T(\d{1,2}:\d{1,2})$/, "$1T$2:00");
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? "" : date.toISOString();
}

function formatTime(value) {
  const date = parseDate(value);
  if (!date) return "-";
  return new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(date).replace(/\//g, "-");
}

function formatFullTime(value) {
  const date = parseDate(value);
  if (!date) return "-";
  return new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(date).replace(/\//g, "-");
}

function newestTime(values) {
  return values.map(parseDate).filter(Boolean).sort((a, b) => b - a)[0]?.toISOString() || null;
}

function text(value, fallback = "-") {
  if (value === 0) return "0";
  if (Array.isArray(value)) return value.length ? value.map((item) => text(item)).join("、") : fallback;
  if (value && typeof value === "object") return readableObject(value);
  return value || fallback;
}

function shortText(value, max = 120) {
  const valueText = text(value, "");
  return valueText.length > max ? `${valueText.slice(0, max)}...` : valueText;
}

function runModelText(run) {
  if (!run) return "未记录";
  return run.model_trace || [run.llm_provider, run.model_name].filter(Boolean).join(" / ") || "未记录";
}

function readableObject(value) {
  if (!value || typeof value !== "object") return String(value || "");
  return Object.entries(value)
    .filter(([, item]) => item !== null && item !== undefined && item !== "")
    .slice(0, 6)
    .map(([key, item]) => `${humanizeKey(key)}：${Array.isArray(item) ? item.join("、") : typeof item === "object" ? JSON.stringify(item) : item}`)
    .join("；");
}

function humanizeKey(key) {
  const map = {
    correlation_type: "关联类型",
    devices: "涉及设备",
    objects: "涉及对象",
    conclusion: "AI结论",
    evidence: "证据",
    event_count: "事件数量",
    missing_data: "缺失数据",
    root_cause_hypothesis: "根因判断",
  };
  return map[key] || String(key).replace(/_/g, " ");
}

function levelLabel(level) {
  const raw = String(level || "normal").toLowerCase();
  if (raw === "unknown") return "证据不足";
  return raw;
}

function levelClass(level) {
  const raw = String(level || "normal").toLowerCase();
  return raw === "unknown" ? "insufficient" : raw;
}

function normalizeItem(item, category = "") {
  if (!item || typeof item !== "object") return { title: String(item || "未命名事项"), category };
  return {
    id: item.id || item.finding_uid || item.title,
    category: item.category || category,
    title: item.title || item.name || item.summary || "未命名事项",
    device: item.device_name || item.device_ip || item.device || item.target || "-",
    object: item.object_key || item.object || item.interface || "-",
    judgment: item.root_cause_hypothesis || item.reason || item.ai_judgment || item.description || item.summary || "当前证据仍需结合现场状态确认。",
    evidence: item.evidence || item.event_types || item.related_events || item.signal || null,
    impact: item.impact || item.risk || "影响范围待结合业务拓扑确认。",
    action: item.recommended_actions || item.action || item.next_action || item.suggestion || null,
    confidence: item.confidence,
    severity: item.severity || item.priority,
    missing: item.missing_data,
    lifecycle: item.lifecycle_status,
    raw: item.raw_finding || item,
  };
}

function adaptAnalysisDisplay() {
  const structured = latestRun.value || {};
  const ruleIssues = buildRuleIssues();
  const explicitRisks = Array.isArray(structured.top_risks) ? structured.top_risks.map((item, index) => normalizeRiskCard(item, index)) : [];
  const inferredRisks = explicitRisks.length ? explicitRisks : buildTopRisks(ruleIssues);
  const status = normalizeOverallStatus(structured.overall_status) || inferOverallStatus(inferredRisks, ruleIssues);
  const statusCopy = statusText(status, inferredRisks, ruleIssues);
  const conclusion = clampChinese(
    structured.ai_conclusion || statusCopy.conclusion || `当前风险主要集中在${inferredRisks.slice(0, 2).map((item) => item.shortName || item.typeLabel).join("与") || "系统运行状态"}。`,
    40,
  );
  const ruleStats = buildRuleStats(ruleIssues);
  return {
    overallStatus: status,
    overallTitle: buildHeroTitle(inferredRisks, statusCopy.title),
    overallSummary: structured.overall_summary || statusCopy.summary,
    aiConclusion: `AI助手提示：${conclusion}`,
    assistantMood: normalizeAssistantMood(structured.assistant_mood) || status,
    assistantText: assistantText(status),
    topRisks: inferredRisks.slice(0, 4),
    analysisIssues: Array.isArray(structured.analysis_issues) ? structured.analysis_issues.map((item, index) => normalizeRiskCard(item, index, "rule_issue")) : ruleIssues,
    ruleStats,
    recommendation: recommendationText(status, inferredRisks, ruleIssues),
  };
}

function normalizeOverallStatus(value) {
  const raw = String(value || "").toLowerCase();
  if (["stable", "minor", "attention", "critical"].includes(raw)) return raw;
  if (["normal", "ok", "healthy"].includes(raw)) return "stable";
  if (["major", "warn", "warning"].includes(raw)) return "attention";
  return "";
}

function buildHeroTitle(risks, fallback) {
  const haystack = risks.map((item) => `${item.title} ${item.summary} ${item.tags.join(" ")}`).join(" ");
  if (hasAny(haystack, ["光模块", "光口", "transceiver", "optical"]) && hasAny(haystack, ["bfd", "丢包", "链路"])) {
    return "光模块风险未恢复，链路质量伴随BFD波动";
  }
  if (hasAny(haystack, ["光模块", "光口", "transceiver", "optical"])) return "光口故障持续未恢复";
  if (hasAny(haystack, ["bfd", "丢包", "链路"])) return "链路质量出现联动异常";
  if (hasAny(haystack, ["radius", "认证", "计费"])) return "认证计费服务异常需复核";
  return fallback || "AI运维态势研判完成";
}

function normalizeAssistantMood(value) {
  const raw = String(value || "").toLowerCase();
  if (["stable", "minor", "attention", "critical"].includes(raw)) return raw;
  if (["calm", "relaxed", "green"].includes(raw)) return "stable";
  if (["focused", "focus", "watch"].includes(raw)) return "minor";
  if (["alert", "warning", "orange"].includes(raw)) return "attention";
  if (["alarm", "danger", "red"].includes(raw)) return "critical";
  return "";
}

function inferOverallStatus(risks, ruleIssues) {
  const must = aiSections.value.must_handle;
  const watch = aiSections.value.watch;
  const hasCritical = must.some((item) => isCriticalRisk(item));
  const hasMajorOpen = must.concat(watch).some((item) => hasAny(`${item.severity} ${item.lifecycle} ${item.title} ${item.judgment}`, ["major", "open", "未恢复", "光模块", "链路", "bfd", "中断", "核心"]));
  if (hasCritical) return "critical";
  if (hasMajorOpen || watch.length || risks.some((item) => ["unrecovered_fault", "correlated_risk"].includes(item.type))) return "attention";
  if (aiSections.value.recovered.length || aiSections.value.noise.length || aiSections.value.insufficient.length || ruleIssues.length) return "minor";
  return "stable";
}

function isCriticalRisk(item) {
  const haystack = `${item.severity} ${item.title} ${item.judgment} ${item.impact}`.toLowerCase();
  return hasAny(haystack, ["critical", "p1", "业务影响", "核心", "中断", "不可达", "多设备同源"]);
}

function statusText(status, risks, ruleIssues) {
  const unrecovered = risks.filter((item) => item.type === "unrecovered_fault").length;
  const correlated = risks.filter((item) => item.type === "correlated_risk").length;
  const recovered = aiSections.value.recovered.length;
  const ruleCount = ruleIssues.length;
  const map = {
    stable: { title: "系统平稳", summary: "当前窗口未发现需人工处置的重大风险，系统运行整体稳定。", conclusion: "当前窗口未发现重大风险，系统运行整体稳定" },
    minor: { title: "轻微异常", summary: "检测到少量异常事件，当前未见明显业务影响，建议持续观察。", conclusion: "当前仅有轻微异常或已恢复事件，建议持续观察" },
    attention: { title: "重要关注", summary: `检测到${unrecovered || "未恢复"}项未恢复故障、${correlated || "关联"}项链路关联异常，建议值班人员重点关注。`, conclusion: "当前风险主要集中在未恢复故障与链路关联异常" },
    critical: { title: "严重异常", summary: "检测到可能影响业务的核心异常，请立即处理。", conclusion: "当前存在可能影响业务的核心异常，请立即处理" },
  };
  const selected = map[status] || map.stable;
  if (status === "minor" && (recovered || ruleCount)) {
    return { ...selected, summary: `当前主要为${recovered}项已恢复事件和${ruleCount}项规则/降噪问题，建议持续观察。` };
  }
  return selected;
}

function assistantText(status) {
  const map = {
    stable: "系统运行平稳，AI助手持续巡检中。",
    minor: "发现轻微异常，正在持续监测趋势变化。",
    attention: "检测到重点风险，建议人工关注。",
    critical: "发现严重异常，请立即处理。",
  };
  return map[status] || map.stable;
}

function buildTopRisks(ruleIssues = []) {
  const cards = [];
  const must = aiSections.value.must_handle.filter((item) => !isRuleLikeRisk(item));
  const watch = aiSections.value.watch.filter((item) => !isRuleLikeRisk(item));
  must.forEach((item, index) => cards.push(riskFromFinding(item, "unrecovered_fault", "未恢复故障", index)));
  buildCorrelationRiskCards().forEach((item) => cards.push(item));
  watch.forEach((item, index) => {
    if (!cards.some((card) => isSimilarTitle(card.title, item.title))) cards.push(riskFromFinding(item, "watch_risk", "重点关注", index));
  });
  aiSections.value.recovered.slice(0, 1).forEach((item, index) => cards.push(riskFromFinding(item, "recovered_event", "已恢复事件", index)));
  ruleIssues.slice(0, 1).forEach((item) => cards.push(item));
  if (!cards.length && reportSummary.value.title && latestRun.value) cards.push(...fallbackRisksFromSummary());
  return cards.slice(0, 4);
}

function buildCorrelationRiskCards() {
  return correlations.value.slice(0, 2).map((item, index) => normalizeRiskCard({
    type: "correlated_risk",
    typeLabel: "关联异常",
    level: inferLevel(`${item.title} ${item.conclusion}`),
    status: "active",
    title: item.title,
    summary: item.conclusion,
    metrics: [`证据${item.evidenceCount}条`, item.type, "重点关注"],
    tags: inferTags(`${item.title} ${item.conclusion} ${item.type}`),
    source: { title: item.title, judgment: item.conclusion, evidence: item.raw.evidence, raw: item.raw },
  }, index));
}

function riskFromFinding(item, type, typeLabel, index = 0) {
  const haystack = `${item.title} ${item.judgment} ${item.device} ${item.object} ${item.evidence}`;
  const level = inferLevel(`${item.severity} ${haystack}`);
  return normalizeRiskCard({
    type,
    typeLabel,
    level,
    status: item.lifecycle || (type === "recovered_event" ? "recovered" : "open"),
    title: cleanRiskTitle(item.title, haystack),
    summary: cleanRiskSummary(item.judgment),
    metrics: inferMetrics(item, type),
    tags: inferTags(haystack),
    source: item,
  }, index);
}

function normalizeRiskCard(item, index = 0, fallbackType = "") {
  const source = item?.source || item?.raw || item;
  const type = item?.type || fallbackType || "risk";
  const title = cleanRiskTitle(item?.title || item?.name || item?.summary || `风险项 ${index + 1}`);
  return {
    id: item?.id || `${type}-${index}-${title}`,
    type,
    typeLabel: item?.typeLabel || item?.type_label || riskTypeLabel(type),
    level: item?.level || item?.severity || "major",
    status: item?.status || "active",
    title,
    shortName: shortRiskName(title),
    summary: cleanRiskSummary(item?.summary || item?.description || item?.judgment || "当前证据仍需结合现场状态确认。"),
    metrics: normalizeStringArray(item?.metrics).slice(0, 3),
    tags: normalizeStringArray(item?.tags).slice(0, 4),
    source,
  };
}

function buildRuleIssues() {
  const issues = [];
  const explicit = latestRun.value?.rule_anomalies || latestRun.value?.analysis_issues;
  if (Array.isArray(explicit)) {
    explicit.filter((item) => `${item.type || item.type_label || ""}`.includes("rule")).forEach((item, index) => issues.push(normalizeRiskCard(item, index, "rule_issue")));
  }
  userRuleHits.value.forEach((hit, index) => {
    const raw = `${hit.raw_text || hit.rule_name || ""} ${hit.action_result || ""} ${text(hit.matched_target, "")}`.toLowerCase();
    const anomalous = hit.safety_exception?.length || raw.includes("uplift") || raw.includes("boost") || raw.includes("blocked") || (raw.includes("radius") && !raw.includes("suppressed"));
    if (anomalous) {
      issues.push(normalizeRiskCard({
        type: "rule_issue",
        typeLabel: "规则异常",
        level: "minor",
        status: "pending",
        title: raw.includes("radius") ? "RADIUS 降噪规则需要复核" : (hit.raw_text || hit.rule_name || "用户规则命中需复核"),
        summary: hit.safety_exception?.length ? "用户规则要求降噪，但触发安全例外，AI仍保留输出。" : "用户规则命中结果与预期存在差异，需检查规则优先级和动作。",
        metrics: [ruleResultLabel(hit.action_result), hit.safety_exception?.length ? "安全例外" : "待复核"],
        tags: ["规则", "降噪", "AI分析修正"],
        source: hit,
      }, index));
    }
  });
  return dedupeCards(issues).slice(0, 3);
}

function buildRuleStats(ruleIssues) {
  const hits = userRuleHits.value;
  return {
    hitCount: hits.length,
    anomalyCount: ruleIssues.length,
    suppressedCount: hits.filter((item) => String(item.action_result || "").includes("suppress")).length,
    upliftCount: hits.filter((item) => hasAny(`${item.action_result || ""}`, ["boost", "uplift"])).length,
  };
}

function fallbackRisksFromSummary() {
  const parts = String(reportSummary.value.title || "").split(/\s*[+＋]\s*/).filter(Boolean);
  return parts.slice(0, 3).map((part, index) => normalizeRiskCard({
    type: hasAny(part, ["恢复", "clear"]) ? "recovered_event" : "unrecovered_fault",
    typeLabel: hasAny(part, ["恢复", "clear"]) ? "已恢复事件" : "核心风险",
    level: inferLevel(part),
    status: hasAny(part, ["恢复", "clear"]) ? "recovered" : "open",
    title: part,
    summary: reportSummary.value.text,
    metrics: [inferLevel(part), "来自报告摘要"],
    tags: inferTags(part),
    source: { title: part, judgment: reportSummary.value.text },
  }, index));
}

function isRuleLikeRisk(item) {
  const haystack = `${item.title} ${item.judgment} ${item.action}`.toLowerCase();
  return hasAny(haystack, ["规则", "rule", "降噪", "suppress", "uplift"]);
}

function cleanRiskTitle(value, haystack = "") {
  const textValue = shortText(String(value || "").replace(/\s*[+＋]\s*/g, " / "), 58);
  if (hasAny(`${textValue} ${haystack}`, ["radius", "认证", "计费"]) && hasAny(`${textValue} ${haystack}`, ["光模块", "transceiver", "optical", "链路", "bfd"])) {
    const opticalPart = textValue.split(/[+/／]/).find((part) => hasAny(part, ["光", "transceiver", "optical", "xge", "链路", "bfd"]));
    return shortText(opticalPart || textValue, 48);
  }
  return textValue;
}

function cleanRiskSummary(value) {
  return shortText(String(value || "当前证据仍需结合现场状态确认。").replace(/\s+/g, " "), 86);
}

function shortRiskName(title) {
  if (hasAny(title, ["光模块", "transceiver", "optical", "光口"])) return "光模块未恢复";
  if (hasAny(title, ["bfd", "丢包", "链路"])) return "链路质量波动";
  if (hasAny(title, ["radius", "认证", "计费"])) return "RADIUS规则";
  return shortText(title, 12);
}

function inferMetrics(item, type) {
  const haystack = `${item.title} ${item.judgment} ${item.evidence} ${item.lifecycle}`;
  const metrics = [];
  const duration = haystack.match(/持续\s*([0-9.]+\s*(?:小时|分钟|h|H|天|\+))/);
  if (duration) metrics.push(`持续${duration[1]}`);
  metrics.push(type === "recovered_event" ? "已恢复" : `状态${item.lifecycle || "open"}`);
  metrics.push(`等级${levelLabel(item.severity || "major")}`);
  return metrics.slice(0, 3);
}

function inferTags(value) {
  const haystack = String(value || "").toLowerCase();
  const tags = [];
  if (hasAny(haystack, ["光模块", "光口", "transceiver", "optical", "xge"])) tags.push("光模块");
  if (hasAny(haystack, ["未恢复", "open", "unclear"])) tags.push("未恢复");
  if (hasAny(haystack, ["bfd", "flap"])) tags.push("BFD");
  if (hasAny(haystack, ["丢包", "packet", "loss", "链路"])) tags.push("链路质量");
  if (hasAny(haystack, ["radius", "认证", "计费"])) tags.push("RADIUS");
  if (hasAny(haystack, ["规则", "rule", "降噪", "suppress"])) tags.push("规则");
  if (!tags.length) tags.push("AI研判");
  return tags.slice(0, 4);
}

function inferLevel(value) {
  const raw = String(value || "").toLowerCase();
  if (hasAny(raw, ["critical", "p1", "严重", "重大"])) return "critical";
  if (hasAny(raw, ["major", "重要", "未恢复", "open"])) return "major";
  if (hasAny(raw, ["minor", "轻微", "已恢复", "recovered"])) return "minor";
  return "major";
}

function riskTypeLabel(type) {
  const map = { unrecovered_fault: "未恢复故障", correlated_risk: "关联异常", recovered_event: "已恢复事件", rule_issue: "规则异常", watch_risk: "重点关注" };
  return map[type] || "核心风险";
}

function normalizeStringArray(value) {
  if (Array.isArray(value)) return value.filter(Boolean).map(String);
  if (!value) return [];
  return [String(value)];
}

function dedupeCards(items) {
  const seen = new Set();
  return items.filter((item) => {
    const key = `${item.type}-${item.title}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function isSimilarTitle(a, b) {
  const left = String(a || "").slice(0, 16);
  const right = String(b || "").slice(0, 16);
  return left && right && (left.includes(right) || right.includes(left));
}

function recommendationText(status, risks, ruleIssues) {
  if (status === "critical") return "立即处理核心异常";
  if (risks.some((item) => hasAny(item.title, ["光", "链路", "BFD", "丢包"]))) return "优先检查光模块与链路质量";
  if (ruleIssues.length) return "复核规则优先级与降噪动作";
  if (status === "stable") return "保持巡检";
  return "持续观察趋势";
}

function clampChinese(value, max = 40) {
  const plain = String(value || "").replace(/^AI判断[:：]?/, "").replace(/\s+/g, "");
  return plain.length > max ? `${plain.slice(0, max)}...` : plain;
}

function hasAny(value, keywords) {
  const haystack = String(value || "").toLowerCase();
  return keywords.some((keyword) => haystack.includes(String(keyword).toLowerCase()));
}

function collectFindings(category, fallback = []) {
  const fromDb = findings.value.filter((item) => item.category === category).map((item) => normalizeItem(item, category));
  if (fromDb.length) return fromDb;
  return (Array.isArray(fallback) ? fallback : []).map((item) => normalizeItem(item, category));
}

function actionText(action) {
  if (!action) return "结合证据继续确认。";
  if (Array.isArray(action)) return action.join("；");
  if (typeof action === "object") return Object.entries(action).map(([key, value]) => `${humanizeKey(key)}：${Array.isArray(value) ? value.join("、") : text(value)}`).join("；");
  return String(action);
}

function evidenceText(evidence) {
  if (!evidence) return "暂无结构化证据。";
  if (Array.isArray(evidence)) return evidence.map((item) => text(item)).join("；");
  if (typeof evidence === "object") return Object.entries(evidence).map(([key, value]) => `${humanizeKey(key)}：${text(value)}`).join("；");
  return String(evidence);
}

function firstEvidence(item) {
  if (Array.isArray(item.evidence) && item.evidence.length) return shortText(item.evidence[0], 120);
  if (item.evidence && typeof item.evidence === "object") {
    const [key, value] = Object.entries(item.evidence)[0] || [];
    if (key) return shortText(`${humanizeKey(key)}：${text(value)}`, 120);
  }
  return shortText(item.judgment, 120);
}

function confidenceText(value) {
  if (value === null || value === undefined || value === "") return "未记录";
  const number = Number(value);
  if (Number.isNaN(number)) return String(value);
  return number <= 1 ? `${Math.round(number * 100)}%` : `${Math.round(number)}%`;
}

function buildActions() {
  const direct = Array.isArray(latestRun.value?.next_actions) ? latestRun.value.next_actions.map((item, index) => normalizeAction(item, index)) : [];
  const fromFindings = aiSections.value.must_handle.concat(aiSections.value.watch).slice(0, 6).map((item, index) => ({
    priority: index < 2 ? "P1" : "P2",
    owner: inferOwner(item),
    target: `${item.device} ${item.object}`.trim(),
    title: item.title,
    reason: item.judgment,
    action: actionText(item.action),
    related: text(item.evidence, "关联事件待补充"),
    source: item,
  }));
  return direct.length ? direct : fromFindings;
}

function normalizeAction(item, index) {
  if (!item || typeof item !== "object") return { priority: index < 2 ? "P1" : "P2", owner: "网管", target: "当前窗口", title: String(item || "建议动作"), reason: "AI 研判输出", action: String(item || ""), related: "-" };
  return {
    priority: item.priority || item.level || (index < 2 ? "P1" : "P2"),
    owner: item.owner || item.team || "网管",
    target: item.target || item.object || item.device || "当前窗口",
    title: item.title || item.action || "建议动作",
    reason: item.reason || item.why || "基于当前事件证据链生成。",
    action: actionText(item.steps || item.recommended_action || item.action || item.description),
    related: text(item.related_events || item.event_types || item.evidence, "-"),
    source: item,
  };
}

function inferOwner(item) {
  const haystack = `${item.title} ${item.device} ${item.object} ${item.judgment}`.toLowerCase();
  if (haystack.includes("radius") || haystack.includes("server")) return "系统";
  if (haystack.includes("link") || haystack.includes("interface") || haystack.includes("optical")) return "传输";
  return "网管";
}

function buildCorrelations() {
  const raw = Array.isArray(latestRun.value?.correlations) ? latestRun.value.correlations : [];
  return raw.map((item, index) => {
    const source = item && typeof item === "object" ? item : { summary: String(item || "") };
    return {
      id: index,
      title: source.title || source.name || source.chain || source.summary || "同窗口事件关联",
      type: humanCorrelationType(source.correlation_type || source.type),
      devices: text(source.devices || source.device_names || source.device || source.device_name, "待确认"),
      objects: text(source.objects || source.object_keys || source.object || source.object_key, "待确认"),
      conclusion: source.conclusion || source.reason || source.summary || "AI 已识别到同窗口关联，需要结合证据确认因果方向。",
      evidenceCount: Array.isArray(source.evidence) ? source.evidence.length : Number(source.evidence_count || source.event_count || 1),
      raw: source,
    };
  });
}

function humanCorrelationType(type) {
  const raw = String(type || "").toLowerCase();
  if (raw.includes("device")) return "同设备关联";
  if (raw.includes("object")) return "同对象关联";
  if (raw.includes("server")) return "同服务器关联";
  if (raw.includes("cascade")) return "级联关系";
  if (raw.includes("time")) return "同时间窗口";
  return "同窗口关联";
}

function buildDataQuality() {
  const quality = latestRun.value?.data_quality || {};
  const items = [
    { key: "untranslated_traps", label: "待补充 MIB", value: quality.untranslated_traps ?? traps.value.filter((item) => item.mib_translated === false).length, detail: "未翻译 Trap 会降低 Trap 语义判断精度。" },
    { key: "missing_mib", label: "缺失 MIB", value: quality.missing_mib ?? countMissing("mib"), detail: "部分 OID 未匹配到 MIB 字典。" },
    { key: "unmatched_devices", label: "设备身份未确认", value: quality.unmatched_devices ?? traps.value.filter((item) => !item.managed_device_name && !item.managed_device_ip).length, detail: "Trap Sender 与真实管理设备仍需补充映射。" },
    { key: "topology_missing", label: "拓扑上下文不足", value: quality.topology_missing ?? traps.value.filter((item) => !item.matched_link && !item.topology_match).length, detail: "缺少链路或对象拓扑会影响根因链路判断。" },
    { key: "field_anomalies", label: "字段异常", value: quality.field_anomalies ?? countMissing("field"), detail: "部分事件字段缺失或格式异常。" },
    { key: "context_gaps", label: "证据不足", value: quality.context_gaps ?? aiSections.value.insufficient.length, detail: "AI 已识别到需要补充上下文的事项。" },
  ];
  return items.map((item) => ({ ...item, value: Number(item.value || 0), raw: quality }));
}

function scheduleLabel(task) {
  if (!task) return "-";
  if (task.schedule_type === "daily") return `每天 ${task.daily_time || "08:00"} 执行`;
  if (task.schedule_type === "cron") return `Cron：${task.cron_expr || "未配置"}`;
  return `每隔 ${task.interval_minutes || 60} 分钟执行一次`;
}

function taskTypeLabel(value) {
  const map = { ai_analysis: "AI 告警分析", events_aggregation: "Events 聚合", trap_check: "Trap 解析检查", data_quality: "数据质量检查" };
  return map[value] || "AI 告警分析";
}

function analysisWindowLabel(task) {
  const hours = Number(task?.hours || 24);
  const map = { 4: "最近 4 小时", 12: "最近 12 小时", 24: "最近 24 小时" };
  return map[hours] || `最近 ${hours} 小时`;
}

function durationText(ms) {
  const number = Number(ms || 0);
  if (!number) return "-";
  if (number < 1000) return `${number} ms`;
  if (number < 60000) return `${Math.round(number / 1000)} 秒`;
  return `${Math.round(number / 60000)} 分钟`;
}

function modelOptionLabel(item) {
  if (!item) return "-";
  return `${item.provider_name || "未分组"} / ${item.display_name || item.model_id}`;
}

function endpointLabel(value) {
  const map = { chat: "对话", embeddings: "向量", rerank: "重排序" };
  return map[value] || text(value);
}

function inputTypeLabel(value) {
  return Array.isArray(value) ? value.join("、") : text(value);
}

function taskModelRows() {
  const byId = new Map(chatModels.value.map((item) => [String(item.id), item]));
  return taskModelDraft.value.map((id, index) => ({ id, index, model: byId.get(String(id)) })).filter((item) => item.model);
}

function ruleTypeLabel(value) {
  const map = { attention: "重点关注", noise_reduction: "降噪", threshold: "阈值控制", report_preference: "报告偏好", unknown: "未识别" };
  return map[value] || text(value);
}

function ruleActionLabel(value) {
  const map = { boost_priority: "提高优先级", downgrade_or_suppress: "降低优先级 / 默认抑制展示", threshold_control: "阈值控制", format_control: "格式控制", unknown: "未识别" };
  return map[value] || text(value);
}

function ruleResultLabel(value) {
  const map = { boosted: "已提高优先级", suppressed: "已降噪", downgrade_blocked_by_safety_exception: "触发安全例外，仍输出" };
  return map[value] || text(value);
}

function ruleUnderstanding(rule) {
  const parsed = rule?.parsed_rule || rule || {};
  if (parsed.human_readable_summary) return parsed.human_readable_summary;
  const parts = [
    ruleTypeLabel(parsed.rule_type),
    ruleActionLabel(parsed.action),
    listText(parsed.target_event_families, "未限定事件族"),
    listText(parsed.target_devices, "未限定设备"),
    listText(parsed.target_objects, "未限定对象"),
  ];
  if (parsed.threshold_count) parts.push(`阈值 ${parsed.threshold_count} 次`);
  if (parsed.safety_exceptions?.length) parts.push(`安全例外 ${parsed.safety_exceptions.length} 条`);
  return parts.filter(Boolean).join(" · ");
}

function listText(value, fallback = "-") {
  const items = Array.isArray(value) ? value : value ? [value] : [];
  return items.length ? items.join("、") : fallback;
}

function resetTaskForm(task = null) {
  editingTask.value = task;
  const hours = Number(task?.hours || 24);
  taskForm.value = {
    task_name: task?.task_name || "",
    task_type: task?.task_type || "ai_analysis",
    enabled: task?.enabled ?? true,
    hours_mode: [4, 12, 24].includes(hours) ? hours : "custom",
    custom_hours: [4, 12, 24].includes(hours) ? 24 : hours,
    hours,
    max_tool_rounds: task?.max_tool_rounds ?? 2,
    schedule_type: task?.schedule_type || "interval",
    interval_minutes: task?.interval_minutes || 60,
    daily_time: task?.daily_time || "08:00",
    cron_expr: task?.cron_expr || "",
    llm_usage_key: task?.llm_usage_key || "aiops_scheduled_analysis",
    llm_model_ids: (task?.llm_model_ids || []).map(String),
    remark: task?.remark || "",
  };
  taskModelDraft.value = (task?.llm_model_ids || []).map(String);
  taskDrawerOpen.value = true;
  if (!llmModels.value.length) guarded(loadLlmInventory, { silent: true });
}

function taskPayload() {
  const mode = taskForm.value.hours_mode;
  const hours = mode === "custom" ? Number(taskForm.value.custom_hours || 24) : Number(mode);
  return { ...taskForm.value, hours, llm_model_ids: taskModelDraft.value.map((item) => Number(item)).filter(Boolean) };
}

function addTaskModelDraft() {
  const first = chatModels.value.find((item) => !taskModelDraft.value.includes(String(item.id))) || chatModels.value[0];
  if (first) taskModelDraft.value.push(String(first.id));
}

function removeTaskModelDraft(index) {
  taskModelDraft.value.splice(index, 1);
}

function resetUserForm(row = null) {
  editingUser.value = row;
  userForm.value = {
    username: row?.username || "",
    display_name: row?.display_name || "",
    password: "",
    role: row?.role || "viewer",
    is_active: row?.is_active ?? true,
    remark: "",
  };
  userDrawerOpen.value = true;
}

function openFinding(item, tab = "summary") {
  selectedFinding.value = item;
  drawerTab.value = tab;
}

function exportMarkdownReport() {
  if (!latestRun.value) return;
  const lines = [
    `# ${reportSummary.value.title}`,
    "",
    `- 风险等级：${reportSummary.value.level}`,
    `- 分析时间：${formatFullTime(latestRun.value.created_at)}`,
    `- 分析窗口：${formatFullTime(latestRun.value.window_start)} 至 ${formatFullTime(latestRun.value.window_end)}`,
    `- 模型：${runModelText(latestRun.value)}`,
    `- Run ID：${latestRun.value.run_uid || "-"}`,
    "",
    "## 一句话总结",
    reportSummary.value.text,
    "",
    "## 必须处理",
    ...markdownFindingList(aiSections.value.must_handle),
    "",
    "## 重点关注",
    ...markdownFindingList(aiSections.value.watch),
    "",
    "## 已恢复",
    ...markdownFindingList(aiSections.value.recovered),
    "",
    "## 证据不足",
    ...markdownFindingList(aiSections.value.insufficient),
    "",
    "## 建议动作",
    ...nextActions.value.map((item) => `- ${item.priority} ${item.title}：${item.action}`),
  ];
  const blob = new Blob([lines.join("\n")], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `aiops-report-${latestRun.value.run_uid || Date.now()}.md`;
  anchor.click();
  URL.revokeObjectURL(url);
}

function markdownFindingList(items) {
  if (!items.length) return ["- 暂无"];
  return items.map((item) => `- **${item.title}**：${item.judgment}\n  - 对象：${item.device} ${item.object}\n  - 证据：${firstEvidence(item)}\n  - 建议：${shortText(actionText(item.action), 180)}`);
}

function countMissing(keyword) {
  return findings.value.reduce((sum, item) => {
    const raw = JSON.stringify(item.missing_data || {}).toLowerCase();
    return sum + (raw.includes(keyword) ? 1 : 0);
  }, 0);
}

async function request(path, options = {}) {
  const separator = path.includes("?") ? "&" : "?";
  const response = await fetch(`${apiBase}${path}${separator}_ts=${Date.now()}`, {
    credentials: "include",
    cache: "no-store",
    headers: { "Content-Type": "application/json", "Cache-Control": "no-cache", ...(options.headers || {}) },
    ...options,
  });
  const payload = await parseApiPayload(response);
  if (!response.ok) throw new Error(payload?.error?.message || payload?.error || `HTTP ${response.status}`);
  return payload;
}

function compactResponseText(raw) {
  return String(raw || "").replace(/\s+/g, " ").trim().slice(0, 180);
}

async function parseApiPayload(response) {
  const raw = await response.text();
  if (!raw) return {};
  try {
    return JSON.parse(raw);
  } catch (err) {
    const contentType = response.headers.get("content-type") || "";
    const htmlLike = contentType.includes("text/html") || raw.trim().startsWith("<");
    const reason = htmlLike ? "接口返回了 HTML，通常是登录过期、反向代理未转发到后端，或上传大小被网关拦截" : "接口返回不是合法 JSON";
    throw new Error(`${reason}（HTTP ${response.status}）：${compactResponseText(raw) || err.message}`);
  }
}

async function guarded(action, options = {}) {
  if (!options.silent) loading.value = true;
  error.value = "";
  try {
    await action();
    lastLoadedAt.value = new Date().toISOString();
  } catch (err) {
    error.value = err.message || String(err);
    if (error.value.includes("authentication") || error.value.includes("login")) user.value = null;
  } finally {
    if (!options.silent) loading.value = false;
  }
}

async function loadMe() {
  try {
    user.value = (await request("/auth/me")).user;
  } catch {
    user.value = null;
  } finally {
    authChecked.value = true;
  }
}

async function submitAuth() {
  await guarded(async () => {
    const body = { username: authForm.value.username, password: authForm.value.password };
    user.value = (await request("/auth/login", { method: "POST", body: JSON.stringify(body) })).user;
    await refreshCurrent();
  });
}

async function logout() {
  await request("/auth/logout", { method: "POST", body: "{}" });
  user.value = null;
}

async function switchView(next) {
  if (next !== "ai") aiHistoricalMode.value = false;
  view.value = next;
  if (next === "aiChat") kbActiveTab.value = "chat";
  if (next === "kbManage") kbActiveTab.value = "reports";
  selectedEvent.value = null;
  await guarded(refreshCurrent);
}

async function refreshCurrent() {
  if (!user.value) return;
  if (view.value === "home") await loadDashboard();
  if (view.value === "overview") await loadOverview();
  if (view.value === "events") await loadEvents();
  if (view.value === "syslog") await loadSyslog();
  if (view.value === "trap") await loadTrap();
  if (view.value === "ai" && !aiHistoricalMode.value) await loadAiLatest();
  if (view.value === "history") await loadRuns();
  if (view.value === "aiRules") await loadAiRules();
  if (view.value === "aiChat") await loadAiChat();
  if (view.value === "kbManage" || view.value === "aiOpsKb") await loadFaultKb();
  if (view.value === "tasks") await loadTasks();
  if (view.value === "models") await loadLlmInventory();
  if (view.value === "users") await loadUsers();
  if (view.value === "settings") await loadSettings();
  if (view.value === "operationLogs") await loadOperationLogs();
  if (view.value === "loginLogs") await loadLoginLogs();
  if (view.value === "chatLogs") await loadChatLogs();
  if (view.value === "qqAuditLogs") await loadQqAuditLogs();
}

async function loadOverview() {
  const [o, f, a, t] = await Promise.all([
    request("/runtime/overview?hours=24"),
    request("/runtime/freshness"),
    request("/alarm-events/latest?limit=8&hours=24"),
    request("/trap/latest?limit=100"),
  ]);
  overview.value = o;
  freshness.value = f;
  events.value = a.items || [];
  traps.value = t.items || [];
}

async function loadSyslog() {
  const result = await request(`/syslog/latest?${syslogQuery()}`);
  syslogs.value = result.items || [];
  syslogTotal.value = result.total ?? syslogs.value.length;
  if (syslogFilters.value.page > totalSyslogPages.value) syslogFilters.value.page = totalSyslogPages.value;
}

function syslogQuery() {
  const params = new URLSearchParams();
  const f = syslogFilters.value;
  params.set("hours", f.hours || 24);
  params.set("limit", f.pageSize);
  params.set("offset", (f.page - 1) * f.pageSize);
  params.set("order", f.order);
  if (f.q) params.set("q", f.q);
  if (f.severity) params.set("severity", f.severity);
  if (f.device) {
    params.set(f.device.includes(":") || /^\d+\./.test(f.device) ? "device_ip" : "device_name", f.device);
  }
  if (f.module) params.set("module", f.module);
  if (f.event) params.set("event_family", f.event);
  const start = parseFilterTime(f.start);
  const end = parseFilterTime(f.end);
  if (start) params.set("start", start);
  if (end) params.set("end", end);
  return params.toString();
}

function applySyslogFilters() {
  syslogFilters.value.page = 1;
  guarded(loadSyslog);
}

function clearSyslogFilters() {
  syslogFilters.value = { q: "", severity: "", device: "", module: "", event: "", hours: 24, start: "", end: "", page: 1, pageSize: 50, order: "desc" };
  guarded(loadSyslog);
}

function changeSyslogPage(delta) {
  syslogFilters.value.page = Math.min(totalSyslogPages.value, Math.max(1, syslogFilters.value.page + delta));
  guarded(loadSyslog);
}

async function loadTrap() {
  const result = await request(`/trap?${trapQuery()}`);
  traps.value = result.items || [];
  trapTotal.value = result.total ?? traps.value.length;
}

function trapQuery() {
  const params = new URLSearchParams();
  const f = trapFilters.value;
  params.set("hours", f.hours || 24);
  params.set("limit", f.pageSize);
  params.set("offset", (f.page - 1) * f.pageSize);
  params.set("order", f.order);
  if (f.q) params.set("q", f.q);
  if (f.alarmName) params.set("alarm_name", f.alarmName);
  if (f.vendor) params.set("alarm_vendor", f.vendor);
  if (f.lifecycle) params.set("alarm_lifecycle_status", f.lifecycle);
  if (f.sender) params.set("trap_sender_ip", f.sender);
  if (f.device) {
    params.set(f.device.includes(":") || /^\d+\./.test(f.device) ? "managed_device_ip" : "managed_device_name", f.device);
  }
  if (f.oid) params.set("trap_oid", f.oid);
  if (f.matched) params.set("alarm_definition_matched", f.matched);
  if (f.mib) params.set("mib_translated", f.mib);
  const start = parseFilterTime(f.start);
  const end = parseFilterTime(f.end);
  if (start) params.set("start", start);
  if (end) params.set("end", end);
  return params.toString();
}

function applyTrapFilters() {
  trapFilters.value.page = 1;
  guarded(loadTrap);
}

function clearTrapFilters() {
  trapFilters.value = { q: "", alarmName: "", vendor: "", lifecycle: "", sender: "", device: "", oid: "", matched: "", mib: "", hours: 24, start: "", end: "", page: 1, pageSize: 20, order: "desc" };
  guarded(loadTrap);
}

function changeTrapPage(delta) {
  trapFilters.value.page = Math.min(totalTrapPages.value, Math.max(1, trapFilters.value.page + delta));
  guarded(loadTrap);
}

function eventQuery() {
  const params = new URLSearchParams();
  const f = eventFilters.value;
  params.set("hours", f.hours || 24);
  params.set("limit", f.pageSize);
  params.set("offset", (f.page - 1) * f.pageSize);
  params.set("sort", f.sort);
  params.set("order", f.order);
  if (f.q) params.set("q", f.q);
  if (f.status) params.set("event_status", f.status);
  if (f.severity) params.set("severity_max", f.severity);
  if (f.device) params.set("device", f.device);
  if (f.eventType) params.set("event_type", f.eventType);
  if (f.object) params.set("object_key", f.object);
  if (f.start) params.set("start", new Date(f.start).toISOString());
  if (f.end) params.set("end", new Date(f.end).toISOString());
  return params.toString();
}

async function loadEvents() {
  const [f, result] = await Promise.all([
    request("/runtime/freshness"),
    request(`/alarm-events?${eventQuery()}`),
  ]);
  freshness.value = f;
  events.value = result.items || [];
  eventTotal.value = result.total ?? events.value.length;
  if (eventFilters.value.page > totalEventPages.value) eventFilters.value.page = totalEventPages.value;
}

function applyEventFilters() {
  eventFilters.value.page = 1;
  guarded(loadEvents);
}

function clearEventFilters() {
  eventFilters.value = { q: "", status: "", severity: "", device: "", eventType: "", object: "", hours: 24, start: "", end: "", page: 1, pageSize: 20, sort: "last_seen", order: "desc" };
  guarded(loadEvents);
}

function changeSort(field) {
  if (eventFilters.value.sort === field) eventFilters.value.order = eventFilters.value.order === "desc" ? "asc" : "desc";
  else {
    eventFilters.value.sort = field;
    eventFilters.value.order = "desc";
  }
  guarded(loadEvents);
}

function changePage(delta) {
  eventFilters.value.page = Math.min(totalEventPages.value, Math.max(1, eventFilters.value.page + delta));
  guarded(loadEvents);
}

async function loadRuns() {
  runs.value = (await request("/ai-runs?limit=50")).items || [];
}

async function loadAiLatest() {
  const [allRuns, successRuns, f, o, t] = await Promise.all([
    request("/ai-runs?limit=50"),
    request("/ai-runs?limit=1&status=success"),
    request("/runtime/freshness"),
    request("/runtime/overview?hours=24"),
    request("/trap/latest?limit=100"),
  ]);
  runs.value = allRuns.items || [];
  freshness.value = f;
  overview.value = o;
  traps.value = t.items || [];
  const uid = successRuns.items?.[0]?.run_uid || runs.value.find((item) => item.status === "success")?.run_uid;
  if (!uid) {
    selectedRun.value = null;
    findings.value = [];
    return;
  }
  selectedRun.value = (await request(`/ai-runs/${uid}`)).item;
  await loadRunFindings(uid);
}

async function openRun(runUid) {
  await guarded(async () => {
    selectedRun.value = (await request(`/ai-runs/${runUid}`)).item;
    await loadRunFindings(runUid);
    aiHistoricalMode.value = true;
    view.value = "ai";
    activeAiTab.value = "must_handle";
  });
}

async function openLatestRunInDashboard() {
  await guarded(async () => {
    aiHistoricalMode.value = false;
    await loadAiLatest();
    view.value = "ai";
    activeAiTab.value = "must_handle";
  });
}

async function loadRunFindings(runUid) {
  findings.value = (await request(`/ai-runs/${runUid}/findings`)).items || [];
}

function selectedAnalysisHours() {
  return aiForm.value.selectedWindow === "custom" ? Number(aiForm.value.customHours || 24) : Number(aiForm.value.selectedWindow);
}

async function startAiRun() {
  if (!isAdmin.value) return;
  const hours = selectedAnalysisHours();
  await guarded(async () => {
    const payload = await request("/ai-runs", { method: "POST", body: JSON.stringify({ hours, max_tool_rounds: 2, save_to_db: true }) });
    beginAnalysisProgress(payload.run_uid, hours);
    selectedRun.value = { run_uid: payload.run_uid, status: "running", hours, window_start: new Date(Date.now() - hours * 3600000).toISOString(), window_end: new Date().toISOString(), summary_text: `正在研判最近 ${hours} 小时事件。` };
    await pollRun(payload.run_uid);
  });
}

function beginAnalysisProgress(runUid, hours) {
  stopAnalysisProgress();
  analysisState.value = { running: true, runUid, hours, startedAt: Date.now(), elapsed: 0, stageIndex: 0 };
  elapsedTimer.value = window.setInterval(() => {
    const elapsed = Math.floor((Date.now() - analysisState.value.startedAt) / 1000);
    analysisState.value.elapsed = elapsed;
    analysisState.value.stageIndex = Math.min(analysisStages.length - 1, Math.floor(elapsed / 18));
  }, 1000);
}

function stopAnalysisProgress() {
  if (elapsedTimer.value) window.clearInterval(elapsedTimer.value);
  elapsedTimer.value = null;
  analysisState.value.running = false;
}

function formatElapsed(seconds) {
  const mm = String(Math.floor(seconds / 60)).padStart(2, "0");
  const ss = String(seconds % 60).padStart(2, "0");
  return `${mm}:${ss}`;
}

async function pollRun(runUid) {
  for (let i = 0; i < 160; i += 1) {
    const run = (await request(`/ai-runs/${runUid}`)).item;
    selectedRun.value = run;
    if (["success", "failed"].includes(run.status)) {
      stopAnalysisProgress();
      await loadRunFindings(runUid);
      await loadAiLatest();
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 3000));
  }
  stopAnalysisProgress();
  error.value = "AI 分析仍在运行，已停止前端等待。可稍后在 AI 分析历史中查看结果。";
  await loadRuns();
}

async function addFeedback(finding) {
  if (!isAdmin.value || !finding?.id) return;
  const comment = window.prompt("反馈说明", "");
  if (comment === null) return;
  await guarded(async () => {
    await request(`/findings/${finding.id}/feedback`, { method: "POST", body: JSON.stringify({ feedback_type: "confirmed", comment }) });
    if (selectedRun.value?.run_uid) await loadRunFindings(selectedRun.value.run_uid);
  });
}

async function copyText(value) {
  try {
    await navigator.clipboard.writeText(value);
  } catch {
    window.prompt("复制以下内容", value);
  }
}

async function loadTasks() {
  tasks.value = (await request("/report-tasks")).items || [];
}

async function createTask() {
  await guarded(async () => {
    const payload = taskPayload();
    if (editingTask.value?.id) await request(`/report-tasks/${editingTask.value.id}`, { method: "PUT", body: JSON.stringify(payload) });
    else await request("/report-tasks", { method: "POST", body: JSON.stringify(payload) });
    taskDrawerOpen.value = false;
    await loadTasks();
  });
}

async function taskAction(task, action) {
  await guarded(async () => {
    await request(`/report-tasks/${task.id}/${action}`, { method: "POST", body: "{}" });
    await loadTasks();
  });
}

async function deleteTask(task) {
  if (!isAdmin.value || !window.confirm(`确认删除任务「${task.task_name}」？`)) return;
  await guarded(async () => {
    await request(`/report-tasks/${task.id}`, { method: "DELETE" });
    await loadTasks();
  });
}

async function loadAiRules() {
  aiRules.value = (await request("/ai-analysis-rules")).items || [];
}

function resetRuleForm(row = null) {
  editingRule.value = row;
  ruleForm.value = {
    rule_name: row?.rule_name || "",
    raw_text: row?.raw_text || "",
    enabled: row?.enabled ?? true,
    priority: row?.priority ?? 50,
  };
  parsedRulePreview.value = row?.parsed_rule || null;
  ruleDrawerOpen.value = true;
}

async function previewRule() {
  if (!ruleForm.value.raw_text.trim()) {
    parsedRulePreview.value = null;
    return;
  }
  const result = await request("/ai-analysis-rules/parse", { method: "POST", body: JSON.stringify({ raw_text: ruleForm.value.raw_text }) });
  parsedRulePreview.value = result.parsed_rule;
  ruleForm.value.priority = result.parsed_rule.priority;
}

async function saveRule() {
  await guarded(async () => {
    if (!parsedRulePreview.value) await previewRule();
    if (parsedRulePreview.value?.requires_confirmation) {
      throw new Error(parsedRulePreview.value.warning || "系统无法明确理解该规则，请修改描述后重新解析。");
    }
    const payload = { ...ruleForm.value };
    if (editingRule.value?.id) await request(`/ai-analysis-rules/${editingRule.value.id}`, { method: "PUT", body: JSON.stringify(payload) });
    else await request("/ai-analysis-rules", { method: "POST", body: JSON.stringify(payload) });
    ruleDrawerOpen.value = false;
    await loadAiRules();
  });
}

async function toggleRule(row) {
  await guarded(async () => {
    await request(`/ai-analysis-rules/${row.id}/toggle`, { method: "POST", body: JSON.stringify({ enabled: !row.enabled }) });
    await loadAiRules();
  });
}

async function deleteRule(row) {
  if (!isAdmin.value || !window.confirm(`确认删除规则「${row.rule_name}」？`)) return;
  await guarded(async () => {
    await request(`/ai-analysis-rules/${row.id}`, { method: "DELETE" });
    await loadAiRules();
  });
}

async function loadDashboard() {
  await Promise.all([loadOverview(), loadRuns(), loadFaultKb(), loadQqBotStatus()]);
}

async function loadQqBotStatus() {
  try {
    qqBotStatus.value = (await request("/system/qq-bot-status")).item || { known: false, online: false, status: "unknown" };
  } catch {
    qqBotStatus.value = { known: false, online: false, status: "unknown" };
  }
}

function kbQuery(filters) {
  const params = new URLSearchParams();
  params.set("limit", filters.pageSize || 10);
  params.set("offset", ((filters.page || 1) - 1) * (filters.pageSize || 10));
  for (const key of ["q", "service", "canonical_symptom", "knowledge_value", "topic_source", "source_type"]) {
    if (filters[key]) params.set(key, filters[key]);
  }
  if (filters.include_noise) params.set("include_noise", "true");
  return params.toString();
}

async function loadFaultKb() {
  const [summary, reports, repairs, documents, topics] = await Promise.all([
    request("/fault-kb/summary"),
    request(`/fault-kb/reports?${kbQuery(kbReportFilters.value)}`),
    request(`/fault-kb/repairs?${kbQuery(kbRepairFilters.value)}`),
    request(`/fault-kb/reports?${kbQuery(kbDocumentFilters.value)}`),
    request(`/fault-kb/topics?${kbQuery(kbTopicFilters.value)}`),
  ]);
  kbSummary.value = summary;
  kbReports.value = reports.items || [];
  kbRepairs.value = repairs.items || [];
  kbDocuments.value = documents.items || [];
  kbTopics.value = topics.items || [];
  kbTotals.value = { reports: reports.total || 0, repairs: repairs.total || 0, documents: documents.total || 0, topics: topics.total || 0 };
}

async function loadAiChat() {
  await Promise.all([loadFaultKb(), loadKbChatSessions()]);
}

async function loadKbChatSessions() {
  kbChatSessions.value = (await request("/fault-kb/chat/sessions?limit=30")).items || [];
}

async function restoreKbChatSession(sessionId) {
  const result = await request(`/fault-kb/chat/sessions/${sessionId}`);
  kbCurrentSessionId.value = result.session?.id || sessionId;
  kbChatMessages.value = (result.messages || []).map((item) => ({
    role: item.role,
    content: item.content,
    evidence: item.evidence,
    model: item.model,
    provider: item.provider,
    model_error: item.model_error,
    created_at: item.created_at,
  }));
  kbShowHistory.value = false;
}

function newKbChat() {
  kbCurrentSessionId.value = null;
  kbChatMessages.value = [];
  kbChatInput.value = "";
}

async function deleteKbChatSession(sessionId) {
  await request(`/fault-kb/chat/sessions/${sessionId}`, { method: "DELETE" });
  if (kbCurrentSessionId.value === sessionId) newKbChat();
  await loadKbChatSessions();
}

function applyKbFilters(type) {
  if (type === "reports") kbReportFilters.value.page = 1;
  if (type === "repairs") kbRepairFilters.value.page = 1;
  if (type === "documents") kbDocumentFilters.value.page = 1;
  if (type === "topics") kbTopicFilters.value.page = 1;
  guarded(loadFaultKb);
}

function kbImportFormFor(type) {
  return kbImportForms.value[type] || kbImportForms.value.repair;
}

function kbImportFileList(type) {
  return kbImportFiles.value[type] || [];
}

async function importFaultKb(type) {
  if (!isAdmin.value) return;
  await guarded(async () => {
    const form = kbImportFormFor(type);
    kbImportResult.value = await request("/fault-kb/import", { method: "POST", body: JSON.stringify(form) });
    kbImportResult.value.category = type;
    await loadFaultKb();
  });
}

function onKbImportFiles(type, event) {
  kbImportFiles.value = { ...kbImportFiles.value, [type]: Array.from(event.target.files || []) };
}

async function uploadFaultKb(type) {
  const files = kbImportFileList(type);
  if (!isAdmin.value || !files.length) return;
  await guarded(async () => {
    const importForm = kbImportFormFor(type);
    const form = new FormData();
    form.append("kind", importForm.kind);
    form.append("rebuild", String(importForm.rebuild));
    form.append("rebuild_aggregates", String(importForm.rebuild_aggregates));
    form.append("drop_noise", String(importForm.drop_noise));
    files.forEach((file) => form.append("files", file, file.name));
    const response = await fetch(`${apiBase}/fault-kb/import/upload`, { method: "POST", body: form, credentials: "include" });
    const payload = await parseApiPayload(response);
    if (!response.ok) throw new Error(payload?.error?.message || payload?.error || `HTTP ${response.status}`);
    payload.category = type;
    kbImportResult.value = payload;
    await loadFaultKb();
    kbImportFiles.value = { ...kbImportFiles.value, [type]: [] };
  });
}

function kbEvidenceSummary(evidence) {
  const records = evidence?.records || [];
  const topics = evidence?.topics || [];
  const formalRecords = records.filter((item) => item.source_type === "formal_fault_report");
  const documentRecords = records.filter((item) => item.source_type === "document_kb");
  const dutyRecords = records.filter((item) => item.source_type === "duty_repair_excel");
  const formal = formalRecords.length;
  const documents = documentRecords.length;
  const duty = dutyRecords.length;
  if (!formal && !documents && !duty && !topics.length) return "";
  const parts = [];
  if (formal) parts.push(`参考故障报告 ${formal} 条`);
  if (documents) parts.push(`参考运维文档 ${documents} 条`);
  if (duty) parts.push(`参考报修记录 ${duty} 条`);
  if (topics.length) parts.push(`相关主题 ${topics.length} 个`);
  const top = formalRecords[0] || documentRecords[0] || dutyRecords[0];
  const title = top?.title || top?.fault_content || "";
  return title ? `${parts.join("，")}；首条：${title}` : parts.join("，");
}

function normalizeChatText(text) {
  return String(text || "").replaceAll("**", "").trim();
}

function revealKbAnswer(message, text) {
  const fullText = normalizeChatText(text);
  message.content = "";
  return new Promise((resolve) => {
    let index = 0;
    const step = () => {
      index = Math.min(index + 3, fullText.length);
      message.content = fullText.slice(0, index);
      if (index < fullText.length) {
        window.setTimeout(step, 16);
      } else {
        resolve();
      }
    };
    step();
  });
}

function wrapCanvasText(ctx, text, maxWidth) {
  const lines = [];
  const paragraphs = String(text || "").split(/\r?\n/);
  paragraphs.forEach((paragraph) => {
    if (!paragraph) {
      lines.push("");
      return;
    }
    let line = "";
    Array.from(paragraph).forEach((char) => {
      const next = line + char;
      if (line && ctx.measureText(next).width > maxWidth) {
        lines.push(line);
        line = char;
      } else {
        line = next;
      }
    });
    lines.push(line);
  });
  return lines;
}

function drawRoundRect(ctx, x, y, width, height, radius) {
  const r = Math.min(radius, width / 2, height / 2);
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + width, y, x + width, y + height, r);
  ctx.arcTo(x + width, y + height, x, y + height, r);
  ctx.arcTo(x, y + height, x, y, r);
  ctx.arcTo(x, y, x + width, y, r);
  ctx.closePath();
}

function downloadCanvas(canvas, filename) {
  canvas.toBlob((blob) => {
    if (!blob) return;
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.click();
    URL.revokeObjectURL(url);
  }, "image/png");
}

function exportKbChatImage() {
  if (!kbChatMessages.value.length) return;
  const width = 1280;
  const padding = 46;
  const bubbleWidth = 930;
  const bubblePadding = 18;
  const lineHeight = 28;
  const gap = 18;
  const scale = Math.min(window.devicePixelRatio || 1, 2);
  const measureCanvas = document.createElement("canvas");
  const measure = measureCanvas.getContext("2d");
  measure.font = "18px Microsoft YaHei, Arial, sans-serif";
  const rows = kbChatMessages.value.map((item) => {
    const evidence = kbEvidenceSummary(item.evidence);
    const contentLines = wrapCanvasText(measure, normalizeChatText(item.content), bubbleWidth - bubblePadding * 2);
    const evidenceLines = evidence ? wrapCanvasText(measure, evidence, bubbleWidth - bubblePadding * 2) : [];
    const height = bubblePadding * 2 + 24 + 10 + contentLines.length * lineHeight + (evidenceLines.length ? 16 + evidenceLines.length * 22 : 0);
    return { item, contentLines, evidenceLines, height };
  });
  const height = 126 + rows.reduce((sum, row) => sum + row.height + gap, 0) + 36;
  const canvas = document.createElement("canvas");
  canvas.width = width * scale;
  canvas.height = height * scale;
  const ctx = canvas.getContext("2d");
  ctx.scale(scale, scale);
  ctx.fillStyle = "#07101f";
  ctx.fillRect(0, 0, width, height);
  ctx.fillStyle = "#0e1a2d";
  ctx.fillRect(0, 0, width, 96);
  ctx.fillStyle = "#e9f2ff";
  ctx.font = "700 30px Microsoft YaHei, Arial, sans-serif";
  ctx.fillText("AI运维问答记录", padding, 48);
  ctx.fillStyle = "#8fa1bd";
  ctx.font = "15px Microsoft YaHei, Arial, sans-serif";
  ctx.fillText(`导出时间：${new Date().toLocaleString("zh-CN")}`, padding, 76);

  let y = 118;
  rows.forEach(({ item, contentLines, evidenceLines, height: bubbleHeight }) => {
    const isUser = item.role === "user";
    const x = isUser ? width - padding - bubbleWidth : padding;
    ctx.fillStyle = isUser ? "rgba(30, 70, 122, 0.86)" : "rgba(9, 22, 38, 0.92)";
    ctx.strokeStyle = isUser ? "rgba(72, 166, 255, 0.5)" : "rgba(87, 227, 179, 0.38)";
    ctx.lineWidth = 1;
    drawRoundRect(ctx, x, y, bubbleWidth, bubbleHeight, 12);
    ctx.fill();
    ctx.stroke();

    ctx.fillStyle = "#f4f8ff";
    ctx.font = "700 18px Microsoft YaHei, Arial, sans-serif";
    ctx.fillText(isUser ? "你" : "AI运维助手", x + bubblePadding, y + bubblePadding + 18);

    ctx.fillStyle = "#dce7f8";
    ctx.font = "18px Microsoft YaHei, Arial, sans-serif";
    let textY = y + bubblePadding + 52;
    contentLines.forEach((line) => {
      ctx.fillText(line, x + bubblePadding, textY);
      textY += lineHeight;
    });

    if (evidenceLines.length) {
      textY += 8;
      ctx.fillStyle = "#8fa1bd";
      ctx.font = "14px Microsoft YaHei, Arial, sans-serif";
      evidenceLines.forEach((line) => {
        ctx.fillText(line, x + bubblePadding, textY);
        textY += 22;
      });
    }
    y += bubbleHeight + gap;
  });

  downloadCanvas(canvas, `aiops-chat-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-")}.png`);
}

async function sendKbChat() {
  const content = kbChatInput.value.trim();
  if (!content || kbChatRunning.value) return;
  kbChatMessages.value.push({ role: "user", content, created_at: new Date().toISOString() });
  kbChatInput.value = "";
  kbChatRunning.value = true;
  try {
    const assistantMessage = { role: "assistant", content: "正在思考...", evidence: null, model_error: null, created_at: new Date().toISOString() };
    kbChatMessages.value.push(assistantMessage);
    const result = await request("/fault-kb/chat", { method: "POST", body: JSON.stringify({ message: content, limit: 10, session_id: kbCurrentSessionId.value }) });
    kbCurrentSessionId.value = result.session_id || kbCurrentSessionId.value;
    assistantMessage.evidence = result.evidence;
    assistantMessage.model_error = result.model_error;
    assistantMessage.created_at = result.created_at;
    await revealKbAnswer(assistantMessage, result.answer);
    await loadKbChatSessions();
  } catch (err) {
    kbChatMessages.value.push({ role: "assistant", content: `问答失败：${err.message || err}`, created_at: new Date().toISOString() });
  } finally {
    kbChatRunning.value = false;
  }
}

async function loadUsers() {
  users.value = (await request("/system/users")).items || [];
}

async function saveUser() {
  await guarded(async () => {
    const payload = { ...userForm.value };
    if (!payload.password) delete payload.password;
    if (editingUser.value?.id) await request(`/system/users/${editingUser.value.id}`, { method: "PUT", body: JSON.stringify(payload) });
    else await request("/system/users", { method: "POST", body: JSON.stringify(payload) });
    userDrawerOpen.value = false;
    await loadUsers();
  });
}

async function toggleUser(row) {
  await guarded(async () => {
    await request(`/system/users/${row.id}/toggle`, { method: "POST", body: "{}" });
    await loadUsers();
  });
}

async function deleteUser(row) {
  if (!isAdmin.value || !window.confirm(`确认删除用户「${row.username}」？`)) return;
  await guarded(async () => {
    await request(`/system/users/${row.id}`, { method: "DELETE" });
    await loadUsers();
  });
}

async function loadSettings() {
  systemSettings.value = (await request("/system/settings")).item || {};
}

async function saveSettings() {
  await guarded(async () => {
    await request("/system/settings", { method: "PUT", body: JSON.stringify(systemSettings.value) });
    await loadSettings();
  });
}

async function loadLlmInventory() {
  const [providers, models, usageKeys, bindings] = await Promise.all([
    request("/llm/providers"),
    request("/llm/models"),
    request("/llm/usage-keys"),
    request("/llm/usage-bindings"),
  ]);
  llmProviders.value = providers.items || [];
  llmModels.value = models.items || [];
  llmUsageKeys.value = usageKeys.items || [];
  llmBindings.value = bindings.items || [];
  bindingDraft.value = selectedUsageBindings.value.map((item) => ({ model_pk: String(item.model_pk), priority: item.priority, enabled: item.enabled, purpose_note: item.purpose_note || "" }));
}

function resetProviderForm(row = null) {
  editingProvider.value = row;
  providerForm.value = {
    name: row?.name || "",
    base_url: row?.base_url || "",
    api_key: "",
    api_key_env: row?.api_key_env || "",
    enabled: row?.enabled ?? true,
    timeout_seconds: row?.timeout_seconds || 60,
    remark: row?.remark || "",
  };
  providerDrawerOpen.value = true;
}

async function saveProvider() {
  await guarded(async () => {
    const payload = { ...providerForm.value };
    if (!payload.api_key) delete payload.api_key;
    if (editingProvider.value?.id) await request(`/llm/providers/${editingProvider.value.id}`, { method: "PUT", body: JSON.stringify(payload) });
    else await request("/llm/providers", { method: "POST", body: JSON.stringify(payload) });
    providerDrawerOpen.value = false;
    await loadLlmInventory();
  });
}

async function deleteProvider(row) {
  if (!isAdmin.value || !window.confirm(`确认删除供应商「${row.name}」及其模型？`)) return;
  await guarded(async () => {
    await request(`/llm/providers/${row.id}`, { method: "DELETE" });
    await loadLlmInventory();
  });
}

async function refreshProvider(row) {
  await guarded(async () => {
    await request(`/llm/providers/${row.id}/refresh`, { method: "POST", body: "{}" });
    await loadLlmInventory();
  });
}

function resetModelForm(row = null) {
  editingModel.value = row;
  modelForm.value = {
    provider_id: row?.provider_id || llmProviders.value[0]?.id || "",
    model_id: row?.model_id || "",
    display_name: row?.display_name || "",
    endpoint_type: row?.endpoint_type || "chat",
    input_types_text: Array.isArray(row?.input_types) ? row.input_types.join(",") : "text",
    output_types_text: Array.isArray(row?.output_types) ? row.output_types.join(",") : "text",
    max_context_tokens: row?.max_context_tokens || "",
    max_input_size: row?.max_input_size || "",
    max_output_tokens: row?.max_output_tokens || "",
    supports_streaming: row?.supports_streaming ?? false,
    supports_tools: row?.supports_tools ?? false,
    enabled: row?.enabled ?? true,
    remark: row?.remark || "",
  };
  modelDrawerOpen.value = true;
}

function splitCsv(value) {
  return String(value || "").split(",").map((item) => item.trim()).filter(Boolean);
}

async function saveModel() {
  await guarded(async () => {
    const payload = { ...modelForm.value, input_types: splitCsv(modelForm.value.input_types_text), output_types: splitCsv(modelForm.value.output_types_text) };
    delete payload.input_types_text;
    delete payload.output_types_text;
    if (editingModel.value?.id) await request(`/llm/models/${editingModel.value.id}`, { method: "PUT", body: JSON.stringify(payload) });
    else await request("/llm/models", { method: "POST", body: JSON.stringify(payload) });
    modelDrawerOpen.value = false;
    await loadLlmInventory();
  });
}

async function testModel(row) {
  await guarded(async () => {
    await request(`/llm/models/${row.id}/test`, { method: "POST", body: "{}" });
    await loadLlmInventory();
  });
}

async function deleteModel(row) {
  if (!isAdmin.value || !window.confirm(`确认删除模型「${row.model_id}」？`)) return;
  await guarded(async () => {
    await request(`/llm/models/${row.id}`, { method: "DELETE" });
    await loadLlmInventory();
  });
}

function resetBindingDraft() {
  bindingDraft.value = selectedUsageBindings.value.map((item) => ({ model_pk: String(item.model_pk), priority: item.priority, enabled: item.enabled, purpose_note: item.purpose_note || "" }));
}

function addBindingDraft() {
  bindingDraft.value.push({ model_pk: chatModels.value[0]?.id ? String(chatModels.value[0].id) : "", priority: (bindingDraft.value.length + 1) * 10, enabled: true, purpose_note: "" });
}

async function saveUsageBindings() {
  await guarded(async () => {
    const items = bindingDraft.value.map((item, index) => ({ ...item, priority: Number(item.priority || (index + 1) * 10), model_pk: Number(item.model_pk) })).filter((item) => item.model_pk);
    await request(`/llm/usage-bindings/${activeUsageKey.value}`, { method: "PUT", body: JSON.stringify({ items }) });
    await loadLlmInventory();
  });
}

async function loadOperationLogs() {
  operationLogs.value = (await request("/system/operation-logs?limit=100")).items || [];
}

async function loadLoginLogs() {
  loginLogs.value = (await request("/system/login-logs?limit=100")).items || [];
}

async function loadChatLogs() {
  chatLogs.value = (await request("/fault-kb/chat/logs?limit=100")).items || [];
}

async function loadQqAuditLogs() {
  const params = new URLSearchParams();
  params.set("limit", String(qqAuditFilters.value.limit || 100));
  for (const key of ["q", "event", "group_id", "user_id"]) {
    const value = String(qqAuditFilters.value[key] || "").trim();
    if (value) params.set(key, value);
  }
  const payload = await request(`/system/qq-audit-logs?${params.toString()}`);
  qqAuditLogs.value = payload.items || [];
  qqAuditSummary.value = payload.summary || {};
}

function resetQqAuditFilters() {
  qqAuditFilters.value = { q: "", event: "", group_id: "", user_id: "", limit: 100 };
  return loadQqAuditLogs();
}

function openQqAuditLog(row) {
  selectedQqAuditLog.value = row;
}

function qqAuditEventLabel(value) {
  const labels = {
    message_queued: "已入队",
    processing_started: "开始处理",
    processing_completed: "处理完成",
    processing_failed: "处理失败",
    message_rejected: "已拦截",
    message_ignored: "已忽略",
  };
  return labels[value] || value || "-";
}

function qqAuditStatusTone(row) {
  if (row?.event === "processing_completed") return "ok";
  if (row?.event === "processing_failed" || row?.event === "message_rejected") return "danger";
  return "muted";
}

async function openChatLog(row) {
  selectedChatLog.value = { ...row, loading: true, messages: row.latest_messages || [] };
  try {
    const payload = await request(`/fault-kb/chat/logs/${row.id}`);
    selectedChatLog.value = { ...(payload.session || row), messages: payload.messages || [], loading: false };
  } catch (err) {
    selectedChatLog.value = { ...row, messages: row.latest_messages || [], loading: false, error: err.message || String(err) };
  }
}

function openKbRecord(kind, row) {
  selectedKbRecord.value = { kind, row };
}

function kbRecordTitle(item) {
  if (!item?.row) return "知识库详情";
  if (item.kind === "topic") return item.row.topic_label || item.row.canonical_symptom || "主题详情";
  return item.row.knowledge_title || item.row.title || item.row.fault_content || item.row.report_file || "知识库详情";
}

function kbRecordFields(item) {
  if (!item?.row) return [];
  const row = item.row;
  if (row.source_type === "document_kb") {
    return [
      ["来源文件", row.report_file || row.source_file],
      ["知识类型", row.knowledge_kind === "table_row" ? "表格行知识" : "文档片段"],
      ["位置", [row.source_sheet, row.source_row].filter(Boolean).join(" / ")],
      ["业务", row.service],
      ["知识标题", row.knowledge_title || row.title],
      ["知识内容", row.knowledge_content || row.fault_content],
    ];
  }
  if (item.kind === "report") {
    return [
      ["日期", row.occurred_date],
      ["来源类型", row.source_type],
      ["报告/文档文件", row.report_file || row.source_file],
      ["主题", row.canonical_symptom_label || row.canonical_symptom],
      ["业务", row.service],
      ["故障现象", row.fault_content],
      ["根因", row.root_cause],
      ["处置/修复", row.fix_method],
      ["影响范围", row.impact_scope],
      ["原始摘要", row.summary],
    ];
  }
  if (item.kind === "repair") {
    return [
      ["日期", row.occurred_date],
      ["来源", [row.source_file, row.source_sheet, row.source_row].filter(Boolean).join(" / ")],
      ["业务", row.service],
      ["价值", row.knowledge_value],
      ["主题", row.canonical_symptom_label || row.canonical_symptom],
      ["报修内容", row.fault_content],
      ["处理情况", row.handling_result],
      ["责任/归属", row.responsibility],
      ["备注", row.remark],
    ];
  }
  return [
    ["主题", row.topic_label],
    ["业务", row.service],
    ["来源", row.topic_source],
    ["总数", row.total_count],
    ["正式报告", row.formal_count],
    ["可引用报修", row.reference_count],
    ["代表案例", (row.representative_cases || []).map((entry) => entry.title || entry.fault_content).filter(Boolean).join(" / ")],
  ];
}

watch(() => eventFilters.value.pageSize, () => {
  eventFilters.value.page = 1;
  if (view.value === "events") guarded(loadEvents);
});

watch(() => trapFilters.value.pageSize, () => {
  trapFilters.value.page = 1;
  if (view.value === "trap") guarded(loadTrap);
});

watch(() => kbReportFilters.value.pageSize, () => {
  kbReportFilters.value.page = 1;
  if (view.value === "kbManage" || view.value === "aiOpsKb") guarded(loadFaultKb);
});

watch(() => kbRepairFilters.value.pageSize, () => {
  kbRepairFilters.value.page = 1;
  if (view.value === "kbManage" || view.value === "aiOpsKb") guarded(loadFaultKb);
});

watch(() => kbDocumentFilters.value.pageSize, () => {
  kbDocumentFilters.value.page = 1;
  if (view.value === "kbManage" || view.value === "aiOpsKb") guarded(loadFaultKb);
});

watch(() => kbTopicFilters.value.pageSize, () => {
  kbTopicFilters.value.page = 1;
  if (view.value === "kbManage" || view.value === "aiOpsKb") guarded(loadFaultKb);
});

watch(activeUsageKey, () => {
  resetBindingDraft();
});

onMounted(async () => {
  await loadMe();
  if (user.value) await guarded(refreshCurrent);
  clockTimer.value = window.setInterval(() => {
    currentTime.value = new Date();
  }, 1000);
  refreshTimer.value = window.setInterval(() => {
    if (user.value) refreshCurrent();
  }, 30000);
});

onBeforeUnmount(() => {
  if (refreshTimer.value) window.clearInterval(refreshTimer.value);
  if (clockTimer.value) window.clearInterval(clockTimer.value);
  stopAnalysisProgress();
});
</script>

<template>
  <main v-if="!authChecked" class="boot-page">
    <div class="ai-loader"><span></span><strong>正在恢复会话</strong><small>连接 AIOps 控制台...</small></div>
  </main>

  <main v-else-if="!user" class="auth-page">
    <div class="auth-visual" aria-hidden="true">
      <span></span><span></span><span></span><span></span><span></span><span></span>
    </div>
    <section class="auth-panel">
      <div class="brand-mark">AI</div>
      <h1>JSCN AIOps</h1>
      <p>面向实时事件、Trap 拓扑关联与 AI 故障研判的运维分析界面。</p>
      <form @submit.prevent="submitAuth">
        <label>用户名<input v-model="authForm.username" autocomplete="username" /></label>
        <label>密码<input v-model="authForm.password" type="password" autocomplete="current-password" /></label>
        <button class="primary" type="submit">登录</button>
      </form>
      <p v-if="error" class="error">{{ error }}</p>
    </section>
  </main>

  <div v-else class="shell">
    <aside class="sidebar">
      <div class="brand cable-brand"><img src="/jscn-logo.png" alt="江苏有线 JSCN" /></div>
      <div class="brand aiops-brand"><span>AI</span><strong>AIOps</strong><small>智能运维分析</small></div>
      <nav>
        <section v-for="group in navGroups" :key="group.title" class="nav-group">
          <p>{{ group.title }}</p>
          <button v-for="item in group.items" :key="item.key" :class="{ active: view === item.key }" @click="switchView(item.key)">
            <span></span>{{ item.label }}
          </button>
        </section>
      </nav>
    </aside>

    <section class="workspace">
      <header :class="['topbar', { 'demo-topbar': view === 'ai' }]">
        <div v-if="view === 'ai'" class="demo-title">
          <div class="demo-title-copy">
            <div class="demo-title-line">
              <strong>宁智网维 · 城域网AI运维中枢</strong>
            </div>
            <small>江苏有线南京分公司｜城域网智能运维分析演示系统</small>
          </div>
        </div>
        <div v-else class="top-title">
          <small>{{ currentTitle }}</small>
          <strong>{{ currentTitle }}</strong>
        </div>
        <div :class="['top-actions', { 'demo-actions': view === 'ai' }]">
          <span :class="['freshness', freshnessState.tone]"><i></i>{{ freshnessState.label }} · {{ freshnessState.detail }}</span>
          <span>最后分析 {{ formatTime(latestRun?.created_at) }}</span>
          <span v-if="view === 'ai'" class="clock-readout">{{ currentClock }}</span>
          <span v-if="view === 'ai'" class="ai-core" aria-hidden="true"><b></b></span>
          <span>{{ user.username }}</span>
          <button class="ghost" @click="guarded(refreshCurrent)">刷新</button>
          <button class="ghost" @click="logout">退出登录</button>
        </div>
      </header>

      <p v-if="error" class="error">{{ error }}</p>
      <p v-if="loading && !analysisState.running" class="loading-line">正在加载最新数据...</p>

      <HomeDashboard
        v-if="view === 'home'"
        :metric-cards="dashboardMetricCards"
        :trend-rows="dashboardTrendRows"
        :runs="runs"
        :freshness-state="freshnessState"
        :qq-bot-status="qqBotStatus"
        :format-time="formatTime"
        :level-label="levelLabel"
        @open-ai="openLatestRunInDashboard"
        @open-chat="switchView('aiChat')"
        @open-run="openRun"
      />

      <section v-if="view === 'ai'" class="ai-page">
        <section v-if="aiHistoricalMode" class="history-mode-banner flow-border">
          <div>
            <span class="engine-tag">历史报告</span>
            <strong>正在查看 {{ formatTime(selectedRun?.created_at) }} 的完整 AI 分析页面</strong>
          </div>
          <button class="primary" @click="openLatestRunInDashboard">切回最新看板</button>
        </section>
        <section v-if="analysisState.running" class="analysis-progress">
          <div class="progress-line"><i :style="{ width: runningPercent }"></i></div>
          <div class="progress-copy">
            <span class="pulse-dot"></span>
            <div><strong>正在研判最近 {{ analysisState.hours }} 小时事件</strong><small>{{ analysisStages[analysisState.stageIndex] }} · 已耗时 {{ formatElapsed(analysisState.elapsed) }} · 预计需要几十秒到数分钟</small></div>
          </div>
          <div class="progress-cards">
            <article><strong>数据收集</strong><span>Syslog / Trap / alarm_events</span></article>
            <article><strong>关联研判</strong><span>设备、对象、时间窗口</span></article>
            <article><strong>报告生成</strong><span>结构化结论与建议动作</span></article>
          </div>
        </section>

        <section :class="['report-hero', 'refined', `status-${analysisDisplay.overallStatus}`]">
          <div class="hero-main">
            <div class="status-overview">
              <div class="hero-kicker">
                <span :class="['risk-tag', analysisDisplay.overallStatus]">{{ riskTagText }}</span>
                <span class="engine-tag">AI智能分析引擎</span>
              </div>
              <h1>{{ analysisDisplay.overallTitle }}</h1>
              <p>{{ analysisDisplay.overallSummary }}</p>
              <strong class="ai-conclusion">{{ analysisDisplay.aiConclusion }}</strong>
            </div>

          </div>
          <div :class="['ai-assistant', `mood-${analysisDisplay.assistantMood}`]">
            <div class="orbit orbit-a"></div>
            <div class="orbit orbit-b"></div>
            <div class="bot">
              <span class="bot-head"><i></i><i></i></span>
              <span class="bot-body"></span>
              <span class="bot-arm left"></span>
              <span class="bot-arm right"></span>
            </div>
            <div class="holo-base"></div>
            <div class="signal-lines"><i></i><i></i><i></i><i></i></div>
            <section class="assistant-card speech-bubble">
              <strong>AI助手判断</strong>
              <p>{{ analysisDisplay.assistantText }}</p>
              <small>{{ analysisDisplay.overallTitle }} · 核心风险 {{ analysisDisplay.topRisks.filter((item) => item.type !== 'rule_issue').length }} 项 · {{ analysisDisplay.recommendation }}</small>
            </section>
          </div>
        </section>

        <section class="ai-layout">
          <main class="ai-main">
            <div class="ai-tabbar">
              <div class="ai-tabs">
                <button v-for="tab in aiTabs" :key="tab.key" :class="{ active: activeAiTab === tab.key }" @click="activeAiTab = tab.key">{{ tab.label }}<b>{{ tab.count() }}</b></button>
              </div>
              <div class="tab-source-strip">
                <span v-for="item in sourceSummary" :key="item.label">{{ item.label }} <b>{{ item.value }}</b></span>
                <span>{{ freshnessState.detail }}</span>
              </div>
            </div>

            <section v-if="activeAiTab === 'must_handle'" class="analysis-panel">
              <div class="section-title"><h2>必须处理</h2><span>AI 优先给结论，证据按需展开</span></div>
              <article v-for="item in aiSections.must_handle" :key="item.id" :class="['finding-row', levelClass(item.severity)]">
                <div class="severity-rail"></div>
                <div class="finding-body">
                  <div class="finding-head"><strong>{{ item.title }}</strong><span>{{ levelLabel(item.severity) }}</span></div>
                  <p class="meta">{{ item.device }} · {{ item.object }} · {{ item.lifecycle || "状态待确认" }}</p>
                  <p class="clamp">{{ item.judgment }}</p>
                  <small>关键证据：{{ firstEvidence(item) }}</small>
                  <div class="row-actions"><span>置信度 {{ confidenceText(item.confidence) }}</span><button class="ghost" @click="openFinding(item, 'evidence')">查看证据</button><button class="ghost" @click="copyText(actionText(item.action))">复制建议</button><button class="ghost">加入关注</button></div>
                </div>
              </article>
              <div v-if="!aiSections.must_handle.length" class="empty">当前未识别到 P1/P2 必须处理项。</div>
            </section>

            <section v-if="activeAiTab === 'watch'" class="analysis-panel">
              <div class="section-title"><h2>重点关注</h2><span>仅展示判断和下一步核查方向</span></div>
              <article v-for="item in aiSections.watch" :key="item.id" class="finding-row watch">
                <div class="severity-rail"></div>
                <div class="finding-body">
                  <div class="finding-head"><strong>{{ item.title }}</strong><span>{{ text(item.severity, '关注') }}</span></div>
                  <p class="meta">{{ item.device }} · {{ item.object }}</p>
                  <p class="clamp">{{ item.judgment }}</p>
                  <small>核查建议：{{ shortText(actionText(item.action), 140) }}</small>
                  <div class="row-actions"><button class="ghost" @click="openFinding(item)">查看详情</button></div>
                </div>
              </article>
              <div v-if="!aiSections.watch.length" class="empty">暂无重点关注项。</div>
            </section>

            <section v-if="activeAiTab === 'correlation'" class="analysis-panel">
              <div class="section-title"><h2>关联分析</h2><span>去 JSON 化表达根因链路与同窗口关联</span></div>
              <article v-for="item in correlations" :key="item.id" class="correlation-row">
                <div><strong>{{ item.title }}</strong><p>{{ item.conclusion }}</p><small>{{ item.type }} · 涉及设备：{{ item.devices }} · 涉及对象：{{ item.objects }} · 证据 {{ item.evidenceCount }} 条</small></div>
                <button class="ghost" @click="openFinding({ title: item.title, judgment: item.conclusion, evidence: item.raw.evidence, impact: item.type, action: item.raw.action, missing: item.raw.missing_data, raw: item.raw }, 'evidence')">查看关联证据</button>
              </article>
              <div v-if="!correlations.length" class="ai-process">
                <div><b>1</b><strong>事件聚合</strong><p>按设备、对象、事件类型聚合当前窗口事件。</p></div>
                <div><b>2</b><strong>上下文匹配</strong><p>结合 Trap、拓扑、恢复状态与噪声候选进行交叉验证。</p></div>
                <div><b>3</b><strong>根因判断</strong><p>AI 根据证据充分度输出处理建议。</p></div>
              </div>
            </section>

            <section v-if="activeAiTab === 'recovered'" class="analysis-panel">
              <div class="section-title"><h2>已恢复</h2><span>恢复事件独立展示，避免和未恢复风险混淆</span></div>
              <article v-for="item in aiSections.recovered" :key="item.id" class="finding-row normal">
                <div class="severity-rail"></div>
                <div class="finding-body">
                  <div class="finding-head"><strong>{{ item.title }}</strong><span>recovered</span></div>
                  <p class="meta">{{ item.device }} · {{ item.object }}</p>
                  <p class="clamp">{{ item.judgment }}</p>
                  <small>观察建议：{{ shortText(actionText(item.action), 140) }}</small>
                  <div class="row-actions"><button class="ghost" @click="openFinding(item)">查看详情</button></div>
                </div>
              </article>
              <div v-if="!aiSections.recovered.length" class="empty">当前窗口暂无已恢复事件。</div>
            </section>

            <section v-if="activeAiTab === 'actions'" class="analysis-panel action-panel">
              <div class="section-title"><h2>建议动作</h2><span>按优先级推进，可复制给运维协同</span></div>
              <article v-for="(item, index) in nextActions" :key="index" class="action-row">
                <span>{{ item.priority }}</span>
                <div><strong>{{ item.title }}</strong><p>{{ item.action }}</p><small>{{ item.owner }} · {{ item.target }} · 触发原因：{{ shortText(item.reason, 120) }}</small></div>
                <div class="row-actions"><button class="ghost" @click="openFinding(item.source || item, 'evidence')">查看证据</button><button class="ghost" @click="copyText(item.action)">复制建议</button><button class="ghost">生成工单</button></div>
              </article>
              <div v-if="!nextActions.length" class="empty">暂无结构化建议动作。</div>
            </section>

            <section v-if="activeAiTab === 'rules_noise'" class="analysis-panel">
              <div class="section-title"><h2>规则与降噪</h2><span>规则问题和网络故障分开展示</span></div>
              <article v-for="item in analysisDisplay.analysisIssues" :key="item.id" class="finding-row rule-issue">
                <div class="severity-rail"></div>
                <div class="finding-body">
                  <div class="finding-head"><strong>{{ item.title }}</strong><span>{{ item.typeLabel }}</span></div>
                  <p class="clamp">{{ item.summary }}</p>
                  <small>标签：{{ item.tags.join("、") }}</small>
                  <div class="row-actions"><button class="ghost" @click="openFinding(item.source || item)">查看规则影响</button></div>
                </div>
              </article>
              <article v-for="item in aiSections.noise" :key="item.id" class="finding-row normal">
                <div class="severity-rail"></div>
                <div class="finding-body">
                  <div class="finding-head"><strong>{{ item.title }}</strong><span>noise</span></div>
                  <p class="clamp">{{ item.judgment }}</p>
                  <div class="row-actions"><button class="ghost" @click="openFinding(item)">查看详情</button><button class="ghost" disabled>抑制策略待接入</button></div>
                </div>
              </article>
              <div v-if="!aiSections.noise.length && !analysisDisplay.analysisIssues.length" class="empty">暂无规则异常或噪声过滤建议。</div>
            </section>

            <section v-if="activeAiTab === 'insufficient'" class="analysis-panel">
              <div class="section-title"><h2>证据不足</h2><span>不强行归因，列出需要补齐的数据</span></div>
              <article v-for="item in aiSections.insufficient" :key="item.id" class="finding-row major">
                <div class="severity-rail"></div>
                <div class="finding-body">
                  <div class="finding-head"><strong>{{ item.title }}</strong><span>insufficient</span></div>
                  <p class="meta">{{ item.device }} · {{ item.object }}</p>
                  <p class="clamp">{{ item.judgment }}</p>
                  <small>缺失数据：{{ shortText(text(item.missing, '需要补充现场、拓扑或 MIB 上下文'), 140) }}</small>
                  <div class="row-actions"><button class="ghost" @click="openFinding(item, 'missing')">查看缺失数据</button></div>
                </div>
              </article>
              <div v-if="!aiSections.insufficient.length" class="empty">暂无证据不足项。</div>
            </section>
          </main>

          <aside class="ai-side">
            <section class="side-panel">
              <div class="section-title"><h2>AI分析信息</h2><span>{{ analysisDisplay.overallTitle }}</span></div>
              <dl class="meta-dl">
                <div><dt>分析时间</dt><dd>{{ formatFullTime(latestRun?.created_at) }}</dd></div>
                <div><dt>分析窗口</dt><dd>{{ formatFullTime(latestRun?.window_start) }} 至 {{ formatFullTime(latestRun?.window_end) }}</dd></div>
                <div><dt>模型</dt><dd class="model-trace" :title="runModelText(latestRun)">{{ runModelText(latestRun) }}</dd></div>
                <div><dt>数据状态</dt><dd>{{ freshnessState.label }}，{{ freshnessState.detail }}</dd></div>
              </dl>
              <div class="analysis-control side-control">
                <label>时间窗口<select v-model="aiForm.selectedWindow"><option v-for="item in windowOptions" :key="item.value" :value="item.value">{{ item.label }}</option></select></label>
                <label v-if="aiForm.selectedWindow === 'custom'">自定义小时<input v-model.number="aiForm.customHours" type="number" min="1" max="168" /></label>
                <button class="primary" :disabled="!isAdmin || analysisState.running" @click="startAiRun">{{ latestRun ? "重新分析" : "开始分析" }}</button>
                <button class="ghost" :disabled="!latestRun" @click="exportMarkdownReport">导出 Markdown</button>
                <button class="ghost" @click="switchView('history')">查看历史</button>
              </div>
            </section>

            <section class="side-panel">
              <div class="section-title"><h2>恢复 / 噪声</h2><span>摘要</span></div>
              <div class="mini-metrics"><article><strong>{{ aiSections.recovered.length }}</strong><span>已恢复事件</span></article><article><strong>{{ aiSections.noise.length }}</strong><span>噪声类别</span></article></div>
              <p>{{ aiSections.noise.slice(0, 3).map((item) => item.title).join(" / ") || "暂无主要噪声类型。" }}</p>
              <details><summary>展开查看</summary><div v-for="item in aiSections.recovered.concat(aiSections.noise)" :key="item.id" class="mini-row" @click="openFinding(item)">{{ item.title }}</div></details>
            </section>

            <section class="side-panel">
              <div class="section-title"><h2>规则与降噪</h2><span>{{ analysisDisplay.ruleStats.hitCount }} 条命中</span></div>
              <div class="mini-metrics rule-stats">
                <article><strong>{{ analysisDisplay.ruleStats.anomalyCount }}</strong><span>规则异常</span></article>
                <article><strong>{{ analysisDisplay.ruleStats.suppressedCount }}</strong><span>被降噪</span></article>
                <article><strong>{{ analysisDisplay.ruleStats.upliftCount }}</strong><span>被提升</span></article>
                <article><strong>{{ userRuleHits.length }}</strong><span>命中规则</span></article>
              </div>
              <details><summary>展开查看</summary>
                <div v-for="issue in analysisDisplay.analysisIssues" :key="issue.id" class="mini-row rule-hit-row">
                  <strong>{{ issue.title }}</strong>
                  <small>{{ issue.summary }}</small>
                </div>
                <div v-for="hit in userRuleHits.slice(0, 5)" :key="`${hit.rule_id}-${hit.section}-${hit.index}`" class="mini-row rule-hit-row">
                  <strong>{{ hit.raw_text || hit.rule_name }}</strong>
                  <small>{{ text(hit.matched_target) }} · {{ ruleResultLabel(hit.action_result) }}</small>
                </div>
                <div v-if="!userRuleHits.length && !analysisDisplay.analysisIssues.length" class="empty">本次分析未命中用户规则。</div>
              </details>
            </section>
          </aside>
        </section>

        <section class="demo-slogan">
          <strong>AI驱动｜全域感知｜智能分析｜精准决策</strong>
          <span>为江苏有线南京分公司城域网稳定运行保驾护航</span>
        </section>
      </section>

      <section v-if="view === 'events'" class="events-page">
        <section class="query-panel">
          <input v-model="eventFilters.q" placeholder="搜索事件类型 / 设备 / 对象 / 摘要" @keyup.enter="applyEventFilters" />
          <select v-model="eventFilters.status"><option value="">全部状态</option><option>open</option><option>recovered</option><option>recovered_or_flapping</option><option>statistical</option></select>
          <select v-model="eventFilters.severity"><option value="">全部级别</option><option>critical</option><option>major</option><option>minor</option><option>info</option></select>
          <input v-model="eventFilters.device" list="device-list" placeholder="设备名/IP" />
          <datalist id="device-list"><option v-for="item in uniqueDevices" :key="item" :value="item" /></datalist>
          <input v-model="eventFilters.eventType" list="event-type-list" placeholder="事件类型" />
          <datalist id="event-type-list"><option v-for="item in uniqueEventTypes" :key="item" :value="item" /></datalist>
          <input v-model="eventFilters.object" placeholder="对象" />
          <select v-model.number="eventFilters.hours"><option :value="1">1小时</option><option :value="4">4小时</option><option :value="12">12小时</option><option :value="24">24小时</option><option :value="72">72小时</option><option :value="168">7天</option></select>
          <input v-model="eventFilters.start" type="datetime-local" class="time-picker" />
          <input v-model="eventFilters.end" type="datetime-local" class="time-picker" />
          <button class="primary" @click="applyEventFilters">查询</button>
          <button class="ghost" @click="clearEventFilters">清空</button>
        </section>

        <section class="table-shell">
          <div class="table-meta"><strong>{{ eventTotal }} 条事件</strong><span>按 {{ eventFilters.sort }} {{ eventFilters.order }} 排序</span><button class="ghost" @click="guarded(loadEvents)">刷新</button></div>
          <div class="table-wrap events-table">
            <table>
              <thead><tr><th @click="changeSort('severity')">级别</th><th>类型</th><th>设备</th><th>对象</th><th>状态</th><th @click="changeSort('event_count')">次数</th><th @click="changeSort('first_seen')">首次时间</th><th @click="changeSort('last_seen')">最后时间</th><th>摘要</th></tr></thead>
              <tbody>
                <tr v-for="row in events" :key="row.event_id || `${row.event_type}-${row.device_name}-${row.object_key}`" @click="selectedEvent = row">
                  <td><span :class="['severity', levelClass(row.severity_max)]">{{ levelLabel(row.severity_max || "info") }}</span></td><td>{{ text(row.event_type) }}</td><td>{{ text(row.device_name || row.device_ip) }}</td><td>{{ text(row.object_key) }}</td><td>{{ text(row.event_status) }}</td><td>{{ text(row.event_count) }}</td><td>{{ formatTime(row.first_seen) }}</td><td>{{ formatTime(row.last_seen) }}</td><td class="summary-cell" :title="row.event_summary">{{ text(row.event_summary) }}</td>
                </tr>
              </tbody>
            </table>
            <div v-if="!events.length" class="empty">当前条件下没有事件。</div>
          </div>
          <div class="pagination"><button :disabled="eventFilters.page <= 1" @click="changePage(-1)">上一页</button><span>第 {{ eventFilters.page }} / {{ totalEventPages }} 页</span><button :disabled="eventFilters.page >= totalEventPages" @click="changePage(1)">下一页</button><select v-model.number="eventFilters.pageSize"><option :value="20">20 / 页</option><option :value="50">50 / 页</option><option :value="100">100 / 页</option></select></div>
        </section>
      </section>

      <section v-if="view === 'overview'" class="overview-page">
        <section class="analysis-panel compact-overview">
          <div class="section-title"><h2>简洁概览</h2><span>入口页只保留数据新鲜度和当前窗口规模</span></div>
          <div class="overview-strip"><article v-for="item in (overview?.windows || [])" :key="item.hours"><span>{{ item.hours }}h</span><strong>{{ item.alarm_events }}</strong><small>Events</small></article></div>
          <p>最新 Syslog：{{ formatFullTime(freshness?.latest_syslog_at) }}；最新 Event：{{ formatFullTime(freshness?.latest_alarm_event_at) }}。</p>
        </section>
      </section>

      <section v-if="view === 'syslog'" class="events-page">
        <section class="query-panel syslog-query">
          <input v-model="syslogFilters.q" placeholder="搜索设备 / IP / 模块 / 事件 / 原始日志" @keyup.enter="applySyslogFilters" />
          <select v-model="syslogFilters.severity"><option value="">全部级别</option><option>critical</option><option>major</option><option>minor</option><option>info</option><option>warning</option><option>error</option></select>
          <input v-model="syslogFilters.device" placeholder="设备名/IP" @keyup.enter="applySyslogFilters" />
          <input v-model="syslogFilters.module" placeholder="模块" @keyup.enter="applySyslogFilters" />
          <input v-model="syslogFilters.event" placeholder="事件族" @keyup.enter="applySyslogFilters" />
          <select v-model.number="syslogFilters.hours"><option :value="1">1小时</option><option :value="4">4小时</option><option :value="12">12小时</option><option :value="24">24小时</option><option :value="72">72小时</option><option :value="168">7天</option></select>
          <input v-model="syslogFilters.start" type="datetime-local" class="time-picker" />
          <input v-model="syslogFilters.end" type="datetime-local" class="time-picker" />
          <button class="primary" @click="applySyslogFilters">查询</button>
          <button class="ghost" @click="clearSyslogFilters">清空</button>
        </section>
        <section class="table-shell">
          <div class="table-meta"><strong>实时 Syslog · {{ syslogTotal }} 条</strong><span>自动刷新 30 秒，支持条件过滤</span><button class="ghost" @click="guarded(loadSyslog)">刷新</button></div>
          <div class="table-wrap syslog-table-wrap"><table class="syslog-table"><thead><tr><th>时间</th><th>设备</th><th>IP</th><th>模块</th><th>级别</th><th>事件</th><th>摘要</th></tr></thead><tbody><tr v-for="row in syslogs" :key="row.timestamp + row.raw_message" @click="selectedSyslog = row"><td>{{ formatTime(row.timestamp) }}</td><td>{{ text(row.device_name) }}</td><td>{{ text(row.device_ip) }}</td><td>{{ text(row.module) }}</td><td>{{ text(row.severity) }}</td><td>{{ text(row.event_family || row.event_code) }}</td><td class="summary-cell" :title="row.raw_message">{{ text(row.raw_message) }}</td></tr></tbody></table><div v-if="!syslogs.length" class="empty">当前筛选条件下没有 Syslog 记录。</div></div>
          <div class="pagination"><button :disabled="syslogFilters.page <= 1" @click="changeSyslogPage(-1)">上一页</button><span>第 {{ syslogFilters.page }} / {{ totalSyslogPages }} 页</span><button :disabled="syslogFilters.page >= totalSyslogPages" @click="changeSyslogPage(1)">下一页</button><select v-model.number="syslogFilters.pageSize" @change="applySyslogFilters"><option :value="20">20 / 页</option><option :value="50">50 / 页</option><option :value="100">100 / 页</option><option :value="200">200 / 页</option></select></div>
        </section>
      </section>

      <section v-if="view === 'trap'" class="events-page">
        <section class="query-panel trap-query">
          <input v-model="trapFilters.q" placeholder="搜索告警名 / OID / 设备 / 对象" @keyup.enter="applyTrapFilters" />
          <input v-model="trapFilters.alarmName" placeholder="告警名称" />
          <select v-model="trapFilters.vendor"><option value="">全部厂家</option><option value="h3c">H3C</option><option value="huawei">Huawei</option><option value="unknown">Unknown</option></select>
          <select v-model="trapFilters.lifecycle"><option value="">全部生命周期</option><option value="active">发生</option><option value="recovered">恢复</option><option value="unknown">未知</option></select>
          <input v-model="trapFilters.sender" placeholder="Trap Sender" />
          <input v-model="trapFilters.device" placeholder="真实设备名/IP" />
          <input v-model="trapFilters.oid" placeholder="Trap OID" />
          <select v-model.number="trapFilters.hours"><option :value="1">1小时</option><option :value="4">4小时</option><option :value="12">12小时</option><option :value="24">24小时</option><option :value="72">72小时</option><option :value="168">7天</option></select>
          <select v-model="trapFilters.matched"><option value="">告警定义不限</option><option value="true">已匹配定义</option><option value="false">未匹配定义</option></select>
          <select v-model="trapFilters.mib"><option value="">MIB不限</option><option value="true">已翻译</option><option value="false">未翻译</option></select>
          <input v-model="trapFilters.start" type="datetime-local" class="time-picker" />
          <input v-model="trapFilters.end" type="datetime-local" class="time-picker" />
          <button class="primary" @click="applyTrapFilters">查询</button>
          <button class="ghost" @click="clearTrapFilters">清空</button>
        </section>
        <section class="table-shell">
          <div class="table-meta"><strong>Trap 管理 · {{ trapTotal }} 条</strong><span>全量分页查询，Trap Sender 不等同故障设备</span><button class="ghost" @click="guarded(loadTrap)">刷新</button></div>
          <div class="table-wrap"><table><thead><tr><th>时间</th><th>告警定义</th><th>级别</th><th>Trap Sender</th><th>真实设备</th><th>对象</th><th>链路匹配</th><th>MIB</th><th>OID</th></tr></thead><tbody><tr v-for="row in traps" :key="row.timestamp + row.raw_message" @click="selectedTrap = row"><td>{{ formatTime(row.timestamp) }}</td><td>{{ text(row.alarm_name || row.trap_oid_name) }}</td><td>{{ text(row.alarm_severity || row.alarm_lifecycle_status) }}</td><td>{{ text(row.trap_sender_ip) }}</td><td>{{ text(row.managed_device_name || row.managed_device_ip) }}</td><td>{{ text(row.managed_object_name) }}</td><td>{{ text(row.matched_link?.link_name || row.topology_correlation_status) }}</td><td>{{ row.mib_translated ? "已翻译" : "未翻译" }}</td><td>{{ text(row.trap_oid) }}</td></tr></tbody></table><div v-if="!traps.length" class="empty">当前筛选条件下没有 Trap 记录。</div></div>
          <div class="pagination"><button :disabled="trapFilters.page <= 1" @click="changeTrapPage(-1)">上一页</button><span>第 {{ trapFilters.page }} / {{ totalTrapPages }} 页</span><button :disabled="trapFilters.page >= totalTrapPages" @click="changeTrapPage(1)">下一页</button><select v-model.number="trapFilters.pageSize"><option :value="20">20 / 页</option><option :value="50">50 / 页</option><option :value="100">100 / 页</option></select></div>
        </section>
      </section>

      <section v-if="view === 'history'" class="table-shell">
        <div class="table-meta"><strong>AI 分析历史</strong><span>{{ runs.length }} 条</span></div>
        <div class="table-wrap"><table class="history-table"><thead><tr><th>时间</th><th>状态</th><th>窗口</th><th>等级</th><th>标题</th><th>模型</th><th></th></tr></thead><tbody><tr v-for="run in runs" :key="run.run_uid"><td>{{ formatTime(run.created_at) }}</td><td>{{ text(run.status) }}</td><td>{{ text(run.hours) }}h</td><td>{{ levelLabel(run.overall_level) }}</td><td>{{ text(run.overall_title) }}</td><td class="model-cell" :title="runModelText(run)">{{ runModelText(run) }}</td><td><button class="ghost" @click="openRun(run.run_uid)">查看报告</button></td></tr></tbody></table></div>
      </section>

      <section v-if="view === 'historyDetail'" class="history-detail-page">
        <section class="report-detail-hero flow-border">
          <div>
            <span class="engine-tag">历史报告快照</span>
            <h2>{{ selectedRun?.overall_title || "AI 分析报告" }}</h2>
            <p>{{ selectedRun?.summary_text || "暂无报告摘要。" }}</p>
          </div>
          <div class="detail-actions">
            <button class="ghost" @click="switchView('history')">返回历史</button>
            <button class="primary" @click="openLatestRunInDashboard">查看最新看板</button>
          </div>
        </section>
        <section class="dashboard-grid compact-detail-grid">
          <article class="metric-tile"><span>分析时间</span><strong>{{ formatTime(selectedRun?.created_at) }}</strong><small>{{ formatFullTime(selectedRun?.window_start) }} 至 {{ formatFullTime(selectedRun?.window_end) }}</small></article>
          <article class="metric-tile"><span>分析窗口</span><strong>{{ text(selectedRun?.hours, "-") }}h</strong><small>{{ text(selectedRun?.status, "-") }}</small></article>
          <article class="metric-tile"><span>风险等级</span><strong>{{ levelLabel(selectedRun?.overall_level) }}</strong><small>{{ runModelText(selectedRun) }}</small></article>
        </section>
        <section class="table-shell">
          <div class="table-meta"><strong>报告发现</strong><span>{{ findings.length }} 条</span></div>
          <div class="table-wrap"><table><thead><tr><th>类型</th><th>等级</th><th>标题</th><th>判断</th><th>操作</th></tr></thead><tbody><tr v-for="item in findings" :key="item.id || item.title"><td>{{ text(item.section || item.category) }}</td><td>{{ levelLabel(item.severity) }}</td><td>{{ text(item.title) }}</td><td>{{ shortText(item.judgment || item.reason || item.summary, 180) }}</td><td><button class="ghost" @click="openFinding(item)">详情</button></td></tr></tbody></table><div v-if="!findings.length" class="empty">这份报告暂无结构化发现。</div></div>
        </section>
      </section>

      <section v-if="view === 'tasks'" class="table-shell">
        <div class="page-heading">
          <div><h2>定时任务</h2><p>定时任务用于周期性触发 AI 分析，系统会按设定窗口读取 Syslog、Trap 和 Events 数据，生成最新 AI 研判报告。</p></div>
          <button class="primary" :disabled="!isAdmin" @click="resetTaskForm()">新建任务</button>
        </div>
        <div class="table-wrap"><table><thead><tr><th>任务名称</th><th>任务类型</th><th>启用状态</th><th>执行计划</th><th>分析窗口</th><th>最近运行时间</th><th>下次运行时间</th><th>最近结果</th><th>最近耗时</th><th>操作</th></tr></thead><tbody><tr v-for="task in tasks" :key="task.id"><td>{{ task.task_name }}</td><td>{{ taskTypeLabel(task.task_type) }}</td><td><span :class="['status-pill', task.enabled ? 'ok' : 'muted']">{{ task.enabled ? "启用" : "停用" }}</span></td><td>{{ scheduleLabel(task) }}</td><td>{{ analysisWindowLabel(task) }}</td><td>{{ formatTime(task.last_run_at) }}</td><td>{{ formatTime(task.next_run_at) }}</td><td>{{ text(task.last_status, '暂无') }}</td><td>{{ durationText(task.last_duration_ms) }}</td><td class="op-cell"><button class="ghost" :disabled="!isAdmin" @click="taskAction(task, 'run-now')">立即运行</button><button class="ghost" :disabled="!isAdmin" @click="resetTaskForm(task)">编辑</button><button class="ghost" :disabled="!isAdmin" @click="taskAction(task, task.enabled ? 'disable' : 'enable')">{{ task.enabled ? "停用" : "启用" }}</button><button class="ghost" @click="taskLogDrawer = task">查看日志</button><button class="ghost" :disabled="!isAdmin" @click="deleteTask(task)">删除</button></td></tr></tbody></table><div v-if="!tasks.length" class="empty">暂无定时任务。</div></div>
      </section>

      <section v-if="view === 'aiRules'" class="table-shell">
        <div class="page-heading">
          <div><h2>AI分析规则</h2><p>把值班经验写成自然语言规则，系统会先解析成结构化条件，再用于后续 AI 分析前的评分、降噪和报告说明。</p></div>
          <button class="primary" :disabled="!isAdmin" @click="resetRuleForm()">新增规则</button>
        </div>
        <div class="table-wrap"><table><thead><tr><th>规则内容</th><th>系统理解</th><th>类型</th><th>动作</th><th>优先级</th><th>状态</th><th>命中次数</th><th>最近命中</th><th>操作</th></tr></thead><tbody><tr v-for="row in aiRules" :key="row.id"><td>{{ row.raw_text }}</td><td>{{ ruleUnderstanding(row) }}</td><td>{{ ruleTypeLabel(row.rule_type) }}</td><td>{{ ruleActionLabel(row.action) }}</td><td>{{ row.priority }}</td><td><span :class="['status-pill', row.enabled ? 'ok' : 'muted']">{{ row.enabled ? "启用" : "停用" }}</span></td><td>{{ row.hit_count }}</td><td>{{ formatTime(row.last_hit_at) }}</td><td class="op-cell"><button class="ghost" @click="resetRuleForm(row)">查看解析</button><button class="ghost" :disabled="!isAdmin" @click="toggleRule(row)">{{ row.enabled ? "停用" : "启用" }}</button><button class="ghost" :disabled="!isAdmin" @click="deleteRule(row)">删除</button></td></tr></tbody></table><div v-if="!aiRules.length" class="empty">暂无 AI 分析规则。</div></div>
      </section>

      <section v-if="view === 'aiChat'" class="kb-page chat-only-page">
        <section class="kb-hero compact-chat-hero">
          <div>
            <span class="engine-tag">运维知识助手</span>
            <h2>AI 问答</h2>
            <p>直接提问即可，系统会自动判断是否参考故障报告和报修经验。</p>
          </div>
          <div class="chat-quick-actions">
            <button class="primary" @click="newKbChat">新对话</button>
            <button class="ghost" @click="kbShowHistory = !kbShowHistory">历史记录</button>
            <button class="ghost" :disabled="!kbChatMessages.length" @click="exportKbChatImage">导出长图</button>
          </div>
        </section>
        <section class="kb-chat-layout single">
          <div class="kb-chat-panel pure-chat">
            <div v-if="kbShowHistory" class="chat-history-strip">
              <button v-for="session in kbChatSessions" :key="session.id" :class="{ active: session.id === kbCurrentSessionId }" @click="restoreKbChatSession(session.id)">
                <strong>{{ session.title }}</strong>
                <span>{{ formatTime(session.last_message_at) }} · {{ session.message_count }} 条</span>
              </button>
              <div v-if="!kbChatSessions.length" class="empty">暂无历史对话。</div>
            </div>
            <div class="kb-chat-messages">
              <article v-for="(item, index) in kbChatMessages" :key="index" :class="['kb-message', item.role]">
                <span class="chat-avatar">{{ item.role === 'user' ? (user?.display_name || user?.username || 'U').slice(0, 1).toUpperCase() : 'AI' }}</span>
                <div class="chat-bubble">
                  <p>{{ item.content }}</p>
                  <small v-if="kbEvidenceSummary(item.evidence)">{{ kbEvidenceSummary(item.evidence) }}</small>
                  <small v-if="item.model_error">模型调用失败：{{ item.model_error }}</small>
                </div>
              </article>
              <div v-if="!kbChatMessages.length" class="empty chat-empty">可以问“用户报点8卡顿怎么处理”“宽带测速不达标怎么排查”，也可以问普通问题。</div>
            </div>
            <form class="kb-chat-input" @submit.prevent="sendKbChat">
              <textarea v-model="kbChatInput" rows="3" placeholder="输入问题，例如：宽带测速不达标怎么排查？" @keydown.shift.enter.prevent="sendKbChat"></textarea>
              <button class="primary" :disabled="kbChatRunning">{{ kbChatRunning ? "思考中" : "发送" }}</button>
            </form>
          </div>
        </section>
      </section>

      <section v-if="view === 'kbManage' || view === 'aiOpsKb'" class="kb-page">
        <section class="kb-hero">
          <div>
            <span class="engine-tag">运维知识助手</span>
            <h2>知识库管理</h2>
            <p>维护故障报告、报修流水、文件知识和主题聚合，为 AI 问答提供可靠证据。</p>
          </div>
          <div class="kb-metrics">
            <article><strong>{{ kbSummary?.formal_report_count ?? kbSummary?.formal_count ?? "-" }}</strong><span>故障报告</span></article>
            <article><strong>{{ kbSummary?.repair_count ?? "-" }}</strong><span>报修流水</span></article>
            <article><strong>{{ kbSummary?.document_count ?? "-" }}</strong><span>文件知识</span></article>
            <article><strong>{{ kbSummary?.topic_count ?? "-" }}</strong><span>经验主题</span></article>
          </div>
        </section>

        <div class="kb-tabs">
          <button :class="{ active: kbActiveTab === 'reports' }" @click="kbActiveTab = 'reports'">故障报告知识库</button>
          <button :class="{ active: kbActiveTab === 'repairs' }" @click="kbActiveTab = 'repairs'">报修知识库</button>
          <button :class="{ active: kbActiveTab === 'documents' }" @click="kbActiveTab = 'documents'">文件知识库</button>
          <button :class="{ active: kbActiveTab === 'topics' }" @click="kbActiveTab = 'topics'">主题聚合</button>
          <button :class="{ active: kbActiveTab === 'import' }" @click="kbActiveTab = 'import'">导入管理</button>
        </div>

        <section v-if="kbActiveTab === 'chat'" class="kb-chat-layout single">
          <div class="kb-chat-panel">
            <div class="section-title">
              <div><h2>AI问答</h2><span>直接提问即可，系统会自动参考故障报告和报修经验。</span></div>
              <button class="ghost" :disabled="!kbChatMessages.length" @click="exportKbChatImage">导出长图</button>
            </div>
            <div class="kb-chat-messages">
              <article v-for="(item, index) in kbChatMessages" :key="index" :class="['kb-message', item.role]">
                <strong>{{ item.role === 'user' ? '你' : 'AI运维助手' }}</strong>
                <p>{{ item.content }}</p>
                <small v-if="kbEvidenceSummary(item.evidence)">{{ kbEvidenceSummary(item.evidence) }}</small>
                <small v-if="item.model_error">模型调用失败：{{ item.model_error }}</small>
              </article>
              <div v-if="!kbChatMessages.length" class="empty">可以问“用户报点8卡顿怎么处理”“宽带测速不达标怎么排查”，也可以问普通问题。</div>
            </div>
            <form class="kb-chat-input" @submit.prevent="sendKbChat">
              <textarea v-model="kbChatInput" rows="3" placeholder="输入问题，例如：宽带测速不达标怎么排查？" @keydown.shift.enter.prevent="sendKbChat"></textarea>
              <button class="primary" :disabled="kbChatRunning">{{ kbChatRunning ? "思考中" : "发送" }}</button>
            </form>
          </div>
        </section>

        <section v-if="kbActiveTab === 'reports'" class="table-shell">
          <div class="page-heading"><div><h2>故障报告知识库</h2><p>来自 2026 重点故障排查报告，适合作为问答权威引用。</p></div><button class="ghost" @click="guarded(loadFaultKb)">刷新</button></div>
          <section class="query-panel">
            <input v-model="kbReportFilters.q" placeholder="搜索标题、现象、原因、修复方式" @keyup.enter="applyKbFilters('reports')" />
            <select v-model="kbReportFilters.service"><option value="">全部业务</option><option value="tv">电视</option><option value="broadband">宽带</option><option value="other">其他</option></select>
            <input v-model="kbReportFilters.canonical_symptom" placeholder="主题 key" @keyup.enter="applyKbFilters('reports')" />
            <button @click="applyKbFilters('reports')">查询</button>
          </section>
          <div class="table-wrap"><table class="kb-table kb-report-table"><thead><tr><th>日期</th><th>报告</th><th>主题</th><th>故障现象</th><th>根因</th><th>修复方式</th><th></th></tr></thead><tbody><tr v-for="row in kbReports" :key="row.id" @click="openKbRecord('report', row)"><td>{{ row.occurred_date }}</td><td><strong>{{ row.title }}</strong><small>{{ row.report_file }}</small></td><td>{{ row.canonical_symptom_label || row.canonical_symptom }}</td><td>{{ shortText(row.fault_content, 120) }}</td><td>{{ shortText(row.root_cause, 120) }}</td><td>{{ shortText(row.fix_method, 140) }}</td><td><button class="ghost" @click.stop="openKbRecord('report', row)">查看</button></td></tr></tbody></table><div v-if="!kbReports.length" class="empty">暂无匹配报告。</div></div>
          <div class="pager"><button class="ghost" :disabled="kbReportFilters.page <= 1" @click="kbReportFilters.page--; guarded(loadFaultKb)">上一页</button><span>{{ kbReportFilters.page }} / {{ totalKbReportPages }} · {{ kbTotals.reports }} 条</span><button class="ghost" :disabled="kbReportFilters.page >= totalKbReportPages" @click="kbReportFilters.page++; guarded(loadFaultKb)">下一页</button></div>
        </section>

        <section v-if="kbActiveTab === 'repairs'" class="table-shell">
          <div class="page-heading"><div><h2>报修知识库</h2><p>来自历史值班报修 Excel，适合做经验补充、频发问题统计和处置参考。</p></div><button class="ghost" @click="guarded(loadFaultKb)">刷新</button></div>
          <section class="query-panel">
            <input v-model="kbRepairFilters.q" placeholder="搜索报修内容或处理情况" @keyup.enter="applyKbFilters('repairs')" />
            <select v-model="kbRepairFilters.service"><option value="">全部业务</option><option value="tv">电视</option><option value="broadband">宽带</option><option value="enterprise">政企</option><option value="other">其他</option></select>
            <select v-model="kbRepairFilters.knowledge_value"><option value="">默认价值范围</option><option value="reference">reference</option><option value="aggregate_only">aggregate_only</option><option value="low_value">low_value</option><option value="noise">noise</option></select>
            <label class="inline-check"><input v-model="kbRepairFilters.include_noise" type="checkbox" />含噪声</label>
            <button @click="applyKbFilters('repairs')">查询</button>
          </section>
          <div class="table-wrap"><table class="kb-table kb-repair-table"><thead><tr><th>日期</th><th>来源</th><th>业务</th><th>价值</th><th>主题</th><th>报修内容</th><th>处理情况</th><th></th></tr></thead><tbody><tr v-for="row in kbRepairs" :key="row.id" @click="openKbRecord('repair', row)"><td>{{ row.occurred_date }}</td><td><strong>{{ row.source_file }}</strong><small>{{ row.source_sheet }} / {{ row.source_row }}</small></td><td>{{ row.service }}</td><td><span :class="['status-pill', row.knowledge_value === 'reference' ? 'ok' : row.knowledge_value === 'noise' ? 'muted' : 'warn']">{{ row.knowledge_value }}</span></td><td>{{ row.canonical_symptom_label || row.canonical_symptom }}</td><td>{{ shortText(row.fault_content, 120) }}</td><td>{{ shortText(row.handling_result, 140) }}</td><td><button class="ghost" @click.stop="openKbRecord('repair', row)">查看</button></td></tr></tbody></table><div v-if="!kbRepairs.length" class="empty">暂无匹配报修记录。</div></div>
          <div class="pager"><button class="ghost" :disabled="kbRepairFilters.page <= 1" @click="kbRepairFilters.page--; guarded(loadFaultKb)">上一页</button><span>{{ kbRepairFilters.page }} / {{ totalKbRepairPages }} · {{ kbTotals.repairs }} 条</span><button class="ghost" :disabled="kbRepairFilters.page >= totalKbRepairPages" @click="kbRepairFilters.page++; guarded(loadFaultKb)">下一页</button></div>
        </section>

        <section v-if="kbActiveTab === 'documents'" class="table-shell">
          <div class="page-heading"><div><h2>文件知识库</h2><p>来自运维手册、项目 FAQ、错误代码表等资料；按通用知识片段管理，不按故障报告解析。</p></div><button class="ghost" @click="guarded(loadFaultKb)">刷新</button></div>
          <section class="query-panel">
            <input v-model="kbDocumentFilters.q" placeholder="搜索文件标题、章节、错误码、配置项" @keyup.enter="applyKbFilters('documents')" />
            <select v-model="kbDocumentFilters.service"><option value="">全部业务</option><option value="tv">电视</option><option value="broadband">宽带</option><option value="enterprise">政企</option><option value="other">其他</option></select>
            <button @click="applyKbFilters('documents')">查询</button>
          </section>
          <div class="table-wrap"><table class="kb-table kb-report-table"><thead><tr><th>日期</th><th>来源文件</th><th>类型</th><th>知识标题</th><th>知识内容</th><th></th></tr></thead><tbody><tr v-for="row in kbDocuments" :key="row.id" @click="openKbRecord('report', row)"><td>{{ row.occurred_date }}</td><td><strong>{{ row.report_file || row.source_file }}</strong><small>{{ row.source_sheet }} / {{ row.source_row }}</small></td><td>{{ row.knowledge_kind === 'table_row' ? '表格行' : '文档片段' }}</td><td>{{ shortText(row.knowledge_title || row.title, 140) }}</td><td>{{ shortText(row.knowledge_content || row.fault_content, 260) }}</td><td><button class="ghost" @click.stop="openKbRecord('report', row)">查看</button></td></tr></tbody></table><div v-if="!kbDocuments.length" class="empty">暂无文件知识记录。</div></div>
          <div class="pager"><button class="ghost" :disabled="kbDocumentFilters.page <= 1" @click="kbDocumentFilters.page--; guarded(loadFaultKb)">上一页</button><span>{{ kbDocumentFilters.page }} / {{ totalKbDocumentPages }} · {{ kbTotals.documents }} 条</span><button class="ghost" :disabled="kbDocumentFilters.page >= totalKbDocumentPages" @click="kbDocumentFilters.page++; guarded(loadFaultKb)">下一页</button></div>
        </section>

        <section v-if="kbActiveTab === 'topics'" class="table-shell">
          <div class="page-heading"><div><h2>主题聚合</h2><p>把正式报告和值班流水归并为经验主题，帮助问答识别高频模式。</p></div><button class="ghost" @click="guarded(loadFaultKb)">刷新</button></div>
          <section class="query-panel"><input v-model="kbTopicFilters.q" placeholder="搜索主题" @keyup.enter="applyKbFilters('topics')" /><select v-model="kbTopicFilters.service"><option value="">全部业务</option><option value="tv">电视</option><option value="broadband">宽带</option><option value="other">其他</option></select><button @click="applyKbFilters('topics')">查询</button></section>
          <div class="topic-grid"><article v-for="row in kbTopics" :key="row.id" class="topic-card clickable-card" @click="openKbRecord('topic', row)"><strong>{{ row.topic_label }}</strong><p>{{ row.service }} · {{ row.canonical_symptom }} · {{ row.topic_source }}</p><div class="mini-metrics"><article><strong>{{ row.total_count }}</strong><span>总数</span></article><article><strong>{{ row.formal_count }}</strong><span>报告</span></article><article><strong>{{ row.reference_count }}</strong><span>引用</span></article></div><small>代表案例：{{ (row.representative_cases || []).slice(0, 2).map((item) => item.title).join(" / ") || "-" }}</small></article></div>
          <div class="pager"><button class="ghost" :disabled="kbTopicFilters.page <= 1" @click="kbTopicFilters.page--; guarded(loadFaultKb)">上一页</button><span>{{ kbTopicFilters.page }} / {{ totalKbTopicPages }} · {{ kbTotals.topics }} 条</span><button class="ghost" :disabled="kbTopicFilters.page >= totalKbTopicPages" @click="kbTopicFilters.page++; guarded(loadFaultKb)">下一页</button></div>
        </section>

        <section v-if="kbActiveTab === 'import'" class="analysis-panel">
          <div class="page-heading"><div><h2>导入管理</h2><p>按固定知识库类型导入，避免把报修流水、正式故障报告和运维文件混在一起。普通使用优先上传文件，服务器路径保留给后台批处理。</p></div></div>
          <div class="kb-import-grid">
            <article v-for="card in kbImportCards" :key="card.key" class="kb-import-card">
              <div class="kb-import-card-head">
                <div><span class="engine-tag">{{ card.tag }}</span><h3>{{ card.title }}</h3></div>
                <strong>{{ card.key === 'report' ? (kbSummary?.formal_report_count ?? 0) : card.key === 'repair' ? (kbSummary?.repair_count ?? 0) : (kbSummary?.document_count ?? 0) }}</strong>
              </div>
              <p>{{ card.uploadHint }}</p>
              <div class="settings-grid compact">
                <label>上传文件<input type="file" :multiple="card.multiple" :accept="card.accept" @change="onKbImportFiles(card.key, $event)" /></label>
                <label>已选文件<input :value="kbImportFileList(card.key).map((file) => file.name).join('，')" readonly :placeholder="card.placeholder" /></label>
                <label>{{ card.pathLabel }}<input v-model="kbImportForms[card.key].path" /></label>
                <label>重建原索引<select v-model="kbImportForms[card.key].rebuild"><option :value="false">否，增量 upsert</option><option :value="true">是，先删除后导入</option></select></label>
                <label>重建主题聚合<select v-model="kbImportForms[card.key].rebuild_aggregates"><option :value="true">是</option><option :value="false">否</option></select></label>
                <label v-if="card.key === 'repair'">报修导入噪声<select v-model="kbImportForms[card.key].drop_noise"><option :value="false">保留噪声用于统计</option><option :value="true">丢弃噪声</option></select></label>
              </div>
              <div class="row-actions">
                <button class="primary" :disabled="!isAdmin || !kbImportFileList(card.key).length" @click="uploadFaultKb(card.key)">上传到{{ card.title }}</button>
                <button class="ghost" :disabled="!isAdmin || !kbImportForms[card.key].path" @click="importFaultKb(card.key)">按路径导入</button>
              </div>
              <small v-if="card.key !== 'repair'">旧 .doc 需要服务器安装 LibreOffice/soffice；没有转换器时请先另存为 .docx。</small>
            </article>
          </div>
          <details v-if="kbImportResult" open><summary>最近导入结果</summary><pre>{{ JSON.stringify(kbImportResult, null, 2) }}</pre></details>
        </section>
      </section>

      <section v-if="view === 'models'" class="models-page">
        <section class="table-shell">
          <div class="page-heading">
            <div><h2>模型供应商</h2><p>管理官方 DeepSeek、省公司模型路由、本公司 OneAPI、本地 GPU 以及后续新增 OpenAI-compatible 接口。</p></div>
            <button class="primary" :disabled="!isAdmin" @click="resetProviderForm()">新增供应商</button>
          </div>
          <div class="table-wrap"><table><thead><tr><th>名称</th><th>Base URL</th><th>Key</th><th>状态</th><th>模型数</th><th>最近检查</th><th>备注</th><th>操作</th></tr></thead><tbody><tr v-for="row in llmProviders" :key="row.id"><td>{{ row.name }}</td><td>{{ row.base_url }}</td><td>{{ row.api_key_masked || row.api_key_env || "未配置" }}</td><td><span :class="['status-pill', row.status === 'ok' ? 'ok' : row.status === 'failed' ? 'danger' : 'muted']">{{ row.status }}</span></td><td>{{ row.model_count }}</td><td>{{ formatTime(row.last_checked_at) }}</td><td>{{ shortText(row.remark, 90) }}</td><td class="op-cell"><button class="ghost" :disabled="!isAdmin" @click="refreshProvider(row)">刷新模型</button><button class="ghost" :disabled="!isAdmin" @click="resetProviderForm(row)">编辑</button><button class="ghost" :disabled="!isAdmin" @click="deleteProvider(row)">删除</button></td></tr></tbody></table><div v-if="!llmProviders.length" class="empty">暂无供应商。</div></div>
        </section>

        <section class="table-shell">
          <div class="page-heading">
            <div><h2>模型清单</h2><p>刷新供应商后自动记录模型类别、输入类型、上下文大小；不完整字段可手工编辑和备注。</p></div>
            <button class="primary" :disabled="!isAdmin || !llmProviders.length" @click="resetModelForm()">新增模型</button>
          </div>
          <div class="table-wrap"><table><thead><tr><th>供应商</th><th>模型</th><th>类别</th><th>输入</th><th>上下文</th><th>状态</th><th>备注</th><th>操作</th></tr></thead><tbody><tr v-for="row in llmModels" :key="row.id"><td>{{ row.provider_name }}</td><td><strong>{{ row.display_name }}</strong><small>{{ row.model_id }}</small></td><td>{{ endpointLabel(row.endpoint_type) }}</td><td>{{ inputTypeLabel(row.input_types) }}</td><td>{{ row.max_context_tokens || row.max_input_size || "未记录" }}</td><td><span :class="['status-pill', row.status === 'ok' ? 'ok' : row.status === 'failed' ? 'danger' : 'muted']">{{ row.enabled ? row.status : "停用" }}</span></td><td>{{ shortText(row.remark || row.last_error, 100) }}</td><td class="op-cell"><button class="ghost" :disabled="!isAdmin" @click="testModel(row)">测试</button><button class="ghost" :disabled="!isAdmin" @click="resetModelForm(row)">编辑</button><button class="ghost" :disabled="!isAdmin" @click="deleteModel(row)">删除</button></td></tr></tbody></table><div v-if="!llmModels.length" class="empty">暂无模型。请先刷新供应商。</div></div>
        </section>

        <section class="analysis-panel">
          <div class="page-heading">
            <div><h2>用途绑定</h2><p>为 AIOps 定时分析、手动分析、故障知识库问答等用途配置模型顺序。运行时会按优先级依次尝试。</p></div>
            <button class="primary" :disabled="!isAdmin" @click="saveUsageBindings">保存绑定</button>
          </div>
          <div class="settings-grid usage-config">
            <label>用途<select v-model="activeUsageKey"><option v-for="item in llmUsageKeys" :key="item.key" :value="item.key">{{ item.label }}</option></select></label>
            <button class="ghost" :disabled="!isAdmin || !chatModels.length" @click="addBindingDraft">添加模型</button>
          </div>
          <div class="binding-list">
            <article v-for="(item, index) in bindingDraft" :key="index" class="binding-row">
              <label>模型<select v-model="item.model_pk"><option v-for="model in chatModels" :key="model.id" :value="String(model.id)">{{ modelOptionLabel(model) }}</option></select></label>
              <label>顺序<input v-model.number="item.priority" type="number" min="1" /></label>
              <label>启用<select v-model="item.enabled"><option :value="true">启用</option><option :value="false">停用</option></select></label>
              <label>备注<input v-model="item.purpose_note" placeholder="例如：首选 / fallback / 低成本" /></label>
              <button class="ghost" :disabled="!isAdmin" @click="bindingDraft.splice(index, 1)">移除</button>
            </article>
            <div v-if="!bindingDraft.length" class="empty">当前用途未绑定模型。</div>
          </div>
        </section>
      </section>

      <section v-if="view === 'users'" class="table-shell">
        <div class="page-heading"><div><h2>用户管理</h2><p>管理平台登录用户、角色和启用状态。</p></div><button class="primary" :disabled="!isAdmin" @click="resetUserForm()">新增用户</button></div>
        <div class="table-wrap"><table><thead><tr><th>用户名</th><th>昵称</th><th>角色</th><th>状态</th><th>最后登录时间</th><th>创建时间</th><th>操作</th></tr></thead><tbody><tr v-for="row in users" :key="row.id"><td>{{ row.username }}</td><td>{{ text(row.display_name) }}</td><td>{{ row.role }}</td><td><span :class="['status-pill', row.is_active ? 'ok' : 'muted']">{{ row.is_active ? "启用" : "禁用" }}</span></td><td>{{ formatTime(row.last_login_at) }}</td><td>{{ formatTime(row.created_at) }}</td><td class="op-cell"><button class="ghost" :disabled="!isAdmin" @click="resetUserForm(row)">编辑</button><button class="ghost" :disabled="!isAdmin" @click="toggleUser(row)">{{ row.is_active ? "禁用" : "启用" }}</button><button class="ghost" :disabled="!isAdmin" @click="resetUserForm(row)">重置密码</button><button class="ghost" :disabled="!isAdmin" @click="deleteUser(row)">删除</button></td></tr></tbody></table><div v-if="!users.length" class="empty">暂无用户。</div></div>
      </section>

      <section v-if="view === 'roles'" class="table-shell">
        <div class="page-heading"><div><h2>角色管理</h2><p>按页面菜单维度规划权限范围。后端角色权限接口待接入。</p></div><button class="primary" disabled>新增角色 · 待接入</button></div>
        <div class="empty-state"><h3>接口待接入</h3><p>当前系统后端仅区分 admin / viewer。页面已预留角色名称、描述、用户数量、权限范围和配置权限入口。</p><div class="permission-grid"><span>监控中心</span><span>AI分析</span><span>调度与策略</span><span>基础数据</span><span>系统管理</span></div></div>
      </section>

      <section v-if="view === 'settings'" class="analysis-panel settings-panel">
        <div class="page-heading"><div><h2>系统设置</h2><p>配置平台名称、默认分析窗口、刷新间隔和数据保留策略。</p></div><button class="primary" :disabled="!isAdmin" @click="saveSettings">保存设置</button></div>
        <div class="settings-grid"><label>平台名称<input v-model="systemSettings.platform_name" /></label><label>默认分析窗口<select v-model="systemSettings.default_analysis_window"><option value="4">最近 4 小时</option><option value="12">最近 12 小时</option><option value="24">最近 24 小时</option></select></label><label>默认刷新间隔（秒）<input v-model="systemSettings.default_refresh_interval" type="number" min="10" /></label><label>AI 模型名称<input v-model="systemSettings.ai_model_name" placeholder="未配置时使用后端环境变量" /></label><label>数据保留周期（天）<input v-model="systemSettings.data_retention_days" type="number" min="1" /></label><label>自动刷新<select v-model="systemSettings.auto_refresh_enabled"><option value="true">启用</option><option value="false">停用</option></select></label><label>分析完成通知<select v-model="systemSettings.analysis_done_notify_enabled"><option value="true">启用</option><option value="false">停用</option></select></label></div>
      </section>

      <section v-if="view === 'chatLogs'" class="table-shell chat-log-page">
        <div class="page-heading"><div><h2>AI问答日志</h2><p>查看用户 AI 问答会话、最近问题、回复和模型调用情况。</p></div><button class="ghost" @click="loadChatLogs">刷新</button></div>
        <div class="table-wrap"><table class="chat-log-table"><thead><tr><th>最近时间</th><th>用户</th><th>会话标题</th><th>消息数</th><th>最近内容</th><th>模型</th><th></th></tr></thead><tbody><tr v-for="row in chatLogs" :key="row.id" @click="openChatLog(row)"><td>{{ formatTime(row.last_message_at) }}</td><td>{{ text(row.username) }}</td><td>{{ text(row.title) }}</td><td>{{ text(row.message_count) }}</td><td>{{ shortText((row.latest_messages || []).map((item) => `${item.role}: ${item.content}`).join(' / '), 180) }}</td><td>{{ text((row.latest_messages || []).find((item) => item.model)?.model || '-') }}</td><td><button class="ghost" @click.stop="openChatLog(row)">详情</button></td></tr></tbody></table><div v-if="!chatLogs.length" class="empty">暂无 AI 问答日志。</div></div>
      </section>

      <section v-if="view === 'qqAuditLogs'" class="table-shell qq-audit-page">
        <div class="page-heading"><div><h2>QQ问答审计</h2><p>审计 QQ 群机器人使用情况、限流拦截、处理耗时和回复结果。</p></div><button class="ghost" @click="loadQqAuditLogs">刷新</button></div>
        <div class="qq-audit-overview">
          <article><span>最近扫描</span><strong>{{ text(qqAuditSummary.scanned, 0) }}</strong></article>
          <article><span>当前匹配</span><strong>{{ text(qqAuditSummary.matched, 0) }}</strong></article>
          <article><span>处理完成</span><strong>{{ text((qqAuditSummary.events || {}).processing_completed, 0) }}</strong></article>
          <article><span>拦截/失败</span><strong>{{ text(((qqAuditSummary.events || {}).message_rejected || 0) + ((qqAuditSummary.events || {}).processing_failed || 0), 0) }}</strong></article>
        </div>
        <section class="query-panel qq-audit-query">
          <input v-model="qqAuditFilters.q" placeholder="搜索问题 / 昵称 / 原因 / 错误" @keyup.enter="loadQqAuditLogs" />
          <input v-model="qqAuditFilters.group_id" placeholder="群号" @keyup.enter="loadQqAuditLogs" />
          <input v-model="qqAuditFilters.user_id" placeholder="用户QQ" @keyup.enter="loadQqAuditLogs" />
          <select v-model="qqAuditFilters.event"><option value="">全部事件</option><option value="message_queued">已入队</option><option value="processing_completed">处理完成</option><option value="processing_failed">处理失败</option><option value="message_rejected">限流/队列拦截</option><option value="message_ignored">忽略</option></select>
          <select v-model.number="qqAuditFilters.limit"><option :value="50">50条</option><option :value="100">100条</option><option :value="200">200条</option><option :value="500">500条</option></select>
          <button class="primary" @click="loadQqAuditLogs">筛选</button><button class="ghost" @click="resetQqAuditFilters">重置</button>
        </section>
        <div class="table-wrap"><table class="qq-audit-table"><thead><tr><th>时间</th><th>事件</th><th>群 / 用户</th><th>昵称</th><th>问题</th><th>结果摘要</th><th>耗时</th><th>状态</th><th></th></tr></thead><tbody><tr v-for="row in qqAuditLogs" :key="row.id" @click="openQqAuditLog(row)"><td>{{ formatTime(row.ts) }}</td><td>{{ qqAuditEventLabel(row.event) }}</td><td><strong>{{ text(row.group_id) }}</strong><small>{{ text(row.user_id) }}</small></td><td>{{ text(row.sender_card || row.sender_nickname) }}</td><td>{{ shortText(row.question, 120) }}</td><td>{{ shortText(row.answer_preview || row.error || row.reason, 160) }}</td><td>{{ durationText(row.duration_ms) }}</td><td><span :class="['status-pill', qqAuditStatusTone(row)]">{{ text(row.status) }}</span></td><td><button class="ghost" @click.stop="openQqAuditLog(row)">详情</button></td></tr></tbody></table><div v-if="!qqAuditLogs.length" class="empty">暂无 QQ 问答审计记录。</div></div>
      </section>

      <section v-if="view === 'operationLogs' || view === 'loginLogs'" class="table-shell">
        <div class="page-heading"><div><h2>{{ view === 'operationLogs' ? '操作日志' : '登录日志' }}</h2><p>支持搜索、时间、用户和类型筛选；登录日志持久化接口待接入。</p></div><button class="ghost" @click="view === 'operationLogs' ? loadOperationLogs() : loadLoginLogs()">刷新</button></div>
        <section class="query-panel log-query"><input placeholder="搜索用户 / 操作类型" disabled /><input type="datetime-local" disabled /><input type="datetime-local" disabled /><select disabled><option>全部类型</option></select><button disabled>筛选待接入</button></section>
        <div class="table-wrap"><table><thead><tr><th>时间</th><th>用户</th><th>类型</th><th>资源</th><th>来源 IP</th><th>详情</th></tr></thead><tbody><tr v-for="row in (view === 'operationLogs' ? operationLogs : loginLogs)" :key="row.id || row.created_at"><td>{{ formatTime(row.created_at) }}</td><td>{{ text(row.actor || row.username) }}</td><td>{{ text(row.action || row.type) }}</td><td>{{ text(row.resource_type || row.resource_id) }}</td><td>{{ text(row.client_ip) }}</td><td>{{ text(row.detail) }}</td></tr></tbody></table><div v-if="!(view === 'operationLogs' ? operationLogs : loginLogs).length" class="empty">暂无数据，接口待接入或当前没有日志记录。</div></div>
      </section>

      <section v-if="['alarmRules','analysisPolicy','devices','tags','dataSources'].includes(view)" class="table-shell">
        <div class="page-heading"><div><h2>{{ currentTitle }}</h2><p>页面框架已预留，后端接口待接入。本页不会展示模拟业务数据。</p></div><button class="primary" disabled>新增 · 待接入</button></div>
        <div class="empty-state"><h3>暂无数据</h3><p>请在后续任务中接入对应后端接口后启用新增、编辑、删除和批量操作。</p></div>
      </section>
    </section>

    <aside v-if="selectedFinding" class="drawer evidence-drawer">
      <button class="drawer-close" @click="selectedFinding = null">关闭</button>
      <h2>{{ selectedFinding.title }}</h2>
      <div class="drawer-tabs"><button :class="{active: drawerTab==='summary'}" @click="drawerTab='summary'">概要</button><button :class="{active: drawerTab==='evidence'}" @click="drawerTab='evidence'">证据</button><button :class="{active: drawerTab==='timeline'}" @click="drawerTab='timeline'">时间线</button><button :class="{active: drawerTab==='impact'}" @click="drawerTab='impact'">影响分析</button><button :class="{active: drawerTab==='actions'}" @click="drawerTab='actions'">建议动作</button><button :class="{active: drawerTab==='missing'}" @click="drawerTab='missing'">缺失数据</button><button :class="{active: drawerTab==='raw'}" @click="drawerTab='raw'">原始字段</button></div>
      <section v-if="drawerTab==='summary'"><h3>AI研判</h3><p>{{ selectedFinding.judgment || selectedFinding.reason || "-" }}</p></section>
      <section v-if="drawerTab==='evidence'"><h3>关键证据</h3><p>{{ evidenceText(selectedFinding.evidence || selectedFinding.related) }}</p></section>
      <section v-if="drawerTab==='timeline'"><h3>事件时间线</h3><p>{{ text(selectedFinding.timeline || selectedFinding.event_types, "暂无结构化时间线。") }}</p></section>
      <section v-if="drawerTab==='impact'"><h3>影响分析</h3><p>{{ selectedFinding.impact || "影响范围待结合业务拓扑确认。" }}</p></section>
      <section v-if="drawerTab==='actions'"><h3>建议动作</h3><p>{{ actionText(selectedFinding.action) }}</p></section>
      <section v-if="drawerTab==='missing'"><h3>缺失数据</h3><p>{{ text(selectedFinding.missing, "暂无缺失数据记录。") }}</p></section>
      <details v-if="drawerTab==='raw'"><summary>原始字段 / JSON</summary><pre>{{ JSON.stringify(selectedFinding.raw || selectedFinding, null, 2) }}</pre></details>
    </aside>

    <aside v-if="selectedTrap" class="drawer">
      <button class="drawer-close" @click="selectedTrap = null">关闭</button>
      <h2>{{ selectedTrap.alarm_name || selectedTrap.trap_oid_name || selectedTrap.trap_oid }}</h2>
      <section><h3>语义解析</h3><p>{{ text(selectedTrap.alarm_vendor) }} · {{ text(selectedTrap.alarm_lifecycle_status) }} · {{ selectedTrap.alarm_definition_matched ? "已匹配告警定义" : "未匹配告警定义" }}</p></section>
      <section><h3>身份字段</h3><p>Trap Sender：{{ text(selectedTrap.trap_sender_ip) }}；真实设备：{{ text(selectedTrap.managed_device_name || selectedTrap.managed_device_ip) }}；对象：{{ text(selectedTrap.managed_object_name) }}</p></section>
      <section><h3>拓扑</h3><p>{{ text(selectedTrap.matched_link?.link_name || selectedTrap.topology_correlation_status) }}</p></section>
      <details><summary>原始字段</summary><pre>{{ JSON.stringify(selectedTrap, null, 2) }}</pre></details>
    </aside>

    <aside v-if="selectedSyslog" class="drawer evidence-drawer">
      <button class="drawer-close" @click="selectedSyslog = null">关闭</button>
      <h2>{{ selectedSyslog.event_family || selectedSyslog.event_code || "Syslog 详情" }}</h2>
      <section><h3>原始日志</h3><p class="pre-wrap">{{ text(selectedSyslog.raw_message) }}</p></section>
      <dl>
        <div><dt>时间</dt><dd>{{ formatFullTime(selectedSyslog.timestamp) }}</dd></div>
        <div><dt>设备</dt><dd>{{ text(selectedSyslog.device_name || selectedSyslog.device_ip) }}</dd></div>
        <div><dt>模块/级别</dt><dd>{{ text(selectedSyslog.module) }} / {{ text(selectedSyslog.severity) }}</dd></div>
        <div><dt>事件</dt><dd>{{ text(selectedSyslog.event_family || selectedSyslog.event_code) }}</dd></div>
      </dl>
      <details><summary>原始字段</summary><pre>{{ JSON.stringify(selectedSyslog, null, 2) }}</pre></details>
    </aside>

    <aside v-if="selectedKbRecord" class="drawer evidence-drawer kb-record-drawer">
      <button class="drawer-close" @click="selectedKbRecord = null">关闭</button>
      <span class="engine-tag">知识库记录</span>
      <h2>{{ kbRecordTitle(selectedKbRecord) }}</h2>
      <dl>
        <div v-for="([label, value], index) in kbRecordFields(selectedKbRecord).filter((item) => item[1] !== undefined && item[1] !== null && item[1] !== '')" :key="`${label}-${index}`">
          <dt>{{ label }}</dt>
          <dd class="pre-wrap">{{ text(value) }}</dd>
        </div>
      </dl>
      <details><summary>原始字段</summary><pre>{{ JSON.stringify(selectedKbRecord.row, null, 2) }}</pre></details>
    </aside>

    <aside v-if="selectedChatLog" class="drawer evidence-drawer chat-log-drawer">
      <button class="drawer-close" @click="selectedChatLog = null">关闭</button>
      <span class="engine-tag">AI 问答日志</span>
      <h2>{{ selectedChatLog.title || "会话详情" }}</h2>
      <p>{{ text(selectedChatLog.username) }} · {{ formatFullTime(selectedChatLog.last_message_at) }} · {{ text(selectedChatLog.message_count) }} 条消息</p>
      <div v-if="selectedChatLog.loading" class="empty">正在加载会话详情...</div>
      <div v-else-if="selectedChatLog.error" class="error">{{ selectedChatLog.error }}</div>
      <div v-else class="log-message-list">
        <article v-for="message in (selectedChatLog.messages || [])" :key="message.id || `${message.role}-${message.created_at}`" :class="['log-message', message.role]">
          <strong>{{ message.role === 'user' ? '用户' : 'AI助手' }}</strong>
          <p class="pre-wrap">{{ message.content }}</p>
          <small>{{ formatFullTime(message.created_at) }} <span v-if="message.model">· {{ message.provider }} / {{ message.model }}</span></small>
        </article>
      </div>
    </aside>

    <aside v-if="selectedQqAuditLog" class="drawer evidence-drawer qq-audit-drawer">
      <button class="drawer-close" @click="selectedQqAuditLog = null">关闭</button>
      <span class="engine-tag">QQ 问答审计</span>
      <h2>{{ qqAuditEventLabel(selectedQqAuditLog.event) }}</h2>
      <p>{{ text(selectedQqAuditLog.group_id) }} · {{ text(selectedQqAuditLog.user_id) }} · {{ formatFullTime(selectedQqAuditLog.ts) }}</p>
      <dl>
        <div><dt>群 / 用户</dt><dd>{{ text(selectedQqAuditLog.group_id) }} / {{ text(selectedQqAuditLog.user_id) }}</dd></div>
        <div><dt>昵称</dt><dd>{{ text(selectedQqAuditLog.sender_card || selectedQqAuditLog.sender_nickname) }}</dd></div>
        <div><dt>消息 ID</dt><dd>{{ text(selectedQqAuditLog.message_id) }}</dd></div>
        <div><dt>状态</dt><dd><span :class="['status-pill', qqAuditStatusTone(selectedQqAuditLog)]">{{ text(selectedQqAuditLog.status) }}</span></dd></div>
        <div><dt>耗时</dt><dd>{{ durationText(selectedQqAuditLog.duration_ms) }}</dd></div>
        <div><dt>回复</dt><dd>{{ text(selectedQqAuditLog.answer_chars, '-') }} 字 / {{ text(selectedQqAuditLog.reply_chunks, '-') }} 段</dd></div>
      </dl>
      <section><h3>问题</h3><p class="pre-wrap">{{ text(selectedQqAuditLog.question, "无问题内容或未触发") }}</p></section>
      <section v-if="selectedQqAuditLog.answer_preview"><h3>结果摘要</h3><p class="pre-wrap">{{ selectedQqAuditLog.answer_preview }}</p></section>
      <section v-if="selectedQqAuditLog.reason || selectedQqAuditLog.error"><h3>原因 / 错误</h3><p class="pre-wrap">{{ text(selectedQqAuditLog.error || selectedQqAuditLog.reason) }}</p></section>
      <details><summary>原始字段 / JSON</summary><pre>{{ JSON.stringify(selectedQqAuditLog, null, 2) }}</pre></details>
    </aside>

    <aside v-if="taskDrawerOpen" class="drawer form-drawer">
      <button class="drawer-close" @click="taskDrawerOpen = false">关闭</button>
      <h2>{{ editingTask ? "编辑任务" : "新建任务" }}</h2>
      <form @submit.prevent="createTask">
        <label>任务名称<input v-model="taskForm.task_name" placeholder="每小时 AI 告警分析" /></label>
        <label>任务类型<select v-model="taskForm.task_type"><option value="ai_analysis">AI 告警分析</option><option value="events_aggregation" disabled>Events 聚合 · 待接入</option><option value="trap_check" disabled>Trap 解析检查 · 待接入</option><option value="data_quality" disabled>数据质量检查 · 待接入</option></select></label>
        <label>执行方式<select v-model="taskForm.schedule_type"><option value="interval">固定间隔</option><option value="daily">每天定时</option><option value="cron">Cron 表达式</option></select><small>决定任务按什么周期运行。</small></label>
        <label v-if="taskForm.schedule_type === 'interval'">固定间隔<input v-model.number="taskForm.interval_minutes" type="number" min="1" /><small>每隔 N 分钟执行一次，适合每小时、每半小时周期分析。</small></label>
        <label v-if="taskForm.schedule_type === 'daily'">每天定时<input v-model="taskForm.daily_time" type="time" /><small>适合日报、晨会报告等固定时间任务。</small></label>
        <label v-if="taskForm.schedule_type === 'cron'">Cron 表达式<input v-model="taskForm.cron_expr" placeholder="0 8 * * *" /><small>适合高级调度配置；支持常见的“分钟 小时 * * *”日级计划。</small></label>
        <label>分析窗口<select v-model="taskForm.hours_mode"><option :value="4">最近 4 小时</option><option :value="12">最近 12 小时</option><option :value="24">最近 24 小时</option><option value="custom">自定义小时数</option></select><small>决定每次 AI 分析读取多长时间范围的数据。</small></label>
        <label v-if="taskForm.hours_mode === 'custom'">自定义小时数<input v-model.number="taskForm.custom_hours" type="number" min="1" max="168" /></label>
        <label>模型用途<select v-model="taskForm.llm_usage_key"><option v-for="item in llmUsageKeys" :key="item.key" :value="item.key">{{ item.label }}</option></select><small>未指定模型列表时，按该用途绑定的模型顺序执行。</small></label>
        <section class="ordered-model-picker">
          <div class="section-title"><h3>指定模型顺序</h3><button class="ghost" type="button" :disabled="!chatModels.length" @click="addTaskModelDraft">添加模型</button></div>
          <article v-for="(row, index) in taskModelDraft" :key="`${row}-${index}`" class="ordered-model-row">
            <span>{{ index + 1 }}</span>
            <select v-model="taskModelDraft[index]"><option v-for="model in chatModels" :key="model.id" :value="String(model.id)">{{ modelOptionLabel(model) }}</option></select>
            <button class="ghost" type="button" @click="removeTaskModelDraft(index)">移除</button>
          </article>
          <small>{{ taskModelRows().length ? "运行时会按上方顺序依次尝试；全部失败才返回失败。" : "可选。不指定时按模型用途绑定的顺序执行。" }}</small>
        </section>
        <label>是否启用<select v-model="taskForm.enabled"><option :value="true">启用</option><option :value="false">停用</option></select></label>
        <label>备注<input v-model="taskForm.remark" placeholder="可选" /></label>
        <button class="primary" :disabled="!isAdmin">{{ editingTask ? "保存任务" : "创建任务" }}</button>
      </form>
    </aside>

    <aside v-if="taskLogDrawer" class="drawer">
      <button class="drawer-close" @click="taskLogDrawer = null">关闭</button>
      <h2>任务运行记录</h2>
      <section><h3>{{ taskLogDrawer.task_name }}</h3><p>最近运行时间：{{ formatFullTime(taskLogDrawer.last_run_at) }}；运行结果：{{ text(taskLogDrawer.last_status, '暂无') }}；AI Run ID：{{ text(taskLogDrawer.last_run_uid) }}</p></section>
      <div class="empty">运行记录明细接口待接入。当前仅展示任务表中的最近一次运行摘要。</div>
    </aside>

    <aside v-if="ruleDrawerOpen" class="drawer form-drawer">
      <button class="drawer-close" @click="ruleDrawerOpen = false">关闭</button>
      <h2>{{ editingRule ? "查看 / 编辑规则" : "新增 AI 分析规则" }}</h2>
      <form @submit.prevent="saveRule">
        <label>规则名称<input v-model="ruleForm.rule_name" placeholder="例如：RADIUS 降噪规则" /></label>
        <label>规则内容<textarea v-model="ruleForm.raw_text" rows="5" placeholder="例如：radius故障不用管" @blur="previewRule"></textarea></label>
        <div class="row-actions"><button class="ghost" type="button" @click="previewRule">解析规则</button></div>
        <section v-if="parsedRulePreview" class="rule-preview">
          <h3>系统理解</h3>
          <p v-if="parsedRulePreview.warning" class="error">{{ parsedRulePreview.warning }}</p>
          <p><strong>规则原文：</strong>{{ ruleForm.raw_text }}</p>
          <p>{{ ruleUnderstanding(parsedRulePreview) }}</p>
          <dl>
            <div><dt>规则类型</dt><dd>{{ ruleTypeLabel(parsedRulePreview.rule_type) }}</dd></div>
            <div><dt>动作</dt><dd>{{ ruleActionLabel(parsedRulePreview.action) }}</dd></div>
            <div><dt>目标事件族</dt><dd>{{ listText(parsedRulePreview.target_event_families) }}</dd></div>
            <div><dt>关键词</dt><dd>{{ listText(parsedRulePreview.target_keywords) }}</dd></div>
            <div><dt>目标设备</dt><dd>{{ listText(parsedRulePreview.target_devices) }}</dd></div>
            <div><dt>目标对象</dt><dd>{{ listText(parsedRulePreview.target_objects) }}</dd></div>
            <div><dt>影响范围</dt><dd>{{ text(parsedRulePreview.scope) }}</dd></div>
            <div><dt>安全例外</dt><dd>{{ listText(parsedRulePreview.safety_exceptions, "无") }}</dd></div>
            <div><dt>置信度</dt><dd>{{ confidenceText(parsedRulePreview.confidence) }}</dd></div>
          </dl>
        </section>
        <label>优先级<input v-model.number="ruleForm.priority" type="number" min="1" max="100" /></label>
        <label>状态<select v-model="ruleForm.enabled"><option :value="true">启用</option><option :value="false">停用</option></select></label>
        <button class="primary" :disabled="!isAdmin || parsedRulePreview?.requires_confirmation">保存并启用</button>
      </form>
    </aside>

    <aside v-if="providerDrawerOpen" class="drawer form-drawer">
      <button class="drawer-close" @click="providerDrawerOpen = false">关闭</button>
      <h2>{{ editingProvider ? "编辑供应商" : "新增供应商" }}</h2>
      <form @submit.prevent="saveProvider">
        <label>名称<input v-model="providerForm.name" placeholder="例如：省公司 modelrouter" /></label>
        <label>Base URL<input v-model="providerForm.base_url" placeholder="http://host:port/v1" /></label>
        <label>API Key<input v-model="providerForm.api_key" type="password" placeholder="留空则不修改；也可使用环境变量" /></label>
        <label>Key 环境变量<input v-model="providerForm.api_key_env" placeholder="例如：DEEPSEEK_API_KEY" /></label>
        <label>超时秒数<input v-model.number="providerForm.timeout_seconds" type="number" min="3" max="600" /></label>
        <label>状态<select v-model="providerForm.enabled"><option :value="true">启用</option><option :value="false">停用</option></select></label>
        <label>备注<textarea v-model="providerForm.remark" rows="4" placeholder="记录来源、费用、使用限制、联系人等"></textarea></label>
        <button class="primary" :disabled="!isAdmin">保存供应商</button>
      </form>
    </aside>

    <aside v-if="modelDrawerOpen" class="drawer form-drawer">
      <button class="drawer-close" @click="modelDrawerOpen = false">关闭</button>
      <h2>{{ editingModel ? "编辑模型" : "新增模型" }}</h2>
      <form @submit.prevent="saveModel">
        <label>供应商<select v-model="modelForm.provider_id"><option v-for="provider in llmProviders" :key="provider.id" :value="provider.id">{{ provider.name }}</option></select></label>
        <label>模型 ID<input v-model="modelForm.model_id" placeholder="例如：deepseek-v4-pro" /></label>
        <label>显示名称<input v-model="modelForm.display_name" placeholder="可选" /></label>
        <label>类别<select v-model="modelForm.endpoint_type"><option value="chat">对话</option><option value="embeddings">向量</option><option value="rerank">重排序</option></select></label>
        <label>输入类型<input v-model="modelForm.input_types_text" placeholder="text,image" /></label>
        <label>输出类型<input v-model="modelForm.output_types_text" placeholder="text" /></label>
        <label>上下文 Token<input v-model.number="modelForm.max_context_tokens" type="number" min="0" /></label>
        <label>输入大小<input v-model="modelForm.max_input_size" placeholder="例如：1 image / 10MB / 2048 tokens" /></label>
        <label>最大输出 Token<input v-model.number="modelForm.max_output_tokens" type="number" min="0" /></label>
        <label>流式输出<select v-model="modelForm.supports_streaming"><option :value="true">支持</option><option :value="false">未知/不支持</option></select></label>
        <label>工具调用<select v-model="modelForm.supports_tools"><option :value="true">支持</option><option :value="false">未知/不支持</option></select></label>
        <label>状态<select v-model="modelForm.enabled"><option :value="true">启用</option><option :value="false">停用</option></select></label>
        <label>备注<textarea v-model="modelForm.remark" rows="4" placeholder="记录适用场景、费用、质量、限制等"></textarea></label>
        <button class="primary" :disabled="!isAdmin">保存模型</button>
      </form>
    </aside>

    <aside v-if="userDrawerOpen" class="drawer form-drawer">
      <button class="drawer-close" @click="userDrawerOpen = false">关闭</button>
      <h2>{{ editingUser ? "编辑用户" : "新增用户" }}</h2>
      <form @submit.prevent="saveUser">
        <label>用户名<input v-model="userForm.username" :disabled="!!editingUser" /></label>
        <label>昵称<input v-model="userForm.display_name" /></label>
        <label>{{ editingUser ? "重置密码" : "密码" }}<input v-model="userForm.password" type="password" placeholder="至少 8 位；编辑时留空则不修改" /></label>
        <label>角色<select v-model="userForm.role"><option value="viewer">viewer</option><option value="admin">admin</option></select></label>
        <label>状态<select v-model="userForm.is_active"><option :value="true">启用</option><option :value="false">禁用</option></select></label>
        <label>备注<input v-model="userForm.remark" placeholder="页面预留，后端暂未持久化" /></label>
        <button class="primary" :disabled="!isAdmin">保存</button>
      </form>
    </aside>

    <aside v-if="selectedQuality" class="drawer evidence-drawer">
      <button class="drawer-close" @click="selectedQuality = null">关闭</button>
      <h2>{{ selectedQuality.label }}</h2>
      <p>{{ selectedQuality.detail }}</p>
      <section><h3>当前数量</h3><p>{{ selectedQuality.value }}</p></section>
      <details><summary>数据质量原始字段</summary><pre>{{ JSON.stringify(selectedQuality.raw || {}, null, 2) }}</pre></details>
    </aside>

    <aside v-if="selectedEvent" class="drawer">
      <button class="drawer-close" @click="selectedEvent = null">关闭</button>
      <h2>{{ selectedEvent.event_type }}</h2>
      <p>{{ selectedEvent.event_summary || "暂无完整摘要。" }}</p>
      <dl><div><dt>设备/对象</dt><dd>{{ text(selectedEvent.device_name || selectedEvent.device_ip) }} · {{ text(selectedEvent.object_key) }}</dd></div><div><dt>状态演化</dt><dd>{{ text(selectedEvent.event_status) }}，累计 {{ text(selectedEvent.event_count) }} 次</dd></div><div><dt>首次 / 最后</dt><dd>{{ formatFullTime(selectedEvent.first_seen) }} / {{ formatFullTime(selectedEvent.last_seen) }}</dd></div><div><dt>级别</dt><dd>{{ text(selectedEvent.severity_max) }}</dd></div></dl>
      <details><summary>原始字段</summary><pre>{{ JSON.stringify(selectedEvent, null, 2) }}</pre></details>
    </aside>
  </div>
</template>

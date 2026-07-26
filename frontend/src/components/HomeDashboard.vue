<script setup>
import { computed } from "vue";

const props = defineProps({
  metricCards: { type: Array, default: () => [] },
  trendRows: { type: Array, default: () => [] },
  runs: { type: Array, default: () => [] },
  freshnessState: { type: Object, default: () => ({ label: "-", detail: "-", tone: "muted" }) },
  qqBotStatus: { type: Object, default: () => ({ known: false, online: false, status: "unknown" }) },
  formatTime: { type: Function, required: true },
  levelLabel: { type: Function, required: true },
});

const emit = defineEmits(["openAi", "openChat", "openRun"]);

const signalRows = computed(() => props.trendRows.slice(0, 4));
const latestRuns = computed(() => props.runs.slice(0, 6));
const qqBotTone = computed(() => (props.qqBotStatus?.online ? "ok" : props.qqBotStatus?.known ? "danger" : "muted"));
const qqBotLabel = computed(() => (props.qqBotStatus?.online ? "在线" : props.qqBotStatus?.known ? "离线" : "未知"));
</script>

<template>
  <section class="home-dashboard command-center">
    <section class="command-hero flow-border">
      <div class="hero-copy">
        <span class="eyebrow">JSCN AIOps · 智能态势中枢</span>
        <h1>实时感知、智能研判、知识闭环</h1>
        <p>汇聚 ELK 事件流、AI 分析结果、故障知识库和问答记录，形成从发现到处置的统一运维入口。</p>
        <div class="home-actions">
          <button class="primary" @click="emit('openAi')">进入运维看板</button>
          <button class="robot-action" @click="emit('openChat')"><span>AI</span><b>打开 AI 问答</b></button>
        </div>
      </div>

      <div class="command-visual" aria-hidden="true">
        <div class="ai-halo"></div>
        <div class="robot-core">
          <span class="robot-eye"></span>
          <span class="robot-eye"></span>
          <i>AI</i>
        </div>
        <div class="topology topology-a"><b></b><b></b><b></b></div>
        <div class="topology topology-b"><b></b><b></b><b></b></div>
        <div class="link-stream stream-a"></div>
        <div class="link-stream stream-b"></div>
        <div class="link-stream stream-c"></div>
      </div>
    </section>

    <section class="metric-ribbon">
      <article v-for="item in metricCards" :key="item.label" class="metric-tile digital-tile">
        <span>{{ item.label }}</span>
        <strong>{{ item.value }}</strong>
        <small>{{ item.hint }}</small>
      </article>
    </section>

    <section class="command-lower">
      <article class="dashboard-panel access-intel flow-border">
        <div class="section-title">
          <h2>数据接入强度</h2>
          <span>近 1h / 3h / 24h</span>
        </div>
        <div class="access-copy">
          <strong>用于判断 ELK 采集压力和事件聚合强度</strong>
          <span>Syslog 是原始日志接入量，Trap 是设备原始告警，Events 是聚合后的可研判事件，不等同于故障数量。</span>
        </div>
        <div class="access-chart" aria-label="ELK access trend chart">
          <div v-for="row in signalRows.slice(0, 3)" :key="row.label" class="access-column">
            <div class="bar-stack">
              <i class="bar syslog" :style="{ height: row.syslogWidth }"><em>Syslog {{ row.syslog }}</em></i>
              <i class="bar events" :style="{ height: row.eventWidth }"><em>Events {{ row.events }}</em></i>
              <i class="bar trap" :style="{ height: row.trapWidth }"><em>Trap {{ row.trap }}</em></i>
            </div>
            <b>{{ row.label }}</b>
          </div>
        </div>
        <div class="access-legend">
          <span><i class="syslog"></i>Syslog 原始日志</span>
          <span><i class="events"></i>Events 聚合事件</span>
          <span><i class="trap"></i>Trap 设备告警</span>
        </div>
      </article>

      <article class="dashboard-panel operation-pulse">
        <div class="section-title">
          <h2>运行状态</h2>
          <span>{{ freshnessState.detail }}</span>
        </div>
        <div :class="['status-orb', freshnessState.tone]"><i></i><strong>{{ freshnessState.label }}</strong></div>
        <div class="pulse-checks">
          <span><i></i> ELK 接入</span>
          <span><i></i> AI 研判</span>
          <span><i></i> 知识问答</span>
        </div>
      </article>

      <article class="dashboard-panel qq-bot-panel">
        <div class="section-title">
          <h2>QQ机器人</h2>
          <span>{{ qqBotStatus?.ts ? formatTime(qqBotStatus.ts) : "等待检测" }}</span>
        </div>
        <div :class="['qq-bot-state', qqBotTone]">
          <i></i>
          <div>
            <strong>{{ qqBotLabel }}</strong>
            <span>OneBot {{ qqBotStatus?.onebot_ok ? "正常" : "异常或未连接" }}</span>
          </div>
        </div>
        <div class="qq-bot-meta">
          <span>邮件告警：{{ qqBotStatus?.email_enabled ? "已启用" : "未启用" }}</span>
          <span>NapCat：{{ qqBotStatus?.napcat_login?.is_login ? "已登录" : "需确认" }}</span>
        </div>
        <a v-if="!qqBotStatus?.online && qqBotStatus?.login_url" class="ghost-link" :href="qqBotStatus.login_url" target="_blank" rel="noreferrer">打开登录页</a>
      </article>

      <article class="dashboard-panel latest-runs">
        <div class="section-title">
          <h2>最新研判</h2>
          <span>{{ runs.length }} 条记录</span>
        </div>
        <div class="mini-run-list">
          <button v-for="run in latestRuns" :key="run.run_uid" @click="emit('openRun', run.run_uid)">
            <strong>{{ run.overall_title || "AI 分析报告" }}</strong>
            <span>{{ formatTime(run.created_at) }} · {{ levelLabel(run.overall_level) }}</span>
          </button>
          <div v-if="!latestRuns.length" class="empty">暂无 AI 分析历史。</div>
        </div>
      </article>
    </section>
  </section>
</template>

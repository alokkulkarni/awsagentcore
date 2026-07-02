/**
 * ContactFlowGraph — visualises the block-by-block journey of an Amazon Connect contact.
 *
 * Option B  – ReactFlow node graph: every block the call touched is a card-node, connected
 *             by directed edges labelled with the branch outcome.  Colour-coded by block type.
 *             Clicking a node opens a side detail panel.  Live mode pulses the latest node.
 *
 * Option C  – Funnel / drop-off chart: aggregate Recharts horizontal bar chart showing how
 *             many contacts (out of the total for that flow) passed through each block.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  Handle,
  Position,
  useNodesState,
  useEdgesState,
  useReactFlow,
  ReactFlowProvider,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import * as dagre from '@dagrejs/dagre';
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Cell,
  LabelList,
} from 'recharts';
import {
  Activity,
  AlertCircle,
  ArrowRight,
  BarChart2,
  Box,
  Clock,
  Edit3,
  GitBranch,
  Layers,
  Mic,
  Network,
  Phone,
  PhoneOff,
  RefreshCw,
  Tag,
  Users,
  Video,
  VideoOff,
  Volume2,
  X,
  Zap,
} from 'lucide-react';
import { getContactFlowEvents, getContactFunnel } from '../services/api';

// ── Block-type definitions ────────────────────────────────────────────────────

const BLOCK_DEF = {
  // ── Play / Prompt ──────────────────────────────────────────────────────────
  PlayPrompt:                  { color: '#38bdf8', icon: Volume2,    label: 'Play Prompt'       },
  MessageParticipant:          { color: '#38bdf8', icon: Volume2,    label: 'Message'           },
  // ── Input / Branch ────────────────────────────────────────────────────────
  GetCustomerInput:            { color: '#818cf8', icon: Mic,        label: 'Get Input'         },
  GetUserInput:                { color: '#818cf8', icon: Mic,        label: 'Get Input'         },
  // ── Conditions ────────────────────────────────────────────────────────────
  CheckContactAttributes:      { color: '#fbbf24', icon: GitBranch, label: 'Check Condition'   },
  CheckAttribute:              { color: '#fbbf24', icon: GitBranch, label: 'Check Condition'   },
  CheckHoursOfOperation:       { color: '#fbbf24', icon: Clock,      label: 'Check Hours'       },
  CheckStaffingLevel:          { color: '#fbbf24', icon: Users,      label: 'Check Staffing'    },
  Branch:                      { color: '#fbbf24', icon: GitBranch, label: 'Branch'             },
  // ── Lambda / External ─────────────────────────────────────────────────────
  InvokeExternalResource:      { color: '#c084fc', icon: Zap,        label: 'Lambda / API'      },
  InvokeLambdaFunction:        { color: '#c084fc', icon: Zap,        label: 'Lambda Call'       },
  // ── Attributes ────────────────────────────────────────────────────────────
  SetContactAttributes:        { color: '#34d399', icon: Tag,        label: 'Set Attribute'     },
  SetAttributes:               { color: '#34d399', icon: Tag,        label: 'Set Attribute'     },
  UpdateContactAttributes:     { color: '#34d399', icon: Edit3,      label: 'Update Attributes' },
  // ── Queue / Transfer ──────────────────────────────────────────────────────
  TransferToQueue:             { color: '#fb923c', icon: ArrowRight, label: 'Transfer to Queue' },
  TransferContact:             { color: '#fb923c', icon: ArrowRight, label: 'Transfer'          },
  Transfer:                    { color: '#fb923c', icon: ArrowRight, label: 'Transfer'          },
  SetQueue:                    { color: '#fb923c', icon: Layers,     label: 'Set Queue'         },
  // ── Disconnect ────────────────────────────────────────────────────────────
  DisconnectParticipant:       { color: '#fb7185', icon: PhoneOff,   label: 'Disconnect'        },
  Disconnect:                  { color: '#fb7185', icon: PhoneOff,   label: 'Disconnect'        },
  EndFlowModuleExecution:      { color: '#fb7185', icon: PhoneOff,   label: 'End Module'        },
  // ── Recording ─────────────────────────────────────────────────────────────
  StartContactRecording:       { color: '#a78bfa', icon: Video,      label: 'Start Recording'   },
  StopContactRecording:        { color: '#a78bfa', icon: VideoOff,   label: 'Stop Recording'    },
  SetRecordingBehavior:        { color: '#a78bfa', icon: Video,      label: 'Recording'         },
  // ── Queue metrics / Wait ──────────────────────────────────────────────────
  GetQueueMetrics:             { color: '#4ade80', icon: BarChart2,  label: 'Queue Metrics'     },
  CheckQueueStatus:            { color: '#4ade80', icon: BarChart2,  label: 'Check Queue'       },
  Loop:                        { color: '#22d3ee', icon: RefreshCw,  label: 'Loop'              },
  Wait:                        { color: '#94a3b8', icon: Clock,      label: 'Wait'              },
  WaitForCustomerResponse:     { color: '#94a3b8', icon: Clock,      label: 'Wait Response'     },
  // ── Callback ──────────────────────────────────────────────────────────────
  CreateCallback:              { color: '#f472b6', icon: Phone,      label: 'Create Callback'   },
  // ── Flow / Module ─────────────────────────────────────────────────────────
  InvokeFlowModule:            { color: '#67e8f9', icon: Layers,     label: 'Sub-flow'          },
  SetEventHook:                { color: '#67e8f9', icon: Layers,     label: 'Event Hook'        },
  // ── Fallback ──────────────────────────────────────────────────────────────
  _default:                    { color: '#94a3b8', icon: Box,        label: 'Block'             },
};

const blockDef = (type) => BLOCK_DEF[type] || BLOCK_DEF._default;

// ── Helpers ───────────────────────────────────────────────────────────────────

const fmtElapsed = (ms) => {
  if (!ms && ms !== 0) return '';
  if (ms < 1000) return `+${ms}ms`;
  if (ms < 60000) return `+${(ms / 1000).toFixed(1)}s`;
  return `+${Math.floor(ms / 60000)}m ${Math.round((ms % 60000) / 1000)}s`;
};

const fmtDuration = (ms) => {
  if (!ms) return '';
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60000)}m ${Math.round((ms % 60000) / 1000)}s`;
};

const NODE_W = 250;
const NODE_H = 96;

// ── Dagre layout ──────────────────────────────────────────────────────────────

function applyDagreLayout(rawNodes, rawEdges) {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: 'LR', nodesep: 40, ranksep: 100 });
  g.setDefaultEdgeLabel(() => ({}));

  rawNodes.forEach((n) => g.setNode(n.id, { width: NODE_W, height: NODE_H }));
  rawEdges.forEach((e) => g.setEdge(e.source, e.target));
  dagre.layout(g);

  return rawNodes.map((n) => {
    const pos = g.node(n.id);
    return { ...n, position: { x: pos.x - NODE_W / 2, y: pos.y - NODE_H / 2 } };
  });
}

// ── Custom ReactFlow node ─────────────────────────────────────────────────────

function FlowBlockNode({ data }) {
  const { event, isLatest, isSelected, onClick } = data;
  const def = blockDef(event.block_type);
  const Icon = def.icon;

  const borderColor = isSelected ? def.color : def.color + '60';
  const bg          = def.color + '14';

  return (
    <div
      onClick={() => onClick(event)}
      className="rounded-xl cursor-pointer transition-all select-none"
      style={{
        width:       NODE_W,
        height:      NODE_H,
        border:      `1.5px solid ${borderColor}`,
        background:  bg,
        boxShadow:   isSelected ? `0 0 0 2px ${def.color}80` : undefined,
      }}
    >
      <Handle
        type="target"
        position={Position.Left}
        style={{ background: def.color, border: 'none', width: 8, height: 8 }}
      />

      {/* Header bar */}
      <div
        className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-t-xl"
        style={{ background: def.color + '2a' }}
      >
        <Icon size={11} style={{ color: def.color, flexShrink: 0 }} />
        <span className="text-[9px] font-semibold uppercase tracking-widest truncate" style={{ color: def.color }}>
          {def.label}
        </span>
        <span className="ml-auto text-[9px] text-slate-600 dark:text-slate-500 shrink-0">{fmtElapsed(event.elapsed_ms)}</span>
        {isLatest && (
          <span
            className="ml-1 h-2 w-2 rounded-full shrink-0 animate-pulse"
            style={{ background: def.color }}
          />
        )}
      </div>

      {/* Body */}
      <div className="px-2.5 py-2 flex flex-col gap-0.5">
        <p className="text-[11px] font-semibold text-slate-900 dark:text-slate-100 truncate leading-tight">
          {event.block_name}
        </p>
        <div className="flex items-center gap-2 mt-0.5">
          {event.outcome && event.outcome !== 'Success' && event.outcome !== 'Successfully invoked' && (
            <span
              className="rounded-full px-1.5 py-0.5 text-[9px] font-medium truncate max-w-[140px]"
              style={{ background: def.color + '25', color: def.color }}
            >
              → {event.outcome}
            </span>
          )}
          {event.duration_ms > 0 && (
            <span className="text-[9px] text-slate-600 dark:text-slate-500 ml-auto shrink-0">
              {fmtDuration(event.duration_ms)}
            </span>
          )}
        </div>
        {event.flow_name && (
          <span className="text-[9px] text-slate-600 truncate">{event.flow_name}</span>
        )}
      </div>

      <Handle
        type="source"
        position={Position.Right}
        style={{ background: def.color, border: 'none', width: 8, height: 8 }}
      />
    </div>
  );
}

const nodeTypes = { flowBlock: FlowBlockNode };

// ── Build graph from events ───────────────────────────────────────────────────

function buildGraph(events, selectedId, onNodeClick, latestEventId) {
  const rawNodes = events.map((evt) => ({
    id:   evt.event_id,
    type: 'flowBlock',
    data: {
      event:      evt,
      isLatest:   evt.event_id === latestEventId,
      isSelected: evt.event_id === selectedId,
      onClick:    onNodeClick,
    },
    position: { x: 0, y: 0 }, // overridden by dagre
  }));

  const rawEdges = events.slice(1).map((evt, i) => {
    const prev = events[i];
    const label = prev.outcome && prev.outcome !== 'Success' && prev.outcome !== 'Successfully invoked'
      ? prev.outcome
      : '';
    const def = blockDef(prev.block_type);
    return {
      id:              `e-${prev.event_id}-${evt.event_id}`,
      source:          prev.event_id,
      target:          evt.event_id,
      label,
      labelStyle:      { fill: '#94a3b8', fontSize: 9, fontWeight: 500 },
      labelBgStyle:    { fill: '#1e293b', fillOpacity: 0.85 },
      labelBgPadding:  [3, 5],
      style:           { stroke: def.color + '80', strokeWidth: 1.5 },
      animated:        evt.event_id === latestEventId,
    };
  });

  const positionedNodes = applyDagreLayout(rawNodes, rawEdges);
  return { nodes: positionedNodes, edges: rawEdges };
}

// ── Detail side panel ─────────────────────────────────────────────────────────

function EventDetailPanel({ event, onClose }) {
  if (!event) return null;
  const def = blockDef(event.block_type);
  const Icon = def.icon;
  const params = event.parameters || {};
  const hasParams = Object.keys(params).length > 0;

  return (
    <div className="flex flex-col h-full overflow-auto bg-white dark:bg-slate-900 border-l border-slate-300 dark:border-slate-700 w-72 shrink-0">
      {/* header */}
      <div
        className="flex items-center justify-between px-4 py-3 border-b border-slate-300 dark:border-slate-700"
        style={{ borderBottom: `2px solid ${def.color}40` }}
      >
        <div className="flex items-center gap-2">
          <Icon size={14} style={{ color: def.color }} />
          <span className="text-xs font-semibold text-slate-800 dark:text-slate-200">{event.block_name}</span>
        </div>
        <button
          onClick={onClose}
          className="text-slate-600 dark:text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 p-0.5 rounded"
        >
          <X size={13} />
        </button>
      </div>

      <div className="px-4 py-3 space-y-3 text-xs">
        <Row label="Block Type"  value={event.block_type} color={def.color} />
        <Row label="Flow"        value={event.flow_name || '—'} />
        <Row label="Elapsed"     value={fmtElapsed(event.elapsed_ms)} />
        <Row label="Duration"    value={fmtDuration(event.duration_ms) || '—'} />
        <Row label="Outcome"     value={event.outcome || '—'} />
        <Row label="Block ID"    value={event.block_id ? event.block_id.slice(-12) : '—'} mono />
        <Row label="Log Group"   value={event.log_group || '—'} mono small />

        {hasParams && (
          <div>
            <p className="text-slate-600 dark:text-slate-500 text-[10px] font-semibold uppercase tracking-wide mb-1.5">Parameters</p>
            <div className="rounded-lg bg-slate-100 dark:bg-slate-800 p-2 space-y-1">
              {Object.entries(params).map(([k, v]) => (
                <div key={k} className="flex gap-2">
                  <span className="text-slate-600 dark:text-slate-500 shrink-0">{k}:</span>
                  <span className="text-slate-700 dark:text-slate-300 truncate">{String(v).slice(0, 80)}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function Row({ label, value, color, mono, small }) {
  return (
    <div className="flex justify-between gap-2">
      <span className="text-slate-600 dark:text-slate-500 shrink-0">{label}</span>
      <span
        className={`text-right truncate ${mono ? 'font-mono' : ''} ${small ? 'text-[10px]' : ''}`}
        style={{ color: color || '#cbd5e1' }}
      >
        {value}
      </span>
    </div>
  );
}

// ── Option B: ReactFlow graph ─────────────────────────────────────────────────

function FlowGraphInner({ events, live }) {
  const [selectedEvent, setSelectedEvent] = useState(null);
  const { fitView } = useReactFlow();

  const latestEventId = events[events.length - 1]?.event_id;

  const { nodes: rawNodes, edges: rawEdges } = useMemo(
    () => buildGraph(events, selectedEvent?.event_id, setSelectedEvent, live ? latestEventId : null),
    [events, selectedEvent?.event_id, live, latestEventId],
  );

  const [nodes, , onNodesChange]   = useNodesState(rawNodes);
  const [edges, , onEdgesChange]   = useEdgesState(rawEdges);

  // Re-apply when nodes/edges change from new polling data
  useEffect(() => {
    onNodesChange(rawNodes.map((n) => ({ type: 'reset', item: n })));
    onEdgesChange(rawEdges.map((e) => ({ type: 'reset', item: e })));
  }, [rawNodes, rawEdges]); // eslint-disable-line react-hooks/exhaustive-deps

  // Fit view on first render and whenever live adds new nodes
  useEffect(() => {
    setTimeout(() => fitView({ padding: 0.15, duration: 400 }), 100);
  }, [events.length]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="flex h-full">
      <div className="flex-1 min-w-0" style={{ height: 520 }}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.15 }}
          minZoom={0.3}
          maxZoom={1.5}
          attributionPosition="bottom-right"
        >
          <Background color="#334155" gap={20} size={1} />
          <Controls
            style={{ background: '#1e293b', border: '1px solid #334155' }}
            showInteractive={false}
          />
          <MiniMap
            nodeColor={(n) => blockDef(n.data?.event?.block_type).color + '80'}
            maskColor="#0f172a99"
            style={{ background: '#1e293b', border: '1px solid #334155' }}
          />
        </ReactFlow>
      </div>
      {selectedEvent && (
        <EventDetailPanel event={selectedEvent} onClose={() => setSelectedEvent(null)} />
      )}
    </div>
  );
}

// ── Option C: Funnel chart ────────────────────────────────────────────────────

const FUNNEL_DROP_THRESHOLDS = { low: 5, mid: 15 }; // % drop — above mid = red

function dropColor(pct) {
  if (!pct) return '#22d3ee';
  if (pct > FUNNEL_DROP_THRESHOLDS.mid) return '#f43f5e';
  if (pct > FUNNEL_DROP_THRESHOLDS.low) return '#f59e0b';
  return '#22d3ee';
}

function FunnelTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div className="rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-2 text-xs shadow-xl">
      <p className="font-semibold text-slate-800 dark:text-slate-200 mb-1">{d.block_name}</p>
      <p className="text-slate-500 dark:text-slate-400">Type: <span className="text-slate-700 dark:text-slate-300">{d.block_type}</span></p>
      <p className="text-slate-500 dark:text-slate-400">Contacts reached: <span className="text-emerald-600 dark:text-emerald-400 font-semibold">{d.count}</span></p>
      <p className="text-slate-500 dark:text-slate-400">% of total: <span className="text-cyan-600 dark:text-cyan-400 font-semibold">{d.pct?.toFixed(1)}%</span></p>
      {d.drop_count > 0 && (
        <p className="text-slate-500 dark:text-slate-400 mt-1">
          Drop before next: <span className="font-semibold" style={{ color: dropColor(d.drop_pct) }}>
            {d.drop_count} ({d.drop_pct?.toFixed(1)}%)
          </span>
        </p>
      )}
    </div>
  );
}

function FlowFunnelChart({ data }) {
  if (!data?.blocks?.length) {
    return (
      <div className="flex h-64 items-center justify-center text-xs text-slate-600 dark:text-slate-500">
        No funnel data available
      </div>
    );
  }

  const total = data.total_contacts;
  const height = Math.max(data.blocks.length * 52 + 80, 300);

  const chartData = [...data.blocks].reverse(); // recharts horizontal renders bottom→top so we reverse

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-4 text-xs text-slate-500 dark:text-slate-400">
        <span><span className="text-slate-800 dark:text-slate-200 font-semibold">{total}</span> total contacts over {data.period_days} days</span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full bg-cyan-400" /> Low drop-off
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full bg-amber-400" /> Moderate drop-off
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full bg-rose-400" /> High drop-off
        </span>
      </div>

      <ResponsiveContainer width="100%" height={height}>
        <BarChart
          layout="vertical"
          data={chartData}
          margin={{ top: 4, right: 80, bottom: 4, left: 200 }}
          barSize={28}
        >
          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" horizontal={false} />
          <XAxis
            type="number"
            domain={[0, total]}
            tick={{ fill: '#64748b', fontSize: 10 }}
            tickLine={{ stroke: '#334155' }}
            axisLine={{ stroke: '#334155' }}
          />
          <YAxis
            type="category"
            dataKey="block_name"
            width={195}
            tick={{ fill: '#cbd5e1', fontSize: 10 }}
            tickLine={false}
            axisLine={false}
          />
          <Tooltip content={<FunnelTooltip />} />
          <Bar dataKey="count" radius={[0, 4, 4, 0]}>
            {chartData.map((entry, i) => (
              <Cell key={i} fill={dropColor(entry.drop_pct)} fillOpacity={0.75} />
            ))}
            <LabelList
              dataKey="count"
              position="right"
              formatter={(v) => `${v} (${chartData.find((d) => d.count === v)?.pct?.toFixed(0)}%)`}
              style={{ fill: '#94a3b8', fontSize: 10 }}
            />
          </Bar>
        </BarChart>
      </ResponsiveContainer>

      {/* Step-by-step drop table */}
      <div className="mt-4 overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-slate-200 dark:border-slate-800">
              <th className="text-left py-2 px-3 font-medium text-slate-600 dark:text-slate-500">#</th>
              <th className="text-left py-2 px-3 font-medium text-slate-600 dark:text-slate-500">Block</th>
              <th className="text-right py-2 px-3 font-medium text-slate-600 dark:text-slate-500">Contacts</th>
              <th className="text-right py-2 px-3 font-medium text-slate-600 dark:text-slate-500">% Remaining</th>
              <th className="text-right py-2 px-3 font-medium text-slate-600 dark:text-slate-500">Drop-off</th>
            </tr>
          </thead>
          <tbody>
            {data.blocks.map((b, i) => {
              const def = blockDef(b.block_type);
              return (
                <tr key={i} className="border-b border-slate-200 dark:border-slate-800/40 hover:bg-slate-100 dark:hover:bg-slate-800/20">
                  <td className="py-2 px-3 text-slate-600">{b.sequence}</td>
                  <td className="py-2 px-3">
                    <div className="flex items-center gap-1.5">
                      <span
                        className="h-1.5 w-1.5 rounded-full shrink-0"
                        style={{ background: def.color }}
                      />
                      <span className="text-slate-700 dark:text-slate-300">{b.block_name}</span>
                      <span
                        className="ml-1 text-[9px] rounded-full px-1.5 py-0.5"
                        style={{ background: def.color + '20', color: def.color }}
                      >
                        {def.label}
                      </span>
                    </div>
                  </td>
                  <td className="py-2 px-3 text-right font-semibold text-slate-800 dark:text-slate-200 tabular-nums">{b.count}</td>
                  <td className="py-2 px-3 text-right tabular-nums">
                    <div className="flex items-center justify-end gap-2">
                      <div className="w-20 bg-slate-200 dark:bg-slate-800 rounded-full h-1.5">
                        <div
                          className="h-1.5 rounded-full"
                          style={{ width: `${b.pct}%`, background: def.color }}
                        />
                      </div>
                      <span className="text-slate-700 dark:text-slate-300 w-9">{b.pct?.toFixed(1)}%</span>
                    </div>
                  </td>
                  <td className="py-2 px-3 text-right tabular-nums">
                    {b.drop_count > 0 ? (
                      <span className="font-semibold" style={{ color: dropColor(b.drop_pct) }}>
                        −{b.drop_count} ({b.drop_pct?.toFixed(1)}%)
                      </span>
                    ) : (
                      <span className="text-slate-600">—</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Flow summary header ───────────────────────────────────────────────────────

function FlowSummaryHeader({ flowData }) {
  if (!flowData?.events?.length) return null;
  const flows = flowData.flows_traversed || [];
  const totalMs = flowData.total_duration_ms || 0;
  return (
    <div className="flex flex-wrap items-center gap-4 text-xs text-slate-500 dark:text-slate-400 mb-3 px-1">
      <span>
        <span className="text-slate-800 dark:text-slate-200 font-semibold">{flowData.event_count}</span> blocks
      </span>
      <span>
        Duration: <span className="text-slate-800 dark:text-slate-200 font-semibold">{fmtDuration(totalMs)}</span>
      </span>
      <div className="flex flex-wrap gap-1.5">
        {flows.map((f) => (
          <span
            key={f}
            className="rounded-full bg-indigo-500/15 px-2 py-0.5 text-indigo-600 dark:text-indigo-300 text-[10px] font-medium"
          >
            {f}
          </span>
        ))}
      </div>
      {flowData.mock && (
        <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-amber-600 dark:text-amber-400 text-[10px]">
          sample data
        </span>
      )}
    </div>
  );
}

// ── Main exported component ───────────────────────────────────────────────────

export default function ContactFlowGraph({ contactId, live = false, onClose }) {
  const [flowData, setFlowData] = useState(null);
  const [loading, setLoading]   = useState(false);
  const [error, setError]       = useState(null);
  const pollRef                 = useRef(null);

  const loadFlowEvents = useCallback(async () => {
    if (!contactId) return;
    try {
      const data = await getContactFlowEvents(contactId);
      setFlowData(data);
      setError(null);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Failed to load flow events');
    }
  }, [contactId]);

  // Initial load
  useEffect(() => {
    setLoading(true);
    loadFlowEvents().finally(() => setLoading(false));
  }, [loadFlowEvents]);

  // Live polling
  useEffect(() => {
    if (!live) return;
    pollRef.current = setInterval(loadFlowEvents, 8000);
    return () => clearInterval(pollRef.current);
  }, [live, loadFlowEvents]);

  const events = flowData?.events || [];

  return (
    <div className="flex flex-col rounded-2xl border border-slate-300 dark:border-slate-700/60 bg-white dark:bg-slate-900 overflow-hidden">
      {/* ── Panel header ── */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900/80">
        <div className="flex items-center gap-3">
          <div className="rounded-lg bg-indigo-500/15 p-1.5">
            <Network size={15} className="text-indigo-600 dark:text-indigo-400" />
          </div>
          <div>
            <p className="text-sm font-semibold text-slate-800 dark:text-slate-200">
              Contact Flow Journey
              {live && (
                <span className="ml-2 inline-flex items-center gap-1 text-[9px] rounded-full bg-emerald-500/20 px-2 py-0.5 text-emerald-600 dark:text-emerald-400">
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
                  LIVE
                </span>
              )}
            </p>
            <p className="text-[10px] text-slate-600 dark:text-slate-500 font-mono truncate max-w-xs">{contactId}</p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={loadFlowEvents}
            className="rounded-lg border border-slate-300 dark:border-slate-700 bg-slate-100 dark:bg-slate-800 p-1.5 text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:hover:text-slate-200 transition"
            title="Refresh"
          >
            <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
          </button>

          {onClose && (
            <button
              onClick={onClose}
              className="rounded-lg border border-slate-300 dark:border-slate-700 bg-slate-100 dark:bg-slate-800 p-1.5 text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:hover:text-slate-200 transition"
            >
              <X size={13} />
            </button>
          )}
        </div>
      </div>

      {/* ── Content ── */}
      <div className="flex-1 overflow-auto p-4">
        {loading && (
          <div className="flex h-64 items-center justify-center gap-2 text-sm text-slate-500 dark:text-slate-400">
            <RefreshCw size={16} className="animate-spin text-indigo-600 dark:text-indigo-400" />
            Loading flow events…
          </div>
        )}

        {!loading && error && (
          <div className="flex items-center gap-3 rounded-xl border border-rose-500/25 bg-rose-500/10 px-4 py-3 text-sm text-rose-600 dark:text-rose-300">
            <AlertCircle size={16} />
            {error}
          </div>
        )}

        {!loading && !error && (
          <>
            <FlowSummaryHeader flowData={flowData} />
            {events.length === 0 ? (
              <div className="flex h-64 flex-col items-center justify-center gap-3 text-slate-600 dark:text-slate-500">
                <Activity size={32} className="opacity-30" />
                <p className="text-sm">No flow events found for this contact.</p>
                <p className="text-xs">Ensure flow logging is enabled in Amazon Connect.</p>
              </div>
            ) : (
              <ReactFlowProvider>
                <FlowGraphInner events={events} live={live} />
              </ReactFlowProvider>
            )}
          </>
        )}
      </div>
    </div>
  );
}
